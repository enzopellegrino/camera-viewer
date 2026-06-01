"""Provisioning web server for the Raspberry Pi Camera Viewer.

Serves a mobile-first configuration page where the user sets up:
  - network (WiFi scan/connect, or ethernet via DHCP)
  - cameras (RTSP CRUD)
  - viewer settings (layout, fps)

Runs on port 8080 in dev; in captive-portal mode it is fronted on port 80.
Includes the well-known captive-portal detection endpoints so phones/PCs pop
the login page automatically.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import uuid
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

from . import config_store as store
from . import network
from . import vpn
from . import vpn_openvpn

app = Flask(__name__, static_folder="static", template_folder="templates")

# ── Flask session secret key (persistent across restarts) ────────────────────
_SECRET_FILE = os.path.expanduser("~/.config/camera-viewer/.flask_secret")


def _load_secret() -> bytes:
    try:
        if os.path.exists(_SECRET_FILE):
            return open(_SECRET_FILE, "rb").read()
    except OSError:
        pass
    key = os.urandom(32)
    try:
        os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
        open(_SECRET_FILE, "wb").write(key)
    except OSError:
        pass
    return key


app.secret_key = _load_secret()
app.permanent_session_lifetime = timedelta(hours=8)

# Host the portal redirects to (set by the launcher in AP mode)
PORTAL_HOST = os.environ.get("PORTAL_HOST", "")


# ── Auth helpers ─────────────────────────────────────────────────────────────

def login_required(admin: bool = False):
    """Decorator: require authenticated session. admin=True requires admin role."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return jsonify({"ok": False, "error": "Non autenticato"}), 401
            if admin and session.get("role") != "admin":
                return jsonify({"ok": False, "error": "Accesso riservato agli amministratori"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")
    return send_from_directory(app.template_folder, "index.html")


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect("/")
    return send_from_directory(app.template_folder, "login.html")


# ── API: Auth ────────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = store.get_user_by_username(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "message": "Credenziali non valide"}), 401
    session.permanent = True
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    session["role"]     = user["role"]
    return jsonify({"ok": True, "username": user["username"], "role": user["role"]})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me")
def api_auth_me():
    if "user_id" not in session:
        return jsonify({"ok": False, "authenticated": False}), 401
    return jsonify({
        "ok": True, "authenticated": True,
        "username": session["username"],
        "role":     session["role"],
    })


# ── API: Site name ────────────────────────────────────────────────────────────

@app.route("/api/site-name", methods=["GET"])
def api_site_name_get():
    return jsonify({"ok": True, "name": store.get_site_name()})


@app.route("/api/site-name", methods=["POST"])
@login_required(admin=True)
def api_site_name_set():
    data = request.get_json(force=True, silent=True) or {}
    store.set_site_name(data.get("name", ""))
    return jsonify({"ok": True, "name": store.get_site_name()})


# ── API: Screens (views) ─────────────────────────────────────────────────────

@app.route("/api/screens", methods=["GET"])
@login_required()
def api_screens_list():
    return jsonify({
        "screens": store.list_screens(),
        "active_screen_id": store.get_active_screen_id(),
    })


@app.route("/api/screens", methods=["POST"])
@login_required(admin=True)
def api_screens_upsert():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "Il nome è obbligatorio"}), 400
    screen = store.upsert_screen(data)
    return jsonify({"ok": True, "screen": screen})


@app.route("/api/screens/<sid>", methods=["PUT"])
@login_required(admin=True)
def api_screens_update(sid: str):
    data = request.get_json(force=True, silent=True) or {}
    data["id"] = sid
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "Il nome è obbligatorio"}), 400
    screen = store.upsert_screen(data)
    return jsonify({"ok": True, "screen": screen})


@app.route("/api/screens/<sid>", methods=["DELETE"])
@login_required(admin=True)
def api_screens_delete(sid: str):
    # Cannot delete last screen
    if len(store.list_screens()) <= 1:
        return jsonify({"ok": False, "message": "Non puoi eliminare l'ultima vista"}), 400
    ok = store.delete_screen(sid)
    return jsonify({"ok": ok})


