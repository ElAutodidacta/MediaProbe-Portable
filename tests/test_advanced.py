from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mediaprobe.engine import SafetyError, analyze_write_samples, run_capacity_test, validate_safe_target
from mediaprobe.browserui import AppState
from mediaprobe.history import HistoryStore
from mediaprobe.models import BenchmarkResult, CapacityResult, DeviceInfo, ProbeReport, utc_now
from mediaprobe.scoring import assess


class AdvancedTests(unittest.TestCase):
    def test_cache_drop_detection(self):
        samples = [{"end_bytes": float((i + 1) * 32 * 1024**2), "mbps": speed} for i, speed in enumerate([100, 98, 95, 70, 30, 25, 23, 20])]
        minimum, p05, drop, at = analyze_write_samples(samples)
        self.assertEqual(minimum, 20)
        self.assertEqual(p05, 20)
        self.assertGreater(drop or 0, 70)
        self.assertIsNotNone(at)

    def test_claimed_u3_below_threshold_and_no_perfect_partial_score(self):
        device = DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, physical_bytes=128_000_000_000, usb_link_mbps=480)
        bench = BenchmarkResult(sequential_write_mbps=20, sequential_read_mbps=35, random_read_iops=1000, random_write_iops=400, sustained_p05_mbps=18)
        capacity = CapacityResult(integrity_ok=True, written_bytes=2 * 1024**3, verified_bytes=2 * 1024**3, coverage_of_volume_percent=1.68)
        a = assess(device, bench, capacity, ["U3", "V30", "A1"])
        self.assertLess(a.score or 100, 80)
        self.assertIn("No alcanzó", a.claimed_class_results[0]["result"])
        self.assertIn("provisional", a.verdict.lower())
        self.assertIn("enlace", a.reader_bottleneck.lower())

    def test_occupied_volume_keeps_provisional_verdict(self):
        device = DeviceInfo(mount="X:\\", total_bytes=128_000_000_000)
        capacity = CapacityResult(integrity_ok=True, complete_volume_coverage=True, coverage_of_volume_percent=40)
        result = assess(device, BenchmarkResult(), capacity)
        self.assertIn("provisional", result.verdict.lower())
        self.assertIn("ocupado", result.confidence.lower())

    def test_capacity_mismatch_counts_only_matching_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, total_bytes=1024**3, free_bytes=1024**3)
            calls = 0
            def altered(_file: int, _offset: int, size: int) -> bytes:
                nonlocal calls
                calls += 1
                return (b"A" if calls <= 16 else b"B") * size
            with patch("mediaprobe.engine.deterministic_block", side_effect=altered):
                result = run_capacity_test(device, 64 * 1024**2, False, reserve_bytes=0)
            self.assertEqual(result.verified_bytes, 0)
            self.assertEqual(result.mismatched_blocks, 16)
            self.assertEqual(len(result.mismatched_offsets), 16)
            self.assertFalse(result.integrity_ok)
            self.assertFalse((Path(tmp) / ".mediaprobe-test").exists())

    def test_expired_store_budget_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, total_bytes=1024**3, free_bytes=1024**3)
            result = run_capacity_test(device, 64 * 1024**2, False, reserve_bytes=0, deadline=time.monotonic() - 1)
            self.assertTrue(result.timed_out)
            self.assertIsNone(result.integrity_ok)
            self.assertEqual(result.verified_bytes, 0)

    def test_recheck_rejects_changed_identity(self):
        old = DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=4, serial="abc")
        new = DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=5, serial="abc")
        with self.assertRaises(SafetyError):
            validate_safe_target(old, new)

    def test_history_round_trip_and_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp) / "history.sqlite3")
            device = DeviceInfo(mount="X:\\", model="Demo", serial="123", total_bytes=128_000_000_000)
            report = ProbeReport("test", utc_now(), device, mode="Solo lectura")
            ids = [store.save(report), store.save(report)]
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(len(store.compare(ids)), 2)
            self.assertEqual(store.get(ids[0])["mode"], "Solo lectura")

    def test_store_workflow_and_read_only_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "device"
            target.mkdir()
            device = DeviceInfo(mount=str(target), total_bytes=1024**3, free_bytes=1024**3, removable=True, serial="test-1")
            database = Path(tmp) / "history.sqlite3"
            bench = BenchmarkResult(sequential_write_mbps=40, sequential_read_mbps=60)
            cap = CapacityResult(written_bytes=64 * 1024**2, verified_bytes=64 * 1024**2, integrity_ok=True)
            with patch("mediaprobe.browserui.local_history_path", return_value=database), \
                 patch("mediaprobe.browserui.discover_devices", return_value=[device]), \
                 patch("mediaprobe.browserui.run_benchmark", return_value=bench) as benchmark, \
                 patch("mediaprobe.browserui.run_capacity_test", return_value=cap) as capacity:
                state = AppState()
                state.refresh()
                state.inspect(str(target), 1, ["U3"])
                self.assertFalse(list(target.iterdir()))
                self.assertEqual(len(state.history.list()), 1)
                state.start("store", str(target), 128, 1, ["U3"], minutes=2)
                state.worker.join(timeout=5)
                self.assertFalse(state.running)
                self.assertEqual(state.mode, "Modo tienda")
                self.assertEqual(len(state.history.list()), 2)
                benchmark.assert_called_once()
                capacity.assert_called_once()
                self.assertEqual(state.report().claimed_classes, ["U3"])


if __name__ == "__main__":
    unittest.main()
