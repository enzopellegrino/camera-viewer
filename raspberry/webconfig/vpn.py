"""WireGuard VPN management with split-tunnel routing.

Some cameras are only reachable through a VPN. This module configures a
WireGuard tunnel WITHOUT losing the current network: only the camera subnets
are routed through the tunnel (split-tunnel via AllowedIPs), everything else
stays on the normal connection.

Privileged operations (writing /etc/wireguard, wg-quick) are delegated to the
`cv-vpn` helper run through sudo, so this module — and Flask — never run as root.

Config can be provided two ways:
  - uploading a WireGuard .conf file (we override AllowedIPs for split-tunnel)
  - entering the fields manually

SECURITY: every value written into the generated .conf is strictly validated.
Newlines/control chars are rejected so an attacker on the (unauthenticated)
setup portal cannot inject extra directives such as `PostUp = <cmd>`, which
wg-quick would otherwise execute as root.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess

IFACE = "wgcam"  # fixed interface name for the camera VPN
HELPER = "/usr/local/sbin/cv-vpn"

# A WireGuard key is 32 bytes base64 -> 44 chars ending with '='.
_RE_WG_KEY = re.compile(r"^[A-Za-z0-9+/]{43}=$")
# host:port  (IPv4 or hostname; no spaces/newlines)
_RE_ENDPOINT = re.compile(r"^[A-Za-z0-9.\-]{1,253}:[0-9]{1,5}$")


# ── Helper invocation ─────────────────────────────────────────────────────────

def _helper_available() -> bool:
    return shutil.which("sudo") is not None and os.path.exists(HELPER)


def _run_helper(action: str, stdin: str | None = None, timeout: int = 30):
    args = ["sudo", "-n", HELPER, action, IFACE]
    try:
        p = subprocess.run(
            args, input=stdin, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


# ── Field validation ──────────────────────────────────────────────────────────

def _no_ctrl(name: str, value: str) -> str:
    """Reject newlines/control chars to prevent .conf directive injection."""
    if any(c in value for c in ("\n", "\r", "\x00")):
        raise ValueError(f"Valore non valido per {name}")
    return value.strip()


def _valid_key(name: str, value: str) -> str:
    v = _no_ctrl(name, value)
    if not _RE_WG_KEY.match(v):
        raise ValueError(f"{name} non è una chiave WireGuard valida")
    return v


def _valid_address(value: str) -> str:
    v = _no_ctrl("Address", value)
    parts = [p.strip() for p in v.split(",") if p.strip()]
    if not parts:
        raise ValueError("Address mancante")
    for p in parts:
        ipaddress.ip_interface(p)  # raises ValueError if malformed
    return ", ".join(parts)


def _valid_endpoint(value: str) -> str:
    v = _no_ctrl("Endpoint", value)
    if not _RE_ENDPOINT.match(v):
        raise ValueError("Endpoint non valido (atteso host:porta)")
    port = int(v.rsplit(":", 1)[1])
    if not (1 <= port <= 65535):
        raise ValueError("Porta endpoint fuori range")
    return v


# ── Config parsing & building ─────────────────────────────────────────────────

def parse_wg_conf(text: str) -> dict:
    """Parse a WireGuard .conf into a dict of Interface + Peer fields.

    Only the keys we know about are kept; unknown/dangerous directives
    (PostUp, PreUp, Table, ...) are ignored and never propagated.
    """
    section = None
    data: dict = {"interface": {}, "peer": {}}
    allowed = {"privatekey", "address", "publickey", "presharedkey", "endpoint"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low == "[interface]":
            section = "interface"
            continue
        if low == "[peer]":
            section = "peer"
            continue
        if "=" not in line or section is None:
            continue
        key, val = line.split("=", 1)
        key = key.strip().lower()
        if key in allowed:
            data[section][key] = val.strip()
    return data


def validate_subnets(subnets: list[str]) -> list[str]:
    """Validate camera subnets/IPs (IPv4/IPv6 CIDR or single host).

    Default routes (prefix length 0, e.g. 0.0.0.0/0 or ::/0) are REJECTED:
    they would turn the split-tunnel into a full-tunnel and could drop the
    local network / SSH.
    """
    out = []
    for s in subnets:
        s = s.strip()
        if not s:
            continue
        if "/" not in s:
            # single host
            ver = ipaddress.ip_address(s).version
            s = s + ("/32" if ver == 4 else "/128")
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            raise ValueError(f"Subnet/IP non valido: {s}")
        if net.prefixlen == 0:
            raise ValueError(
                f"Rotta di default non ammessa (lo split-tunnel la vieta): {s}"
            )
        out.append(str(net))
    if not out:
        raise ValueError("Indica almeno una subnet o IP delle camere remote")
    return out


def build_split_tunnel_conf(fields: dict, camera_subnets: list[str]) -> str:
    """Build a WireGuard .conf forcing split-tunnel routing.

    `fields` carries: private_key, address, (optional dns),
    peer_public_key, (optional preshared_key), endpoint.
    `camera_subnets` becomes AllowedIPs — ONLY these go through the tunnel.
    DNS is intentionally omitted to avoid changing the global resolver.

    All values are strictly validated to prevent directive injection.
    """
    iface = fields.get("interface", {}) if "interface" in fields else fields
    peer = fields.get("peer", {}) if "peer" in fields else fields

    raw_private = (iface.get("privatekey") or fields.get("private_key") or "").strip()
    raw_address = (iface.get("address") or fields.get("address") or "").strip()
    raw_public = (peer.get("publickey") or fields.get("peer_public_key") or "").strip()
    raw_psk = (peer.get("presharedkey") or fields.get("preshared_key") or "").strip()
    raw_endpoint = (peer.get("endpoint") or fields.get("endpoint") or "").strip()

    missing = [n for n, v in [
        ("PrivateKey", raw_private), ("Address", raw_address),
        ("Peer PublicKey", raw_public), ("Endpoint", raw_endpoint),
    ] if not v]
    if missing:
        raise ValueError("Campi VPN mancanti: " + ", ".join(missing))

    # Validate every field (raises ValueError on anything suspicious).
    private_key = _valid_key("PrivateKey", raw_private)
    public_key = _valid_key("Peer PublicKey", raw_public)
    address = _valid_address(raw_address)
    endpoint = _valid_endpoint(raw_endpoint)
    preshared = _valid_key("PresharedKey", raw_psk) if raw_psk else ""

    allowed = ", ".join(validate_subnets(camera_subnets))

    lines = ["[Interface]", f"PrivateKey = {private_key}", f"Address = {address}", ""]
    lines += ["[Peer]", f"PublicKey = {public_key}"]
    if preshared:
        lines.append(f"PresharedKey = {preshared}")
    lines += [
        f"Endpoint = {endpoint}",
        f"AllowedIPs = {allowed}",
        "PersistentKeepalive = 25",
        "",
    ]
    return "\n".join(lines)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def apply_config(conf_text: str, enable_on_boot: bool = True) -> tuple[bool, str]:
    """Install the .conf and bring the tunnel up."""
    if not _helper_available():
        return False, "Helper cv-vpn non installato sul sistema"
    rc, out, err = _run_helper("install", stdin=conf_text)
    if rc != 0:
        return False, f"Installazione config fallita: {err or out}"
    action = "enable" if enable_on_boot else "up"
    rc, out, err = _run_helper(action)
    if rc != 0:
        return False, f"Attivazione VPN fallita: {err or out}"
    return True, "VPN attivata"


def disable() -> tuple[bool, str]:
    if not _helper_available():
        return False, "Helper cv-vpn non disponibile"
    rc, out, err = _run_helper("disable")
    return (rc == 0), (out or err or "").strip()


def remove() -> tuple[bool, str]:
    if not _helper_available():
        return False, "Helper cv-vpn non disponibile"
    rc, out, err = _run_helper("remove")
    return (rc == 0), (out or err or "").strip()


def status() -> dict:
    """Return tunnel status parsed from `wg show dump`.

    State is derived via the privileged helper (the web app runs as a normal
    user and cannot read /etc/wireguard, which is 0700 root).
    """
    result = {"configured": False, "active": False, "endpoint": None,
              "allowed_ips": None, "last_handshake": 0, "rx": 0, "tx": 0}
    if not _helper_available():
        return result

    rc, out, _ = _run_helper("status")
    dump = out.strip() if rc == 0 else ""

    if dump:
        # Interface is up. First line = interface; peer lines have >= 8 fields.
        result["active"] = True
        result["configured"] = True
        for line in dump.splitlines():
            peer = line.split("\t")
            if len(peer) >= 8:  # this is a peer row
                result["endpoint"] = peer[2] if peer[2] != "(none)" else None
                result["allowed_ips"] = peer[3] if peer[3] != "(none)" else None
                try:
                    result["last_handshake"] = int(peer[4])
                    result["rx"] = int(peer[5])
                    result["tx"] = int(peer[6])
                except (ValueError, IndexError):
                    pass
                break
    else:
        # Tunnel down — check if a config is stored
        rc2, out2, _ = _run_helper("exists")
        result["configured"] = (out2.strip() == "yes")
    return result
