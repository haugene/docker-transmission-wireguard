#!/usr/bin/env python3

import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

__doc__ = """\
Resolve WireGuard Endpoint hostnames to IPs before netns setup.
Uses dig @WG_BOOTSTRAP_DNS (default 1.1.1.1) so bootstrap DNS does not use
Docker's 127.0.0.11. Skips lookup when Endpoint already uses an IP literal.
Prefers A (IPv4) over AAAA when both exist.
"""

ENDPOINT = re.compile(r"^(Endpoint)\s*=\s*(.+)$", re.IGNORECASE)
# `[IPv6]:port` or `host:port` (host must not contain ':' unless bracketed IPv6)
_SPLIT = re.compile(
    r"^(?P<v6>\[[^\]]+\]:\d+)|(?P<v4host>[^:]+):(?P<port>\d+)$"
)


def _strip_inline_comment(value: str) -> str:
    """Drop trailing `# comment` from an Endpoint value (host:port never contains '#')."""
    return value.split("#", 1)[0].strip()


def _validate_resolver(resolver: str) -> str:
    """Require an IP literal so dig @resolver does not itself need DNS."""
    try:
        return str(ipaddress.ip_address(resolver.strip()))
    except ValueError as e:
        raise ValueError(
            f"WG_BOOTSTRAP_DNS must be an IP address, got {resolver!r}"
        ) from e


def _parse_endpoint(raw: str) -> tuple[str, str]:
    s = _strip_inline_comment(raw)
    m = _SPLIT.match(s)
    if not m:
        raise ValueError(f"invalid Endpoint: {raw!r}")
    if m["v6"]:
        inner, _, port = s[1:].partition("]:")
        return inner, port
    return m["v4host"], m["port"]


def _format_endpoint(ip: str, port: str) -> str:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        return f"[{addr.compressed}]:{port}"
    return f"{addr.compressed}:{port}"


def _dig_ip(hostname: str, record: str, resolver: str) -> str | None:
    try:
        r = subprocess.run(
            ["dig", "+short", "+time=5", f"@{resolver}", hostname, record],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "dig not found; install dnsutils (or equivalent) in the image"
        ) from e
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.strip().split()
        if not parts or parts[0].startswith(";"):
            continue
        try:
            ipaddress.ip_address(parts[0])
            return parts[0]
        except ValueError:
            # CNAME or other non-IP line from dig +short
            continue
    return None


def _resolve(hostname: str, resolver: str) -> str:
    # Prefer IPv4; fall back to AAAA for IPv6-only hostnames.
    for record in ("A", "AAAA"):
        if ip := _dig_ip(hostname, record, resolver):
            return ip
    msg = f"could not resolve {hostname!r} via @{resolver}"
    raise LookupError(msg)


def _maybe_resolve(value: str, resolver: str) -> tuple[str, bool]:
    host, port = _parse_endpoint(value)
    try:
        ipaddress.ip_address(host)
        return _format_endpoint(host, port), False
    except ValueError:
        pass
    return _format_endpoint(_resolve(host, resolver), port), True


def transform(path_in: Path, path_out: Path, resolver: str) -> None:
    text = path_in.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        m = ENDPOINT.match(stripped)
        if not m:
            out.append(line)
            continue
        key, val = m[1], _strip_inline_comment(m[2])
        try:
            new_val, changed = _maybe_resolve(val, resolver)
        except ValueError as e:
            raise ValueError(f"Endpoint line: {e}") from e
        if changed:
            print(
                f"Resolved Endpoint hostname to {new_val!r} (via @{resolver})",
                file=sys.stderr,
            )
        out.append(f"{key} = {new_val}\n")

    path_out.write_text("".join(out), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: resolve-wg-endpoints.py <config_in> <config_out>\n"
            "Resolver: WG_BOOTSTRAP_DNS (default 1.1.1.1, must be an IP)",
            file=sys.stderr,
        )
        return 1
    try:
        resolver = _validate_resolver(os.environ.get("WG_BOOTSTRAP_DNS") or "1.1.1.1")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.is_file():
        print(f"Error: config file {sys.argv[1]!r} not found", file=sys.stderr)
        return 1
    try:
        transform(src, dst, resolver)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except LookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
