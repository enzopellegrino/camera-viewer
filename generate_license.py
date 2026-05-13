"""
Developer tool — generate a lifetime license key.

Usage:
    .venv/bin/python generate_license.py <email>

The private key (license_private.pem) must be in the current directory.
"""

import base64
import json
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def generate(email: str) -> str:
    private_key = serialization.load_pem_private_key(
        Path("license_private.pem").read_bytes(), password=None
    )
    payload = json.dumps(
        {"email": email, "type": "lifetime", "issued": date.today().isoformat()},
        separators=(",", ":"),
    ).encode()
    signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    p64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    s64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{p64}.{s64}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    key = generate(sys.argv[1])
    print(f"\nLicense key for {sys.argv[1]}:\n")
    print(key)
    print()
