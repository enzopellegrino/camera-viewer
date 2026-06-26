"""
Offline RSA-2048 license manager.

Trial:    7 days from first launch, stored in Application Support.
Lifetime: machine-bound RSA-signed key.

Key format:  <base64url_payload>.<base64url_signature>
Payload JSON: {"email": "...", "machine_id": "...", "type": "lifetime", "issued": "YYYY-MM-DD"}
"""

import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import date
from enum import Enum, auto
from pathlib import Path


def _app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "Camera Viewer"
    else:
        base = Path.home() / "Library" / "Application Support" / "Camera Viewer"
    base.mkdir(parents=True, exist_ok=True)
    return base

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


TRIAL_DAYS = 7

_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAl1DE9SUiwT3lXHrRerjw
COi9zOlizysm99Irv0+LJf5sW5GVqfo9MKUGuk/R7qvE8uUKEvtjycjfWQU631BK
SH3mI4i9VjZKnYMzfO/igWjPjfjfZgj3JTWTAufjPKYCJMN6Deb0WaQUnsZTUySE
1sUG6QvjPVPAjk0CE1LUTFtkNZdcJ1zWeV56fNnFnWrqWNJsU/G8dPpSsMsH14BU
nuXy1d/TmEzPddAWt/+o2W9p8OX+S5i+ZlnkREOd/xWayX2y1w7UQ0u5wvtSkKNr
sWiH4fdu6FnGjM6gIkTJMOHCSbkfTKtLFtaO3R8RKC9ByhNTt5xUSlDWeX8wBgj+
vwIDAQAB
-----END PUBLIC KEY-----"""

_HMAC_SALT = b"cv-trial-2025-n1computer"


class LicenseStatus(Enum):
    TRIAL_ACTIVE = auto()
    TRIAL_EXPIRED = auto()
    LICENSED = auto()



# ── Trial storage ─────────────────────────────────────────────────────────────

def _trial_path() -> Path:
    return _app_data_dir() / "trial.dat"


def _trial_checksum(data: dict) -> str:
    payload = json.dumps({k: data[k] for k in ("started", "last_seen")}, sort_keys=True)
    return hmac.new(_HMAC_SALT, payload.encode(), hashlib.sha256).hexdigest()


def _load_trial() -> dict | None:
    p = _trial_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if data.get("checksum") != _trial_checksum(data):
            return None  # tampered
        return data
    except Exception:
        return None


def _save_trial(data: dict):
    data["checksum"] = _trial_checksum(data)
    _trial_path().parent.mkdir(parents=True, exist_ok=True)
    _trial_path().write_text(json.dumps(data))


def _init_trial() -> dict:
    today = date.today().isoformat()
    data = {"started": today, "last_seen": today}
    _save_trial(data)
    return data


def trial_days_remaining() -> int:
    trial = _load_trial()
    if trial is None:
        trial = _init_trial()
    today = date.today()
    started = date.fromisoformat(trial["started"])
    elapsed = (today - started).days
    return max(0, TRIAL_DAYS - elapsed)


def _update_trial_last_seen():
    trial = _load_trial()
    if trial is None:
        _init_trial()
        return
    today = date.today().isoformat()
    last_seen = trial.get("last_seen", today)
    # detect clock rollback — treat as tampering: set last_seen to today if it moved forward
    if today >= last_seen:
        trial["last_seen"] = today
        _save_trial(trial)


# ── License key ───────────────────────────────────────────────────────────────

def _b64_decode(s: str) -> bytes:
    padding_needed = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * padding_needed)


def _verify_key(key: str) -> dict | None:
    """Return payload dict if signature is valid, else None."""
    try:
        parts = key.strip().split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig_b64 = parts
        payload_bytes = _b64_decode(payload_b64)
        sig_bytes = _b64_decode(sig_b64)
        public_key = serialization.load_pem_public_key(_PUBLIC_KEY_PEM)
        public_key.verify(sig_bytes, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
        return json.loads(payload_bytes)
    except Exception:
        return None


def _license_path() -> Path:
    return _app_data_dir() / "license.dat"


def load_license() -> dict | None:
    p = _license_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        payload = _verify_key(data.get("key", ""))
        if payload and payload.get("type") == "lifetime":
            return payload
        return None
    except Exception:
        return None


def activate_license(key: str) -> tuple[bool, str]:
    """Returns (success, message)."""
    payload = _verify_key(key)
    if payload is None:
        return False, "Chiave non valida."
    if payload.get("type") != "lifetime":
        return False, "Tipo di licenza non riconosciuto."
    _license_path().parent.mkdir(parents=True, exist_ok=True)
    _license_path().write_text(json.dumps({"key": key}))
    return True, "Licenza attivata. Grazie!"


# ── Main check ────────────────────────────────────────────────────────────────

def check_license() -> LicenseStatus:
    if load_license():
        return LicenseStatus.LICENSED
    _update_trial_last_seen()
    if trial_days_remaining() > 0:
        return LicenseStatus.TRIAL_ACTIVE
    return LicenseStatus.TRIAL_EXPIRED


# ── Kiosk / NUC license (stored in config.json) ───────────────────────────────

def _config_license_key() -> str:
    """Read license_key field from the shared config.json."""
    import json
    from pathlib import Path
    cfg_path = Path.home() / ".config" / "camera-viewer" / "config.json"
    env_path = __import__("os").environ.get("CAMERA_VIEWER_CONFIG")
    if env_path:
        cfg_path = Path(env_path)
    try:
        return json.loads(cfg_path.read_text()).get("license_key", "")
    except Exception:
        return ""


def get_kiosk_license_info() -> dict:
    """Returns license status for the kiosk/NUC system.

    Reads the key from config.json (shared with the Flask portal).
    Return shape:
        {"valid": bool, "type": "lifetime"|"timed"|None,
         "expires": "YYYY-MM-DD"|None, "site": str}
    """
    key = _config_license_key()
    if not key:
        return {"valid": False, "type": None, "expires": None, "site": ""}
    payload = _verify_key(key)
    if not payload:
        return {"valid": False, "type": None, "expires": None, "site": ""}
    ltype = payload.get("type", "")
    site  = payload.get("site", payload.get("email", ""))
    if ltype == "lifetime":
        return {"valid": True, "type": "lifetime", "expires": None, "site": site}
    if ltype == "timed":
        expires_str = payload.get("expires", "2000-01-01")
        try:
            valid = date.today() <= date.fromisoformat(expires_str)
        except ValueError:
            valid = False
        return {"valid": valid, "type": "timed", "expires": expires_str, "site": site}
    return {"valid": False, "type": ltype, "expires": None, "site": site}


def check_kiosk_license() -> LicenseStatus:
    """LicenseStatus for the kiosk system based on config.json key."""
    info = get_kiosk_license_info()
    if info["valid"]:
        return LicenseStatus.LICENSED
    return LicenseStatus.TRIAL_EXPIRED