@app.route("/api/screens/<sid>/activate", methods=["POST"])
@login_required()
def api_screens_activate(sid: str):
    ok = store.set_active_screen(sid)
    if not ok:
        return jsonify({"ok": False, "message": "Vista non trovata"}), 404
    # Send command to viewer
    try:
        with open(_VIEWER_CMD_FILE, "w") as f:
            f.write(f"screen:{sid}")
    except OSError:
        pass
    return jsonify({"ok": True, "active_screen_id": sid})


# ── API: Users ────────────────────────────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
@login_required(admin=True)
def api_users_list():
    return jsonify({"users": store.list_users()})


@app.route("/api/users", methods=["POST"])
@login_required(admin=True)
def api_users_create():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role     = data.get("role", "operator")
    if not username or not password:
        return jsonify({"ok": False, "message": "Username e password obbligatori"}), 400
    if role not in store.VALID_ROLES:
        return jsonify({"ok": False, "message": "Ruolo non valido"}), 400
    if store.get_user_by_username(username):
        return jsonify({"ok": False, "message": "Username già in uso"}), 400
    user = store.create_user(username, generate_password_hash(password), role)
    return jsonify({"ok": True, "user": user})


@app.route("/api/users/<uid>/password", methods=["PUT"])
@login_required()
def api_users_change_password(uid: str):
    # Admin can change any password; user can only change own
    if session.get("role") != "admin" and session.get("user_id") != uid:
        return jsonify({"ok": False, "message": "Non autorizzato"}), 403
    data = request.get_json(force=True, silent=True) or {}
    password = (data.get("password") or "").strip()
    if len(password) < 4:
        return jsonify({"ok": False, "message": "Password troppo corta (min 4 caratteri)"}), 400
    ok = store.update_user_password(uid, generate_password_hash(password))
    return jsonify({"ok": ok})


@app.route("/api/users/<uid>", methods=["DELETE"])
@login_required(admin=True)
def api_users_delete(uid: str):
    if session.get("user_id") == uid:
        return jsonify({"ok": False, "message": "Non puoi eliminare te stesso"}), 400
    ok = store.delete_user(uid)
    if not ok:
        return jsonify({"ok": False, "message": "Impossibile eliminare (ultimo admin?)"}), 400
    return jsonify({"ok": True})


# ── Captive portal detection (iOS / Android / Windows) ───────────────────────
# These OS-specific URLs are probed by devices to detect a captive portal.
# Returning a redirect (or a non-"success" body) triggers the login popup.

@app.route("/generate_204")          # Android
@app.route("/gen_204")               # Android (alt)
@app.route("/hotspot-detect.html")   # iOS / macOS
@app.route("/library/test/success.html")  # iOS (alt)
@app.route("/ncsi.txt")              # Windows
@app.route("/connecttest.txt")       # Windows
@app.route("/redirect")              # Windows
def captive_detect():
    target = f"http://{PORTAL_HOST}/" if PORTAL_HOST else "/"
    return redirect(target, code=302)


# ── API: status & network ────────────────────────────────────────────────────

@app.route("/api/status")
@login_required()
def api_status():
    return jsonify(network.current_status())


@app.route("/api/wifi/scan")
@login_required()
def api_wifi_scan():
    return jsonify({"networks": network.scan_wifi()})


@app.route("/api/wifi/connect", methods=["POST"])
@login_required(admin=True)
def api_wifi_connect():
    data = request.get_json(force=True, silent=True) or {}
    ssid = data.get("ssid", "")
    password = data.get("password", "")
    ok, msg = network.connect_wifi(ssid, password)
    if ok:
        def _net(cfg):
            cfg.setdefault("network", {})["mode"] = "wifi"
            cfg["network"]["ssid"] = ssid
        store.mutate(_net)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/network/mode", methods=["POST"])
@login_required(admin=True)
def api_network_mode():
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "dhcp")
    def _net(cfg):
        cfg.setdefault("network", {})["mode"] = mode
    store.mutate(_net)
    return jsonify({"ok": True, "mode": mode})


# ── API: cameras ──────────────────────────────────────────────────────────────

@app.route("/api/cameras", methods=["GET"])
@login_required()
def api_cameras_list():
    return jsonify({"cameras": store.list_cameras(), "layout": store.get_layout()})


@app.route("/api/cameras", methods=["POST"])
@login_required(admin=True)
def api_cameras_upsert():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "Il nome è obbligatorio"}), 400
    if not (url.lower().startswith("rtsp://") or url.lower().startswith("srt://")):
        return jsonify({"ok": False, "message": "L'URL deve iniziare con rtsp:// o srt://"}), 400
    entry = store.upsert_camera(data)
    return jsonify({"ok": True, "camera": entry})


