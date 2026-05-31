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

from flask import Flask, jsonify, redirect, request, send_from_directory

from . import config_store as store
from . import network
from . import vpn
from . import vpn_openvpn

app = Flask(__name__, static_folder="static", template_folder="templates")

# Host the portal redirects to (set by the launcher in AP mode)
PORTAL_HOST = os.environ.get("PORTAL_HOST", "")


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


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
def api_status():
    return jsonify(network.current_status())


@app.route("/api/wifi/scan")
def api_wifi_scan():
    return jsonify({"networks": network.scan_wifi()})


@app.route("/api/wifi/connect", methods=["POST"])
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
def api_network_mode():
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "dhcp")
    def _net(cfg):
        cfg.setdefault("network", {})["mode"] = mode
    store.mutate(_net)
    return jsonify({"ok": True, "mode": mode})


# ── API: cameras ──────────────────────────────────────────────────────────────

@app.route("/api/cameras", methods=["GET"])
def api_cameras_list():
    return jsonify({"cameras": store.list_cameras(), "layout": store.get_layout()})


@app.route("/api/cameras", methods=["POST"])
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
def api_cameras_delete(cam_id: str):
    ok = store.delete_camera(cam_id)
    return jsonify({"ok": ok})


# ── API: settings / layout ────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify({"settings": store.get_settings(), "layout": store.get_layout()})


@app.route("/api/settings", methods=["POST"])
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
def api_wallpaper_get():
    exists = os.path.exists(_WALLPAPER_PATH)
    return jsonify({"ok": True, "custom": exists,
                    "url": "/api/wallpaper/image" if exists else None})


@app.route("/api/wallpaper/image", methods=["GET"])
def api_wallpaper_image():
    if not os.path.exists(_WALLPAPER_PATH):
        return "", 404
    return send_from_directory(
        os.path.dirname(_WALLPAPER_PATH),
        os.path.basename(_WALLPAPER_PATH),
    )


@app.route("/api/wallpaper", methods=["POST"])
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
def api_placeholder_get():
    exists = os.path.exists(_PLACEHOLDER_PATH)
    return jsonify({"ok": True, "custom": exists,
                    "url": "/api/placeholder/image" if exists else None})


@app.route("/api/placeholder/image", methods=["GET"])
def api_placeholder_image():
    if not os.path.exists(_PLACEHOLDER_PATH):
        return "", 404
    return send_from_directory(
        os.path.dirname(_PLACEHOLDER_PATH),
        os.path.basename(_PLACEHOLDER_PATH),
    )


@app.route("/api/placeholder", methods=["POST"])
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
def api_placeholder_delete():
    if os.path.exists(_PLACEHOLDER_PATH):
        os.remove(_PLACEHOLDER_PATH)
    return jsonify({"ok": True, "message": "Logo rimosso"})


# ── API: VPN (WireGuard split-tunnel) ────────────────────────────────────────

def _parse_subnets(value) -> list[str]:
    """Accept a list or a string with comma/newline separated subnets."""
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[,\n;]+", str(value or ""))
    return [s.strip() for s in items if s.strip()]


@app.route("/api/vpn", methods=["GET"])
def api_vpn_status():
    """Report the active/configured tunnel (WireGuard or OpenVPN)."""
    ovpn = vpn_openvpn.status()
    if ovpn["active"] or ovpn["configured"]:
        return jsonify({"protocol": "openvpn", **ovpn})
    wg = vpn.status()
    return jsonify({"protocol": "wireguard", **wg})


@app.route("/api/vpn", methods=["POST"])
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
def api_setup_mode():
    """Re-enter provisioning mode on next boot."""
    store.set_force_setup(True)
    _reboot_soon()
    return jsonify({"ok": True, "message": "Riavvio in modalità configurazione…"})


@app.route("/api/mode")
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
