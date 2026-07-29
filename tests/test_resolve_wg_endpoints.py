#!/usr/bin/env python3
"""Unit tests for resolve-wg-endpoints.py (no dig / network required)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resolve_wg_endpoints", ROOT / "resolve-wg-endpoints.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ParseEndpointTests(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(mod._parse_endpoint("1.2.3.4:51820"), ("1.2.3.4", "51820"))

    def test_hostname(self):
        self.assertEqual(
            mod._parse_endpoint("vpn.example.com:51820"),
            ("vpn.example.com", "51820"),
        )

    def test_ipv6(self):
        self.assertEqual(
            mod._parse_endpoint("[2001:db8::1]:51820"),
            ("2001:db8::1", "51820"),
        )

    def test_trailing_comment(self):
        self.assertEqual(
            mod._parse_endpoint("vpn.example.com:51820 # primary"),
            ("vpn.example.com", "51820"),
        )

    def test_invalid(self):
        with self.assertRaises(ValueError):
            mod._parse_endpoint("no-port")


class FormatEndpointTests(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(mod._format_endpoint("1.2.3.4", "51820"), "1.2.3.4:51820")

    def test_ipv6_compressed(self):
        self.assertEqual(
            mod._format_endpoint("2001:0db8:0000::1", "51820"),
            "[2001:db8::1]:51820",
        )


class ValidateResolverTests(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(mod._validate_resolver("1.1.1.1"), "1.1.1.1")

    def test_ipv6(self):
        self.assertEqual(mod._validate_resolver("2001:db8::1"), "2001:db8::1")

    def test_rejects_hostname(self):
        with self.assertRaises(ValueError):
            mod._validate_resolver("dns.example.com")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            mod._validate_resolver("   ")


class TransformTests(unittest.TestCase):
    def test_skips_ip_literal_and_strips_comment(self):
        conf = (
            "[Interface]\n"
            "Address = 10.0.0.2/32\n"
            "[Peer]\n"
            "Endpoint = 9.9.9.9:51820 # keep\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.conf"
            dst = Path(tmp) / "out.conf"
            src.write_text(conf, encoding="utf-8")
            mod.transform(src, dst, "1.1.1.1")
            out = dst.read_text(encoding="utf-8")
            self.assertIn("Endpoint = 9.9.9.9:51820\n", out)
            self.assertNotIn("# keep", out)

    @patch.object(mod, "_dig_ip")
    def test_resolves_hostname_preferring_a(self, dig_ip):
        def side_effect(hostname, record, resolver):
            if record == "A":
                return "203.0.113.10"
            return "2001:db8::10"

        dig_ip.side_effect = side_effect
        conf = "[Peer]\nEndpoint = vpn.example.com:51820\n"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.conf"
            dst = Path(tmp) / "out.conf"
            src.write_text(conf, encoding="utf-8")
            mod.transform(src, dst, "1.1.1.1")
            self.assertIn("Endpoint = 203.0.113.10:51820\n", dst.read_text(encoding="utf-8"))
        dig_ip.assert_called()

    @patch.object(mod, "_dig_ip")
    def test_falls_back_to_aaaa(self, dig_ip):
        def side_effect(hostname, record, resolver):
            if record == "AAAA":
                return "2001:db8::99"
            return None

        dig_ip.side_effect = side_effect
        conf = "[Peer]\nEndpoint = ipv6-only.example:51820\n"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.conf"
            dst = Path(tmp) / "out.conf"
            src.write_text(conf, encoding="utf-8")
            mod.transform(src, dst, "1.1.1.1")
            self.assertIn(
                "Endpoint = [2001:db8::99]:51820\n",
                dst.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
