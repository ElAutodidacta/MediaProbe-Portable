from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mediaprobe.browserui import AppState
from mediaprobe.models import BenchmarkResult, DeviceInfo, ProbeReport, utc_now
from mediaprobe.product import validate_product, compare_product
from mediaprobe.online import lookup_product, rank_candidate, public_https, _DuckParser, reference_speeds
from mediaprobe.reports import report_text, report_html


class ProductTests(unittest.TestCase):
    def test_invalid_nonfinite_and_negative_claims_rejected(self):
        for value in ("NaN", "inf", -1, 0):
            with self.assertRaises(ValueError): validate_product({"read_mbps": value})
        self.assertEqual(validate_product({"capacity_gb": "128,5"})["capacity_gb"], 128.5)

    def test_maximum_claim_is_not_a_minimum_failure(self):
        p = validate_product({"read_mbps": 200, "write_mbps": 100, "capacity_gb": 128})
        rows = compare_product(p, DeviceInfo(mount="test", physical_bytes=128_000_000_000), BenchmarkResult(sequential_read_mbps=100))
        self.assertEqual(rows[1]["percent"], 50)
        self.assertIn("no es un mínimo", rows[1]["note"])
        self.assertIn("falta verificar", rows[0]["note"])

    def test_official_domain_does_not_authenticate_wrong_model(self):
        p = validate_product({"brand": "Samsung", "model": "EVO Plus", "capacity_gb": 128})
        device = DeviceInfo(mount="test", model="Generic USB Disk")
        r = rank_candidate({"title": "Samsung Refrigerator", "snippet": "", "url": "https://www.samsung.com/refrigerator"}, p, device)
        self.assertFalse(r["relevant"])
        self.assertEqual(r["match"], "Coincidencia débil")
        fake = rank_candidate({"title": "Samsung EVO Plus 128 GB", "url": "https://samsung.com.example.org/product", "snippet": ""}, p, device)
        self.assertFalse(fake["official"])

    def test_private_identifiers_are_not_search_terms(self):
        device = DeviceInfo(mount="test", model="Kingston DataTraveler SECRET_SERIAL", serial="SECRET_SERIAL", cid="PRIVATE_CID")
        with patch("mediaprobe.online.search", return_value=([{"title": "Kingston DataTraveler 128 GB", "url": "https://www.kingston.com/usb", "snippet": ""}], "test")) as search:
            r = lookup_product(validate_product({"brand": "Kingston", "capacity_gb": 128}), device)
        self.assertEqual(r["connectivity"], "online")
        for call in search.call_args_list:
            self.assertNotIn("SECRET_SERIAL", call.args[0])
            self.assertNotIn("PRIVATE_CID", call.args[0])

    def test_offline_is_an_explicit_unavailable_result(self):
        with patch("mediaprobe.online.search", side_effect=OSError("offline")):
            r = lookup_product(validate_product({"brand": "Kingston", "model": "DataTraveler"}), DeviceInfo(mount="test"))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["candidates"], [])

    def test_explicit_official_speed_reference_and_discrepancy(self):
        self.assertEqual(reference_speeds("read/write speeds up to 1,000/900MB/s"), {"read_mbps": 1000, "write_mbps": 900})
        self.assertEqual(reference_speeds("256GB USB 3.2 Gen 2"), {})
        row = {"title": "Kingston DataTraveler Max", "url": "https://www.kingston.com/test", "snippet": "read/write speeds up to 1,000/900MB/s"}
        result = rank_candidate(row, validate_product({"brand": "Kingston", "model": "DataTraveler Max", "read_mbps": 2000}), DeviceInfo(mount="test"))
        self.assertEqual(len(result["spec_disagreements"]), 1)
        row["url"] = "https://shop.example.org/product"
        self.assertEqual(rank_candidate(row, {}, DeviceInfo(mount="test"))["reference_speeds"], {})

    def test_private_source_rejected_and_search_result_parsing(self):
        with self.assertRaises(ValueError): public_https("http://127.0.0.1/admin")
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError): public_https("https://example.org/test")
        parser = _DuckParser()
        parser.feed('<a class="result-link" href="https://www.kingston.com/test">Kingston <b>Max</b></a><td class="result-snippet">256 GB USB</td>')
        self.assertEqual(parser.rows[0]["title"], "Kingston Max")
        self.assertEqual(parser.rows[0]["snippet"], "256 GB USB")

    def test_product_persistence_and_export_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, serial="fixture", total_bytes=128_000_000_000)
            product = validate_product({"brand": "<script>test</script>", "model": "Model 1", "auto_lookup": False})
            with patch("mediaprobe.browserui.local_history_path", return_value=Path(tmp)/"history.db"):
                first = AppState(); first.devices = [device]
                first.set_product(tmp, product)
                second = AppState(); second.devices = [device]; second.choose(tmp)
                self.assertEqual(second.product, product)
                report = second.report()
                self.assertEqual(report.to_dict()["schema_version"], 3)
                self.assertIn("Model 1", report_text(report))
                self.assertNotIn("<script>test</script>", report_html(report))
                self.assertIn("&lt;script&gt;", report_html(report))

    def test_offline_retry_retains_dated_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, serial="fixture", model="Generic USB Disk")
            with patch("mediaprobe.browserui.local_history_path", return_value=Path(tmp)/"history.db"):
                state = AppState(); state.devices = [device]
                state.set_product(tmp, {"brand": "Kingston", "model": "DataTraveler Max", "auto_lookup": False})
                reference = {"status": "done", "checked_at": utc_now(), "candidates": [{"title": "Demo", "url": "https://www.kingston.com/test"}]}
                with patch("mediaprobe.browserui.lookup_product", return_value=reference):
                    state.start_lookup(force=True)
                    worker = state.lookup_worker
                    if worker: worker.join(timeout=5)
                with patch("mediaprobe.browserui.lookup_product", return_value={"status": "unavailable", "checked_at": utc_now(), "message": "Offline"}):
                    state.start_lookup(force=True)
                    worker = state.lookup_worker
                    if worker: worker.join(timeout=5)
                self.assertTrue(state.online_lookup["cached"])
                self.assertEqual(state.online_lookup["candidates"], reference["candidates"])


if __name__ == "__main__": unittest.main()
