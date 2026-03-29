#!/usr/bin/env python3
"""Print KEY's value from a WireGuard config (supports `Key=value` and `Key = value`)."""

import re
import sys


def get_value(key: str, path: str) -> str | None:
    line_re = re.compile(rf"^{re.escape(key)}\s*=\s*(.+)$", re.IGNORECASE)
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line and not line.startswith("#") and (m := line_re.match(line)):
                    return m.group(1).strip()
    except FileNotFoundError:
        print(f"Error: config file {path!r} not found", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)
    return None


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "usage: get-config-value.py <key> <config_file>\n"
            "example: get-config-value.py Address /path/to/wg.conf",
            file=sys.stderr,
        )
        sys.exit(1)
    value = get_value(sys.argv[1], sys.argv[2])
    if value is None:
        print(f"Key {sys.argv[1]!r} not found in config file", file=sys.stderr)
        sys.exit(1)
    print(value)


if __name__ == "__main__":
    main()
