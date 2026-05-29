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
    return {
        "cameras": [],
        "screens": [{"name": "Default", "layout": "auto", "cameras": []}],
        "settings": {
            "kiosk_mode": True,
            "reconnect_delay_ms": 5000,
            "render_fps": 30,
            "default_screen": 0,
        },
        "network": {"mode": "dhcp", "interface": "auto"},
    }


def _normalize(cfg: dict) -> dict:
    """Ensure required keys exist with the right types (defensive)."""
    if not isinstance(cfg, dict):
        cfg = {}
    if not isinstance(cfg.get("cameras"), list):
        cfg["cameras"] = []
    if not isinstance(cfg.get("screens"), list) or not cfg["screens"]:
        cfg["screens"] = [{"name": "Default", "layout": "auto", "cameras": []}]
    for screen in cfg["screens"]:
        if not isinstance(screen, dict):
            continue
        if not isinstance(screen.get("cameras"), list):
            screen["cameras"] = []
    if not isinstance(cfg.get("settings"), dict):
        cfg["settings"] = {}
    if not isinstance(cfg.get("network"), dict):
        cfg["network"] = {"mode": "dhcp", "interface": "auto"}
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
