"""OpenVPN client management with split-tunnel routing.

Mirror of vpn.py but for OpenVPN (.ovpn). Some camera installations expose
access only through an OpenVPN tunnel (the same the user connects to with
Tunnelblick on macOS). We bring that tunnel up on the Pi WITHOUT losing the
local network: only the camera subnets are routed through it (split-tunnel).

Privileged operations are delegated to the `cv-ovpn` helper via sudo, so this
module and Flask never run as root.

SECURITY: a .ovpn is a config that can run shell commands (up/down/plugin/
script-security ...). Since the setup portal is unauthenticated, we reject any
.ovpn containing script-executing directives before installing it.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess

NAME = "cvcam"  # systemd: openvpn-client@cvcam
HELPER = "/usr/local/sbin/cv-ovpn"

# Directives that can execute commands/scripts as root — never allowed from an
# uploaded .ovpn on the unauthenticated portal.
_DANGEROUS = {
    "up", "down", "route-up", "route-pre-down", "ipchange", "tls-verify",
    "auth-user-pass-verify", "client-connect", "client-disconnect",
    "learn-address", "plugin", "script-security", "up-restart",
    "tls-crypt-v2-verify", "auth-gen-token",
}
# Directives we strip because they break split-tunnel (full-tunnel routing).
_STRIP_PREFIXES = ("redirect-gateway", "redirect-private")


def _helper_available() -> bool:
    return shutil.which("sudo") is not None and os.path.exists(HELPER)


def _run_helper(action: str, stdin: str | None = None, timeout: int = 45):
    args = ["sudo", "-n", HELPER, action, NAME]
    try:
        p = subprocess.run(
            args, input=stdin, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def _subnet_routes(camera_subnets: list[str]) -> list[str]:
    """Convert CIDR subnets into OpenVPN `route NET MASK` directives.

    Reuses the same validation rules as WireGuard (rejects default routes).
    """
    from .vpn import validate_subnets
    routes = []
    for cidr in validate_subnets(camera_subnets):
        net = ipaddress.ip_network(cidr, strict=False)
        if net.version != 4:
            raise ValueError("OpenVPN split-tunnel supporta solo IPv4 qui")
        routes.append(f"route {net.network_address} {net.netmask}")
    return routes


def build_split_tunnel_ovpn(
    ovpn_text: str, camera_subnets: list[str], has_credentials: bool
) -> str:
    """Validate and rewrite a .ovpn for split-tunnel + non-interactive auth."""
    routes = _subnet_routes(camera_subnets)

    out_lines: list[str] = []
    needs_auth = False
    in_inline = False  # inside an <xxx>...</xxx> inline block (skip validation)

    for raw in ovpn_text.splitlines():
        line = raw.strip()
        # Track inline blocks like <ca> ... </ca>: keep verbatim.
        if re.match(r"^<\/?[a-zA-Z0-9_-]+>$", line):
            out_lines.append(raw)
            if line.startswith("</"):
                in_inline = False
            elif not line.startswith("</"):
                in_inline = True
            continue
        if in_inline:
            out_lines.append(raw)
            continue
        if not line or line.startswith("#") or line.startswith(";"):
            out_lines.append(raw)
            continue

        directive = line.split()[0].lower()

        if directive in _DANGEROUS:
            raise ValueError(
                f"Direttiva non consentita nel file .ovpn per sicurezza: {directive}"
            )
        if directive.startswith(_STRIP_PREFIXES):
            continue  # drop full-tunnel routing
        if directive == "route-nopull":
            continue  # we add our own
        if directive == "dev":
            continue  # force a deterministic device name (added below)
        if directive == "auth-user-pass":
            needs_auth = True
            # Replace with a file-based form (non-interactive).
            out_lines.append("auth-user-pass cvcam.auth")
            continue

        out_lines.append(raw)

    if needs_auth and not has_credentials:
        raise ValueError("Questa VPN richiede username e password")

    # Enforce split-tunnel: deterministic device, ignore pushed routes, then
    # add only the camera routes.
    out_lines.append("")
    out_lines.append("# --- split-tunnel (added by Camera Viewer) ---")
    out_lines.append("dev tuncam")
    out_lines.append("route-nopull")
    out_lines.extend(routes)
    out_lines.append("")
    return "\n".join(out_lines)


def apply_config(ovpn_text: str, camera_subnets: list[str],
                 username: str = "", password: str = "",
                 enable_on_boot: bool = True) -> tuple[bool, str]:
    if not _helper_available():
        return False, "Helper cv-ovpn non installato sul sistema"

    has_creds = bool(username and password)
    if any(c in username for c in ("\n", "\r")) or any(c in password for c in ("\n", "\r")):
        return False, "Credenziali non valide"

    try:
        conf = build_split_tunnel_ovpn(ovpn_text, camera_subnets, has_creds)
    except ValueError as e:
        return False, str(e)

    rc, out, err = _run_helper("install", stdin=conf)
    if rc != 0:
        return False, f"Installazione config fallita: {err or out}"

    if has_creds:
        rc, out, err = _run_helper("auth", stdin=f"{username}\n{password}\n")
        if rc != 0:
            return False, f"Salvataggio credenziali fallito: {err or out}"

    action = "enable" if enable_on_boot else "up"
    rc, out, err = _run_helper(action)
    if rc != 0:
        return False, f"Attivazione VPN fallita: {err or out}"
    return True, "VPN OpenVPN attivata"


def disable() -> tuple[bool, str]:
    if not _helper_available():
        return False, "Helper cv-ovpn non disponibile"
    rc, out, err = _run_helper("disable")
    return (rc == 0), (out or err or "").strip()


def remove() -> tuple[bool, str]:
    if not _helper_available():
        return False, "Helper cv-ovpn non disponibile"
    rc, out, err = _run_helper("remove")
    return (rc == 0), (out or err or "").strip()


def status() -> dict:
    """Status via the helper: active (systemd), tun IP, configured."""
    result = {"configured": False, "active": False, "tun_ip": None,
              "routes": None}
    if not _helper_available():
        return result
    rc, out, _ = _run_helper("status")
    if rc != 0:
        return result
    for line in out.splitlines():
        if line.startswith("active="):
            result["active"] = (line.split("=", 1)[1].strip() == "yes")
        elif line.startswith("configured="):
            result["configured"] = (line.split("=", 1)[1].strip() == "yes")
        elif line.startswith("tun_ip="):
            v = line.split("=", 1)[1].strip()
            result["tun_ip"] = v or None
        elif line.startswith("routes="):
            v = line.split("=", 1)[1].strip()
            result["routes"] = v or None
    return result
