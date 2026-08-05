#!/usr/bin/env python3
"""Unit tests for updateSettings.py."""

import importlib.util
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'update_settings', ROOT / 'updateSettings.py',
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


@contextmanager
def transmission_env(env_map):
    """Run with only the given TRANSMISSION_* vars set (others removed)."""
    cleaned = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith('TRANSMISSION_')
    }
    cleaned.update(env_map)
    with patch.dict(os.environ, cleaned, clear=True):
        yield


class NormalizeUmaskTests(unittest.TestCase):
    def test_legacy_decimal(self):
        self.assertEqual(mod.normalize_umask('2'), '002')
        self.assertEqual(mod.normalize_umask(18), '022')

    def test_octal_string(self):
        self.assertEqual(mod.normalize_umask('022'), '022')
        self.assertEqual(mod.normalize_umask('002'), '002')
        self.assertEqual(mod.normalize_umask('02'), '002')


class HeuristicParseTests(unittest.TestCase):
    def test_bool(self):
        self.assertIs(mod.heuristic_parse('true'), True)
        self.assertIs(mod.heuristic_parse('FALSE'), False)

    def test_int_and_float(self):
        self.assertEqual(mod.heuristic_parse('51413'), 51413)
        self.assertEqual(mod.heuristic_parse('2.5'), 2.5)

    def test_string(self):
        self.assertEqual(mod.heuristic_parse('/data/completed'), '/data/completed')


class KeyMappingTests(unittest.TestCase):
    def test_prefers_existing_kebab(self):
        settings = {'download-dir': '/old'}
        self.assertEqual(
            mod.env_suffix_to_setting_key('DOWNLOAD_DIR', settings),
            'download-dir',
        )

    def test_prefers_existing_snake(self):
        settings = {'download_dir': '/old'}
        self.assertEqual(
            mod.env_suffix_to_setting_key('DOWNLOAD_DIR', settings),
            'download_dir',
        )

    def test_defaults_to_kebab_when_missing(self):
        self.assertEqual(
            mod.env_suffix_to_setting_key('PEER_PORT', {}),
            'peer-port',
        )


class ApplyEnvOverridesTests(unittest.TestCase):
    def test_ignores_non_setting_env_vars(self):
        settings = {}
        with transmission_env({
            'TRANSMISSION_HOME': '/config/transmission-home',
            'TRANSMISSION_WEB_UI': 'shift',
            'TRANSMISSION_WEB_HOME': '/opt/ui',
            'TRANSMISSION_PEER_PORT': '12345',
        }):
            mod.apply_env_overrides(settings)

        self.assertEqual(settings, {'peer-port': 12345})

    def test_coerces_from_existing_type(self):
        settings = {'rpc-enabled': False, 'peer-port': 51413}
        with transmission_env({
            'TRANSMISSION_RPC_ENABLED': 'true',
            'TRANSMISSION_PEER_PORT': '9999',
        }):
            mod.apply_env_overrides(settings)

        self.assertIs(settings['rpc-enabled'], True)
        self.assertEqual(settings['peer-port'], 9999)

    def test_umask_type_map(self):
        settings = {}
        with transmission_env({'TRANSMISSION_UMASK': '2'}):
            with patch('builtins.print') as mocked_print:
                mod.apply_env_overrides(settings)
        self.assertEqual(settings['umask'], '002')
        printed = ' '.join(
            str(call.args[0]) for call in mocked_print.call_args_list
        )
        self.assertIn("Normalized umask from '2' to '002'", printed)

    def test_umask_already_octal_skips_normalize_log(self):
        settings = {}
        with transmission_env({'TRANSMISSION_UMASK': '002'}):
            with patch('builtins.print') as mocked_print:
                mod.apply_env_overrides(settings)
        self.assertEqual(settings['umask'], '002')
        printed = ' '.join(
            str(call.args[0]) for call in mocked_print.call_args_list
        )
        self.assertNotIn('Normalized umask', printed)

    def test_redacts_rpc_password_in_output(self):
        settings = {'rpc-password': 'old'}
        with transmission_env({'TRANSMISSION_RPC_PASSWORD': 'secret'}):
            with patch('builtins.print') as mocked_print:
                mod.apply_env_overrides(settings)

        self.assertEqual(settings['rpc-password'], 'secret')
        printed = ' '.join(
            str(call.args[0]) for call in mocked_print.call_args_list
        )
        self.assertIn('[REDACTED]', printed)
        self.assertNotIn('secret', printed)


class UpdateSettingsFileTests(unittest.TestCase):
    def test_creates_partial_file_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            with transmission_env({
                'TRANSMISSION_DOWNLOAD_DIR': '/data/completed',
                'TRANSMISSION_PEER_PORT': '51414',
                'TRANSMISSION_UMASK': '2',
            }):
                mod.update_settings_file(path)

            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)

            self.assertEqual(data['download-dir'], '/data/completed')
            self.assertEqual(data['peer-port'], 51414)
            self.assertEqual(data['umask'], '002')

    def test_overlays_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({
                    'download-dir': '/old',
                    'peer-port': 51413,
                    'dht-enabled': True,
                }, handle)

            with transmission_env({
                'TRANSMISSION_DOWNLOAD_DIR': '/data/completed',
            }):
                mod.update_settings_file(path)

            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)

            self.assertEqual(data['download-dir'], '/data/completed')
            self.assertEqual(data['peer-port'], 51413)
            self.assertIs(data['dht-enabled'], True)


if __name__ == '__main__':
    unittest.main()
