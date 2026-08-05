#!/usr/bin/env python3
"""Apply TRANSMISSION_* environment overrides to settings.json."""

import argparse
import json
import os
import re
import sys
from typing import Any

ENV_PREFIX = 'TRANSMISSION_'

# Container/orchestration vars that share the TRANSMISSION_ prefix but are not
# settings.json keys.
IGNORED_ENV_VARS = frozenset({
    'TRANSMISSION_HOME',
    'TRANSMISSION_WEB_HOME',
    'TRANSMISSION_WEB_UI',
})

# Setting names (kebab or snake) that need an explicit type when the key is
# not already present in settings.json and where the heuristic approach would get it wrong.
TYPE_MAP = {
    'umask': str,
}

_SENSITIVE_SETTINGS = frozenset({'rpc-password', 'rpc_password'})


def env_suffix_to_setting_key(suffix: str, settings: dict) -> str:
    """Pick the settings.json key for an env suffix like DOWNLOAD_DIR."""
    snake = suffix.lower()
    kebab = snake.replace('_', '-')
    if kebab in settings:
        return kebab
    if snake in settings:
        return snake
    return kebab


def normalize_umask(value: Any) -> str:
    """Normalize umask to a 3-digit octal string as used by Transmission 4.1+.

    Legacy values used a decimal integer (2 → 002, 18 → 022). Values that
    already look like octal strings (leading zero) are kept as-is and zero-padded
    to 3 digits when needed.
    """
    text = str(value).strip()
    if re.fullmatch(r'0[0-7]*', text):
        return text.zfill(3) if len(text) < 3 else text
    if re.fullmatch(r'[0-9]+', text):
        return format(int(text, 10), '03o')
    raise ValueError(f'Invalid umask value: {value!r}')


def type_map_entry(setting: str):
    """Return TYPE_MAP value for kebab or snake setting name, if any."""
    return TYPE_MAP.get(setting) or TYPE_MAP.get(setting.replace('_', '-'))


def coerce_value(setting: str, raw: str, settings: dict) -> Any:
    """Coerce an env string to the right type for a setting."""
    mapped = type_map_entry(setting)
    if mapped is not None:
        # umask: Transmission 4.1+ stores a 3-digit octal string ("002").
        # Older settings and env values used a decimal integer (2 / 18).
        # Normalize so both forms become the string Transmission expects.
        if setting.replace('_', '-') == 'umask':
            normalized = normalize_umask(raw)
            if normalized != str(raw).strip():
                print(f'Normalized umask from {raw!r} to {normalized!r}')
            return normalized
        return mapped(raw)

    if setting in settings and settings[setting] is not None:
        existing = settings[setting]
        existing_type = type(existing)
        if existing_type is bool:
            return raw.lower() == 'true'
        try:
            return existing_type(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f'Could not coerce {raw!r} to {existing_type} for {setting}'
            ) from None

    return heuristic_parse(raw)


def heuristic_parse(raw: str) -> Any:
    """Best-effort parse when we have no existing value or type map entry."""
    lowered = raw.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def iter_transmission_env_overrides() -> list[tuple[str, str]]:
    """Return (env_name, value) for TRANSMISSION_* overrides we should apply."""
    overrides = []
    for env_name, value in os.environ.items():
        if not env_name.startswith(ENV_PREFIX):
            continue
        if env_name in IGNORED_ENV_VARS:
            continue
        overrides.append((env_name, value))
    return sorted(overrides)


def apply_env_overrides(settings: dict) -> dict:
    """Apply TRANSMISSION_* env vars onto a settings dict; return the same dict."""
    for env_name, raw_value in iter_transmission_env_overrides():
        suffix = env_name[len(ENV_PREFIX):]
        setting = env_suffix_to_setting_key(suffix, settings)
        sensitive = setting in _SENSITIVE_SETTINGS
        log_value = '[REDACTED]' if sensitive else raw_value

        try:
            coerced = coerce_value(setting, raw_value, settings)
        except ValueError as exc:
            print(
                f'Could not coerce {env_name} value {log_value}: {exc}',
                file=sys.stderr,
            )
            raise

        print(
            f'Overriding {setting} because {env_name} is set to {log_value}'
        )
        settings[setting] = coerced
    return settings


def load_settings(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f'No existing settings.json at {path}; creating a new one from env')
        return {}
    except json.JSONDecodeError:
        print(
            f'Could not parse existing settings.json at {path}; '
            'creating a new one from env',
            file=sys.stderr,
        )
        return {}

    if not isinstance(data, dict):
        print(
            f'settings.json at {path} is not a JSON object; '
            'creating a new one from env',
            file=sys.stderr,
        )
        return {}

    print(f'Loaded existing settings.json from {path}')
    return data


def save_settings(path: str, settings: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(settings, handle, indent=4)
        handle.write('\n')


def update_settings_file(path: str) -> dict:
    settings = load_settings(path)
    apply_env_overrides(settings)
    save_settings(path, settings)
    return settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Update Transmission settings.json from TRANSMISSION_* env vars',
    )
    parser.add_argument(
        'settings_file',
        type=str,
        help='Path to Transmission settings.json',
    )
    args = parser.parse_args(argv)
    update_settings_file(args.settings_file)
    return 0


if __name__ == '__main__':
    sys.exit(main())