@app.route("/api/cameras/<cam_id>", methods=["DELETE"])
@login_required(admin=True)
def api_cameras_delete(cam_id: str):
    ok = store.delete_camera(cam_id)
    return jsonify({"ok": ok})


# ── API: settings / layout ────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
@login_required()
def api_settings_get():
    return jsonify({"settings": store.get_settings(), "layout": store.get_layout()})


@app.route("/api/settings", methods=["POST"])
@login_required(admin=True)
def api_settings_set():
    data = request.get_json(force=True, silent=True) or {}
    patch = {}
    if "render_fps" in data:
        try:
            fps = int(data["render_fps"])
            if 5 <= fps <= 60:
                patch["render_fps"] = fps
        except (ValueError, TypeError):
            pass
    if "reconnect_delay_ms" in data:
        try:
            ms = int(data["reconnect_delay_ms"])
            if ms > 0:
                patch["reconnect_delay_ms"] = ms
        except (ValueError, TypeError):
            pass
    if patch:
        store.update_settings(patch)
    if "layout" in data:
        try:
            store.set_layout(data["layout"])
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400
    return jsonify({"ok": True, "settings": store.get_settings(), "layout": store.get_layout()})


@app.route("/api/restart-viewer", methods=["POST"])
@login_required()
def api_restart_viewer():
    """Kill the viewer and relaunch it with the correct display environment.

    No sudo needed — viewer and Flask both run as user pi.
    """
    import signal as _signal
    import time as _time

    # Kill any running viewer instance
    for proc in os.popen("pgrep -f 'python3 main.py'").read().split():
        try:
            os.kill(int(proc), _signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass

    _time.sleep(1)  # give it time to exit cleanly

    # Relaunch via cv-viewer-launch which handles the operational mode check.
    env = os.environ.copy()
    env.update({
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "QT_QPA_PLATFORM": "xcb",
        "CAMERA_VIEWER_CONFIG": str(store.config_path()),
    })
    subprocess.Popen(
        ["/usr/local/sbin/cv-viewer-launch"],
        env=env,
        stdout=open("/tmp/viewer.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return jsonify({"ok": True, "message": "Viewer riavviato"})


# ── API: Viewer remote control ────────────────────────────────────────────────

_VIEWER_CMD_FILE = "/tmp/cv-viewer-cmd"


@app.route("/api/viewer/zoom", methods=["POST"])
@login_required()
def api_viewer_zoom():
    """Zoom a specific camera on the monitor (portal remote control).

    Body: {"camera_id": "<id>"}  → zoom that camera
          {"camera_id": null}    → return to grid
    """
    data = request.get_json(force=True, silent=True) or {}
    cam_id = data.get("camera_id")
    cmd = f"zoom:{cam_id}" if cam_id else "grid"
    try:
        with open(_VIEWER_CMD_FILE, "w") as f:
            f.write(cmd)
        return jsonify({"ok": True, "cmd": cmd})
    except OSError as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ── API: Wallpaper ────────────────────────────────────────────────────────────

_WALLPAPER_PATH = os.path.expanduser("~/.config/camera-viewer/wallpaper.jpg")
_PCMANFM_CONF_GLOB = os.path.expanduser(
    "~/.config/pcmanfm/default/desktop-items-*.conf"
)
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _set_pcmanfm_wallpaper(path: str) -> None:
    """Update all pcmanfm desktop config files with the new wallpaper path."""
    import glob as _glob, configparser as _cp

    for conf_file in _glob.glob(_PCMANFM_CONF_GLOB):
        cfg = _cp.RawConfigParser()
        cfg.read(conf_file)
        if not cfg.has_section("*"):
            cfg.add_section("*")
        cfg.set("*", "wallpaper", path)
        cfg.set("*", "wallpaper_mode", "crop")
        with open(conf_file, "w") as f:
            cfg.write(f)

    # Signal pcmanfm to reload (SIGHUP)
    env = {
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
        "HOME": os.path.expanduser("~"),
    }
    subprocess.run(
        ["pcmanfm", "--set-wallpaper", path, "--wallpaper-mode=crop"],
        env={**os.environ, **env},
        timeout=5,
        check=False,
        capture_output=True,
    )


@app.route("/api/wallpaper", methods=["GET"])
@login_required()
def api_wallpaper_get():
    exists = os.path.exists(_WALLPAPER_PATH)
    return jsonify({"ok": True, "custom": exists,
                    "url": "/api/wallpaper/image" if exists else None})


@app.route("/api/wallpaper/image", methods=["GET"])
@login_required()
def api_wallpaper_image():
    if not os.path.exists(_WALLPAPER_PATH):
        return "", 404
    return send_from_directory(
        os.path.dirname(_WALLPAPER_PATH),
        os.path.basename(_WALLPAPER_PATH),
    )


@app.route("/api/wallpaper", methods=["POST"])
@login_required(admin=True)
def api_wallpaper_set():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "message": "Nessun file ricevuto"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({"ok": False,
                        "message": "Formato non supportato (usa JPG, PNG, BMP, WEBP)"}), 400

    os.makedirs(os.path.dirname(_WALLPAPER_PATH), exist_ok=True)
    f.save(_WALLPAPER_PATH)

    try:
        _set_pcmanfm_wallpaper(_WALLPAPER_PATH)
    except Exception as e:
        return jsonify({"ok": False, "message": f"Salvataggio OK ma errore applicazione: {e}"}), 500

    return jsonify({"ok": True, "message": "Sfondo aggiornato"})


@app.route("/api/wallpaper", methods=["DELETE"])
@login_required(admin=True)
def api_wallpaper_delete():
    default = "/usr/share/rpd-wallpaper/aurora.jpg"
    if os.path.exists(_WALLPAPER_PATH):
        os.remove(_WALLPAPER_PATH)
    try:
        _set_pcmanfm_wallpaper(default)
    except Exception:
        pass
    return jsonify({"ok": True, "message": "Sfondo ripristinato"})


# ── API: Placeholder telecamera ───────────────────────────────────────────────

_PLACEHOLDER_PATH = os.path.expanduser("~/.config/camera-viewer/placeholder.jpg")


@app.route("/api/placeholder", methods=["GET"])
@login_required()
def api_placeholder_get():
    exists = os.path.exists(_PLACEHOLDER_PATH)
    return jsonify({"ok": True, "custom": exists,
                    "url": "/api/placeholder/image" if exists else None})


@app.route("/api/placeholder/image", methods=["GET"])
@login_required()
def api_placeholder_image():
    if not os.path.exists(_PLACEHOLDER_PATH):
        return "", 404
    return send_from_directory(
        os.path.dirname(_PLACEHOLDER_PATH),
        os.path.basename(_PLACEHOLDER_PATH),
    )


@app.route("/api/placeholder", methods=["POST"])
@login_required(admin=True)
def api_placeholder_set():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "message": "Nessun file ricevuto"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({"ok": False,
                        "message": "Formato non supportato (usa JPG, PNG, WEBP)"}), 400
    os.makedirs(os.path.dirname(_PLACEHOLDER_PATH), exist_ok=True)
    # Salva sempre come .jpg per semplicità (il path è fisso)
    f.save(_PLACEHOLDER_PATH)
    return jsonify({"ok": True, "message": "Logo aggiornato. Apparirà alla prossima disconnessione."})


@app.route("/api/placeholder", methods=["DELETE"])
@login_required(admin=True)
def api_placeholder_delete():
    if os.path.exists(_PLACEHOLDER_PATH):
        os.remove(_PLACEHOLDER_PATH)
    return jsonify({"ok": True, "message": "Logo rimosso"})


# ── API: VPN Profiles ────────────────────────────────────────────────────────

@app.route("/api/vpn/profiles", methods=["GET"])
@login_required()
def api_vpn_profiles_list():
    """Sync profile active flag with the real tunnel state."""
    ovpn_st  = vpn_openvpn.status()
    wg_st    = vpn.status()
    tunnel_up = ovpn_st["active"] or wg_st["active"]

    marked_active = store.get_active_vpn_profile()
    profiles      = store.list_vpn_profiles(mask_sensitive=True)

    if tunnel_up and not marked_active and len(profiles) == 1:
        # Tunnel is running but no profile is marked — auto-sync the only profile
        store.set_vpn_profile_active(profiles[0]["id"])
        marked_active = {"id": profiles[0]["id"]}

    elif not tunnel_up and marked_active:
        # Tunnel stopped (boot failure, network error) — clear stale active flag
        store.set_vpn_profile_active(None)
        marked_active = None

    return jsonify({
        "profiles": store.list_vpn_profiles(mask_sensitive=True),
        "active_id": (marked_active or {}).get("id"),
    })


@app.route("/api/vpn/profiles", methods=["POST"])
@login_required(admin=True)
def api_vpn_profiles_create():
    data = request.get_json(force=True, silent=True) or {}
    if not (data.get("name") or "").strip():
        return jsonify({"ok": False, "message": "Il nome del profilo è obbligatorio"}), 400
    profile = store.upsert_vpn_profile(data)
    return jsonify({"ok": True, "profile": {k: v for k, v in profile.items()
                                             if k not in store._VPN_SENSITIVE}})


@app.route("/api/vpn/profiles/<pid>", methods=["PUT"])
@login_required(admin=True)
def api_vpn_profiles_update(pid: str):
    data = request.get_json(force=True, silent=True) or {}
    data["id"] = pid
    if not (data.get("name") or "").strip():
        return jsonify({"ok": False, "message": "Il nome del profilo è obbligatorio"}), 400
    profile = store.upsert_vpn_profile(data)
    return jsonify({"ok": True, "profile": {k: v for k, v in profile.items()
                                             if k not in store._VPN_SENSITIVE}})


@app.route("/api/vpn/profiles/<pid>", methods=["DELETE"])
@login_required(admin=True)
def api_vpn_profiles_delete(pid: str):
    # Deactivate before deleting if it's active
    active = store.get_active_vpn_profile()
    if active and active.get("id") == pid:
        vpn.disable()
        vpn_openvpn.disable()
        store.set_vpn_profile_active(None)
    ok = store.delete_vpn_profile(pid)
    return jsonify({"ok": ok})


@app.route("/api/vpn/profiles/<pid>/activate", methods=["POST"])
@login_required(admin=True)
def api_vpn_profiles_activate(pid: str):
    """Activate a VPN profile: apply the tunnel and mark it as active."""
    profile = store.get_vpn_profile_raw(pid)
    if not profile:
        return jsonify({"ok": False, "message": "Profilo non trovato"}), 404

    subnets = profile.get("camera_subnets", [])
    enable_on_boot = profile.get("auto_connect", True)
    protocol = profile.get("protocol", "openvpn")

    # Tear down any existing tunnel first
    vpn.disable()
    vpn_openvpn.disable()

    if protocol == "openvpn":
        ok, msg = vpn_openvpn.apply_config(
            profile.get("conf_text", ""),
            subnets,
            username=profile.get("username", ""),
            password=profile.get("password", ""),
            enable_on_boot=enable_on_boot,
        )
    else:
        # WireGuard
        try:
            if profile.get("mode") == "file" or profile.get("conf_text"):
                fields = vpn.parse_wg_conf(profile.get("conf_text", ""))
            else:
                fields = {k: profile.get(k, "") for k in
                          ("private_key", "address", "peer_public_key",
                           "preshared_key", "endpoint")}
            conf_text = vpn.build_split_tunnel_conf(fields, subnets)
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400
        ok, msg = vpn.apply_config(conf_text, enable_on_boot=enable_on_boot)

    if ok:
        store.set_vpn_profile_active(pid)

    return jsonify({"ok": ok, "message": msg})


@app.route("/api/vpn/profiles/<pid>/deactivate", methods=["POST"])
@login_required(admin=True)
def api_vpn_profiles_deactivate(pid: str):
    """Deactivate the VPN tunnel and clear the active flag."""
    ok1, _ = vpn.disable()
    ok2, _ = vpn_openvpn.disable()
    store.set_vpn_profile_active(None)
    return jsonify({"ok": True, "message": "VPN disattivata"})


# ── API: VPN (WireGuard split-tunnel) ────────────────────────────────────────

def _parse_subnets(value) -> list[str]:
    """Accept a list or a string with comma/newline separated subnets."""
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[,\n;]+", str(value or ""))
    return [s.strip() for s in items if s.strip()]


@app.route("/api/vpn", methods=["GET"])
@login_required()
def api_vpn_status():
    """Report the active/configured tunnel (WireGuard or OpenVPN)."""
    ovpn = vpn_openvpn.status()
    if ovpn["active"] or ovpn["configured"]:
        return jsonify({"protocol": "openvpn", **ovpn})
    wg = vpn.status()
    return jsonify({"protocol": "wireguard", **wg})


@app.route("/api/vpn", methods=["POST"])
@login_required(admin=True)
def api_vpn_apply():
    data = request.get_json(force=True, silent=True) or {}
    subnets = _parse_subnets(data.get("camera_subnets"))
    protocol = data.get("protocol", "wireguard")
    enable_on_boot = bool(data.get("enable_on_boot", True))

    if protocol == "openvpn":
        # Only one tunnel at a time: tear down WireGuard first.
        vpn.remove()
        ok, msg = vpn_openvpn.apply_config(
            data.get("conf_text", ""), subnets,
            username=data.get("username", ""), password=data.get("password", ""),
            enable_on_boot=enable_on_boot,
        )
        if ok:
            validated = vpn.validate_subnets(subnets)
            def _v(cfg):
                cfg["vpn"] = {"enabled": True, "protocol": "openvpn",
                              "camera_subnets": validated}
            store.mutate(_v)
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)

    # WireGuard
    vpn_openvpn.remove()  # only one tunnel at a time
    mode = data.get("mode", "manual")
    try:
        if mode == "file":
            fields = vpn.parse_wg_conf(data.get("conf_text", ""))
        else:
            fields = {
                "private_key": data.get("private_key", ""),
                "address": data.get("address", ""),
                "peer_public_key": data.get("peer_public_key", ""),
                "preshared_key": data.get("preshared_key", ""),
                "endpoint": data.get("endpoint", ""),
            }
        conf_text = vpn.build_split_tunnel_conf(fields, subnets)
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400

    ok, msg = vpn.apply_config(conf_text, enable_on_boot=enable_on_boot)
    if ok:
        validated = vpn.validate_subnets(subnets)
        def _v(cfg):
            cfg["vpn"] = {"enabled": True, "protocol": "wireguard",
                          "camera_subnets": validated}
        store.mutate(_v)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/vpn/disable", methods=["POST"])
@login_required(admin=True)
def api_vpn_disable():
    # disable whichever is active
    ok1, _ = vpn.disable()
    ok2, _ = vpn_openvpn.disable()
    ok = ok1 or ok2
    if ok:
        def _v(cfg):
            cfg.setdefault("vpn", {})["enabled"] = False
        store.mutate(_v)
    return jsonify({"ok": ok, "message": "VPN disattivata"})


@app.route("/api/vpn", methods=["DELETE"])
@login_required(admin=True)
def api_vpn_remove():
    vpn.remove()
    vpn_openvpn.remove()
    def _v(cfg):
        cfg["vpn"] = {"enabled": False}
    store.mutate(_v)
    return jsonify({"ok": True, "message": "VPN rimossa"})


# ── API: mode transitions (apply & reboot) ───────────────────────────────────

def _reboot_soon(delay: float = 2.0):
    """Reboot shortly, so the HTTP response can reach the client first."""
    def go():
        subprocess.run(["sudo", "-n", "/usr/local/sbin/cv-mode", "reboot"], check=False)
    threading.Timer(delay, go).start()


@app.route("/api/apply", methods=["POST"])
@login_required(admin=True)
def api_apply():
    """Finish setup: switch to operational mode and reboot."""
    if not store.has_cameras():
        return jsonify({"ok": False,
                        "message": "Aggiungi almeno una telecamera prima di avviare"}), 400
    store.set_force_setup(False)
    _reboot_soon()
    return jsonify({"ok": True,
                    "message": "Configurazione salvata. Il dispositivo si riavvia e mostra le telecamere…"})


@app.route("/api/setup-mode", methods=["POST"])
@login_required(admin=True)
def api_setup_mode():
    """Re-enter provisioning mode on next boot."""
    store.set_force_setup(True)
    _reboot_soon()
    return jsonify({"ok": True, "message": "Riavvio in modalità configurazione…"})


@app.route("/api/mode")
@login_required()
def api_mode():
    """Report whether the device would boot into provisioning."""
    return jsonify({
        "provisioning": store.should_provision(),
        "has_cameras": store.has_cameras(),
        "force_setup": store.is_force_setup(),
    })


def main():
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=bool(os.environ.get("DEBUG")))


if __name__ == "__main__":
    main()
