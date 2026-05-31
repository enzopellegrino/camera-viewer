"""Network management via nmcli (NetworkManager).

Used by the provisioning web app to scan WiFi networks, report the current
connection, and connect the Pi to a chosen WiFi. Ethernet is handled by DHCP
automatically, so it only needs status reporting.

All functions degrade gracefully if nmcli is unavailable (e.g. when developing
on macOS) by returning empty/neutral results instead of raising.
"""
from __future__ import annotations

import shutil
import subprocess


def _has_nmcli() -> bool:
    return shutil.which("nmcli") is not None


def _run(args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def scan_wifi() -> list[dict]:
    """Return available WiFi networks: [{ssid, signal, security, in_use}]."""
    if not _has_nmcli():
        return []
    # Trigger a rescan (best-effort), then list
    _run(["nmcli", "dev", "wifi", "rescan"], timeout=10)
    rc, out, _ = _run(
        ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]
    )
    if rc != 0:
        return []

    networks: dict[str, dict] = {}
    for line in out.splitlines():
        # Fields are colon-separated; SSID may contain escaped colons (\:)
        parts = _split_nmcli(line)
        if len(parts) < 4:
            continue
        in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        if not ssid:
            continue
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        # Keep the strongest entry per SSID
        if ssid not in networks or sig > networks[ssid]["signal"]:
            networks[ssid] = {
                "ssid": ssid,
                "signal": sig,
                "security": security or "open",
                "in_use": in_use.strip() == "*",
            }
    return sorted(networks.values(), key=lambda n: n["signal"], reverse=True)


def current_status() -> dict:
    """Report the active connection: type, ssid, ip, online."""
    result = {"type": None, "ssid": None, "ip": None, "online": False}

    # Try nmcli first (NetworkManager-managed interfaces)
    if _has_nmcli():
        rc, out, _ = _run(
            ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION,DEVICE", "dev", "status"]
        )
        if rc == 0:
            for line in out.splitlines():
                parts = _split_nmcli(line)
                if len(parts) < 4:
                    continue
                dtype, state, conn, device = parts[:4]
                if state == "connected" and dtype in ("wifi", "ethernet"):
                    result["type"] = dtype
                    result["online"] = True
                    if dtype == "wifi":
                        result["ssid"] = conn
                    ip = _device_ip(device)
                    if ip:
                        result["ip"] = ip
                    if dtype == "ethernet":
                        result["ssid"] = None  # ethernet has no SSID
                        break  # prefer ethernet

    # Fallback: use `ip` command for interfaces managed by networkd
    # (e.g. on Ubuntu Server where NM reports them as "unmanaged")
    if not result["online"]:
        ip = _ip_fallback()
        if ip:
            result["online"] = True
            result["type"] = "ethernet"
            result["ip"] = ip

    return result


def _ip_fallback() -> str | None:
    """Get the first non-loopback IPv4 address via `ip addr` (networkd fallback)."""
    try:
        import re
        rc, out, _ = _run(["ip", "-4", "addr", "show"])
        if rc != 0:
            return None
        for line in out.splitlines():
            m = re.search(r"inet\s+([\d.]+)/\d+", line)
            if m and not m.group(1).startswith("127."):
                return m.group(1)
    except Exception:
        pass
    return None


def _device_ip(device: str) -> str | None:
    rc, out, _ = _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", device])
    if rc != 0:
        return None
    for line in out.splitlines():
        if line.startswith("IP4.ADDRESS"):
            # IP4.ADDRESS[1]:192.168.10.75/24
            val = line.split(":", 1)[-1].strip()
            return val.split("/")[0] if val else None
    return None


def connect_wifi(ssid: str, password: str) -> tuple[bool, str]:
    """Connect to a WiFi network. Returns (success, message)."""
    if not _has_nmcli():
        return False, "nmcli non disponibile su questo sistema"
    if not ssid:
        return False, "SSID mancante"
    # Validate SSID to avoid argument injection into nmcli (e.g. an SSID
    # starting with '-' would be parsed as an option).
    if ssid.startswith("-") or len(ssid.encode("utf-8")) > 32:
        return False, "SSID non valido"
    if any(c in ssid for c in ("\n", "\r", "\x00")) or any(
        c in password for c in ("\n", "\r", "\x00")
    ):
        return False, "Credenziali WiFi non valide"

    args = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    rc, out, err = _run(args, timeout=45)
    if rc == 0:
        return True, f"Connesso a {ssid}"
    return False, (err or out or "Connessione fallita").strip()


def _split_nmcli(line: str) -> list[str]:
    """Split an nmcli terse line on unescaped colons."""
    fields, buf, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            buf.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    fields.append("".join(buf))
    return fields
