"""Lightweight config.json reader/writer shared with the viewer app.

This module intentionally has NO Qt dependency so it can run inside the Flask
provisioning server. It reads and writes the same config.json consumed by the
PySide6 viewer on the Raspberry Pi.

Writes are atomic (tmp + replace) and read-modify-write sequences are
serialized with a module-level lock to avoid lost updates under Flask's
multi-threaded request handling.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

VALID_LAYOUTS = ["auto", "1x1", "1x2", "2x1", "2x2", "3x2", "2x3", "3x3", "4x4"]
VALID_ROLES   = ["admin", "operator"]

# Serializes read-modify-write sequences across concurrent requests.
_CONFIG_LOCK = threading.RLock()


def config_path() -> Path:
    """Shared config location on the Pi.

    Overridable via CAMERA_VIEWER_CONFIG for testing/dev.
    """
    override = os.environ.get("CAMERA_VIEWER_CONFIG")
    if override:
        p = Path(override)
    else:
        p = Path.home() / ".config" / "camera-viewer" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def force_setup_path() -> Path:
    """Flag file that forces provisioning mode on next boot."""
    return config_path().parent / "force-setup"


def is_force_setup() -> bool:
    return force_setup_path().exists()


def set_force_setup(on: bool) -> None:
    with _CONFIG_LOCK:
        p = force_setup_path()
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("1")
        else:
            p.unlink(missing_ok=True)


def has_cameras() -> bool:
    return len(load_config().get("cameras", [])) > 0


def should_provision() -> bool:
    """Decide whether the Pi should boot into provisioning mode."""
    return is_force_setup() or not has_cameras()


def _default_config() -> dict:
    first_screen_id = uuid.uuid4().hex[:8]
    return {
        "cameras": [],
        "screens": [{"id": first_screen_id, "name": "Default", "layout": "auto", "cameras": []}],
        "active_screen_id": first_screen_id,
        "settings": {
            "kiosk_mode": True,
            "reconnect_delay_ms": 5000,
            "render_fps": 30,
            "default_screen": 0,
        },
        "network": {"mode": "dhcp", "interface": "auto"},
        "site_name": "Camera Viewer",
        "users": [],   # populated by _normalize on first run
    }


def _normalize(cfg: dict) -> dict:
    """Ensure required keys exist with the right types (defensive)."""
    if not isinstance(cfg, dict):
        cfg = {}
    if not isinstance(cfg.get("cameras"), list):
        cfg["cameras"] = []
    if not isinstance(cfg.get("screens"), list) or not cfg["screens"]:
        sid = uuid.uuid4().hex[:8]
        cfg["screens"] = [{"id": sid, "name": "Default", "layout": "auto", "cameras": []}]
    for screen in cfg["screens"]:
        if not isinstance(screen, dict):
            continue
        if not isinstance(screen.get("cameras"), list):
            screen["cameras"] = []
        # Migrate: add id to existing screens
        if "id" not in screen:
            screen["id"] = uuid.uuid4().hex[:8]
    if not isinstance(cfg.get("settings"), dict):
        cfg["settings"] = {}
    if not isinstance(cfg.get("network"), dict):
        cfg["network"] = {"mode": "dhcp", "interface": "auto"}
    # Migrate: active_screen_id
    if not cfg.get("active_screen_id") and cfg["screens"]:
        cfg["active_screen_id"] = cfg["screens"][0]["id"]
    # Migrate: site_name
    cfg.setdefault("site_name", "Camera Viewer")
    # Migrate: rimuovi vecchia chiave vpn (sostituita da vpn_profiles)
    cfg.pop("vpn", None)
    # Migrate: users — create default admin on first run
    if not isinstance(cfg.get("users"), list) or not cfg["users"]:
        from werkzeug.security import generate_password_hash
        cfg["users"] = [{
            "id": uuid.uuid4().hex[:8],
            "username": "admin",
            "password_hash": generate_password_hash("admin"),
            "role": "admin",
            "must_change_password": True,
        }]
    # Migrate: add must_change_password to existing users that lack it
    for u in cfg.get("users", []):
        u.setdefault("must_change_password", False)
    return cfg


def load_config() -> dict:
    path = config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # Corrupted/unreadable: back it up and start from defaults so the
            # provisioning portal stays usable to recover the device.
            try:
                path.replace(path.with_suffix(".json.bad"))
            except OSError:
                pass
            cfg = _default_config()
            save_config(cfg)
    else:
        cfg = _default_config()
        save_config(cfg)

    return _normalize(cfg)


def save_config(cfg: dict) -> None:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(path)  # atomic write


def mutate(fn):
    """Run a read-modify-write under the lock. `fn(cfg)` mutates cfg in place
    and may return a value, which is returned to the caller."""
    with _CONFIG_LOCK:
        cfg = load_config()
        result = fn(cfg)
        save_config(cfg)
        return result


# ── Camera helpers ──────────────────────────────────────────────────────────

def list_cameras() -> list[dict]:
    return load_config()["cameras"]


def upsert_camera(camera: dict) -> dict:
    """Add a new camera or update an existing one (matched by id)."""
    cam_id = camera.get("id") or uuid.uuid4().hex[:8]
    entry = {
        "id": cam_id,
        "name": (camera.get("name") or "").strip(),
        "url": (camera.get("url") or "").strip(),
    }
    passphrase = (camera.get("passphrase") or "").strip()
    if passphrase:
        entry["passphrase"] = passphrase

    def _apply(cfg):
        cameras = cfg["cameras"]
        for i, c in enumerate(cameras):
            if c.get("id") == cam_id:
                cameras[i] = entry
                break
        else:
            cameras.append(entry)
            # auto-add new camera to the first screen so it shows on the monitor
            if cfg["screens"]:
                cfg["screens"][0].setdefault("cameras", []).append(cam_id)

    mutate(_apply)
    return entry


def delete_camera(cam_id: str) -> bool:
    def _apply(cfg):
        before = len(cfg["cameras"])
        cfg["cameras"] = [c for c in cfg["cameras"] if c.get("id") != cam_id]
        for screen in cfg["screens"]:
            screen["cameras"] = [cid for cid in screen.get("cameras", []) if cid != cam_id]
        return len(cfg["cameras"]) < before

    return mutate(_apply)


# ── Settings / layout helpers ────────────────────────────────────────────────

def get_settings() -> dict:
    return load_config().get("settings", {})


def update_settings(patch: dict) -> dict:
    def _apply(cfg):
        cfg.setdefault("settings", {}).update(patch)
        return cfg["settings"]

    return mutate(_apply)


def set_layout(layout: str) -> None:
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"Invalid layout: {layout}")

    def _apply(cfg):
        if cfg["screens"]:
            cfg["screens"][0]["layout"] = layout

    mutate(_apply)


def get_layout() -> str:
    cfg = load_config()
    if cfg["screens"]:
        return cfg["screens"][0].get("layout", "auto")
    return "auto"


# ── Screens (views) ──────────────────────────────────────────────────────────

def list_screens() -> list[dict]:
    return load_config().get("screens", [])


def get_active_screen_id() -> str:
    cfg = load_config()
    return cfg.get("active_screen_id", "")


def upsert_screen(screen: dict) -> dict:
    sid = screen.get("id") or uuid.uuid4().hex[:8]
    entry = {
        "id": sid,
        "name": (screen.get("name") or "").strip() or "Vista",
        "layout": screen.get("layout", "auto") if screen.get("layout") in VALID_LAYOUTS else "auto",
        "cameras": [c for c in screen.get("cameras", []) if isinstance(c, str)],
    }

    def _apply(cfg):
        screens = cfg.setdefault("screens", [])
        for i, s in enumerate(screens):
            if s.get("id") == sid:
                screens[i] = entry
                return
        screens.append(entry)
        if not cfg.get("active_screen_id"):
            cfg["active_screen_id"] = sid

    mutate(_apply)
    return entry


def delete_screen(screen_id: str) -> bool:
    def _apply(cfg):
        before = len(cfg.get("screens", []))
        cfg["screens"] = [s for s in cfg.get("screens", []) if s.get("id") != screen_id]
        # Reset active if deleted
        if cfg.get("active_screen_id") == screen_id:
            cfg["active_screen_id"] = cfg["screens"][0]["id"] if cfg["screens"] else ""
        return len(cfg["screens"]) < before

    return mutate(_apply)


def set_active_screen(screen_id: str) -> bool:
    def _apply(cfg):
        ids = [s["id"] for s in cfg.get("screens", [])]
        if screen_id not in ids:
            return False
        cfg["active_screen_id"] = screen_id
        return True

    return mutate(_apply)


# ── Site name ────────────────────────────────────────────────────────────────

def get_site_name() -> str:
    return load_config().get("site_name", "Camera Viewer")


def set_site_name(name: str) -> None:
    def _apply(cfg):
        cfg["site_name"] = (name or "Camera Viewer").strip()[:64]
    mutate(_apply)


# ── Users ────────────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    """Returns users without password_hash."""
    return [
        {"id": u["id"], "username": u["username"], "role": u["role"]}
        for u in load_config().get("users", [])
    ]


def get_user_by_username(username: str) -> dict | None:
    for u in load_config().get("users", []):
        if u.get("username") == username:
            return u
    return None


def get_user_by_id(user_id: str) -> dict | None:
    for u in load_config().get("users", []):
        if u.get("id") == user_id:
            return u
    return None


def create_user(username: str, password_hash: str, role: str) -> dict:
    uid = uuid.uuid4().hex[:8]
    entry = {"id": uid, "username": username.strip(), "password_hash": password_hash, "role": role}

    def _apply(cfg):
        cfg.setdefault("users", []).append(entry)

    mutate(_apply)
    return {"id": uid, "username": entry["username"], "role": role}


def update_user_password(user_id: str, password_hash: str) -> bool:
    def _apply(cfg):
        for u in cfg.get("users", []):
            if u["id"] == user_id:
                u["password_hash"] = password_hash
                u["must_change_password"] = False   # reset flag after change
                return True
        return False

    return mutate(_apply)


def delete_user(user_id: str) -> bool:
    """Refuses deletion if it's the last admin."""
    def _apply(cfg):
        users = cfg.get("users", [])
        target = next((u for u in users if u["id"] == user_id), None)
        if not target:
            return False
        if target["role"] == "admin":
            admins = [u for u in users if u["role"] == "admin"]
            if len(admins) <= 1:
                return False  # last admin — refuse
        cfg["users"] = [u for u in users if u["id"] != user_id]
        return True

    return mutate(_apply)


