#!/usr/bin/env python3
"""Strip wg-quick-specific keys from a WireGuard config, producing output suitable for `wg setconf`.

Equivalent to `wg-quick strip` but without the unnecessary root check.
"""

import sys

WG_QUICK_KEYS = frozenset(
    {"address", "dns", "mtu", "table", "preup", "postup", "predown", "postdown", "saveconfig"}
)


def strip_config(path: str) -> str:
    interface_section = False
    lines: list[str] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.lower().startswith("["):
                interface_section = stripped.lower() == "[interface]"

            if interface_section and "=" in stripped:
                key = stripped.split("=", 1)[0].strip().lower()
                if key in WG_QUICK_KEYS:
                    continue

            lines.append(line)

    return "".join(lines)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: strip-wg-config.py <config_file>", file=sys.stderr)
        sys.exit(1)

    try:
        print(strip_config(sys.argv[1]), end="")
    except FileNotFoundError:
        print(f"Error: config file {sys.argv[1]!r} not found", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
