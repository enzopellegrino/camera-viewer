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
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqUhfxNDsClE2H7+oYL3X
tbgFE82kbaxHFuz2xH6eaYBrJJDF3hE7zkgVF8Pnf9PcuFmqDbl2fYoAmgfxuhH9
a97wnYXLFsf7UR4vg6mcFIlmCH3lgJNjYHcsnAg0oUZ67Dbr28RcPB8i6tcNDZJR
A/Vcu5xrZByWrXSsEeGmiv4ojDXqZXI2BM96O2qZ9wmEwgHxKPtfWZJWsQBGFZlA
Ok7mTrk6ej3z4aWgL5cwE+OPojWbjiqW5AZASJH8KbFvf3YXINPdb6rQcwzmv9XJ
/4MbjEFzMRXmztuNHIw7MGqp/VZxBH2u32c6QYVxAc5Z1QJ2yz9lSIHbQi/apSfm
ywIDAQAB
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