# ── VPN Profiles ──────────────────────────────────────────────────────────────

_VPN_SENSITIVE = ("conf_text", "password", "private_key", "preshared_key")


def list_vpn_profiles(mask_sensitive: bool = True) -> list[dict]:
    """Return profiles. With mask_sensitive=True passwords are hidden."""
    profiles = load_config().get("vpn_profiles", [])
    if not mask_sensitive:
        return profiles
    result = []
    for p in profiles:
        safe = {k: ("••••" if k in _VPN_SENSITIVE and v else v)
                for k, v in p.items()}
        result.append(safe)
    return result


def get_vpn_profile_raw(profile_id: str) -> dict | None:
    """Return full profile including sensitive fields."""
    for p in load_config().get("vpn_profiles", []):
        if p.get("id") == profile_id:
            return p
    return None


def upsert_vpn_profile(profile: dict) -> dict:
    """Create or update a VPN profile. Merges sensitive fields if masked."""
    pid = profile.get("id") or uuid.uuid4().hex[:8]

    def _apply(cfg):
        profiles = cfg.setdefault("vpn_profiles", [])
        existing = next((p for p in profiles if p.get("id") == pid), None)
        entry = {
            "id": pid,
            "name": (profile.get("name") or "Profilo VPN").strip(),
            "protocol": profile.get("protocol", "openvpn"),
            "camera_subnets": profile.get("camera_subnets", []),
            "auto_connect": bool(profile.get("auto_connect", True)),
            "active": existing.get("active", False) if existing else False,
        }
        # Preserve sensitive fields when placeholder "••••" is received
        for key in _VPN_SENSITIVE:
            new_val = profile.get(key, "")
            if new_val and new_val != "••••":
                entry[key] = new_val
            elif existing:
                entry[key] = existing.get(key, "")
            else:
                entry[key] = ""
        # Preserve username (not sensitive but may not change)
        entry["username"] = profile.get("username") or (existing or {}).get("username", "")

        if existing:
            profiles[profiles.index(existing)] = entry
        else:
            profiles.append(entry)
        return entry

    return mutate(_apply)


def delete_vpn_profile(profile_id: str) -> bool:
    def _apply(cfg):
        before = len(cfg.get("vpn_profiles", []))
        cfg["vpn_profiles"] = [p for p in cfg.get("vpn_profiles", [])
                               if p.get("id") != profile_id]
        return len(cfg["vpn_profiles"]) < before

    return mutate(_apply)


def set_vpn_profile_active(profile_id: str | None) -> None:
    """Mark one profile as active, deactivate all others."""
    def _apply(cfg):
        for p in cfg.get("vpn_profiles", []):
            p["active"] = (p.get("id") == profile_id)

    mutate(_apply)


def get_active_vpn_profile() -> dict | None:
    """Return the currently active profile (full data)."""
    for p in load_config().get("vpn_profiles", []):
        if p.get("active"):
            return p
    return None
