from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from mediaprobe.engine import (
    SafetyError,
    destructive_confirmation,
    run_benchmark,
    run_capacity_test,
    validate_destructive_target,
)
from mediaprobe.models import DeviceInfo, ProbeReport, utc_now
from mediaprobe.reports import export_report, report_html, report_text
from mediaprobe.scoring import assess
from mediaprobe.util import deterministic_block, parse_vid_pid


class CoreTests(unittest.TestCase):
    def test_pattern_is_repeatable_and_position_specific(self):
        self.assertEqual(deterministic_block(1, 0, 8192), deterministic_block(1, 0, 8192))
        self.assertNotEqual(deterministic_block(1, 0, 8192), deterministic_block(1, 4096, 8192))

    def test_vid_pid_parser(self):
        self.assertEqual(parse_vid_pid(r"USB\VID_0781&PID_5581\123"), ("0781", "5581"))
        self.assertEqual(parse_vid_pid("nothing"), ("", ""))

    def test_benchmark_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, total_bytes=4 * 1024**3, free_bytes=3 * 1024**3, removable=True)
            bench = run_benchmark(device, file_size_mib=16, random_operations=100, small_file_count=20)
            self.assertFalse(bench.errors, bench.errors)
            self.assertGreater(bench.sequential_write_mbps or 0, 0)
            self.assertGreater(bench.random_read_iops or 0, 0)
            self.assertFalse((Path(tmp) / ".mediaprobe-test").exists())
            capacity = run_capacity_test(device, maximum_bytes=64 * 1024**2, exhaustive=False, reserve_bytes=0)
            self.assertTrue(capacity.integrity_ok, capacity.io_errors)
            self.assertEqual(capacity.written_bytes, 64 * 1024**2)
            assessment = assess(device, bench, capacity)
            report = ProbeReport("test", utc_now(), device, bench, capacity, assessment)
            self.assertIn("Puntuación técnica", report_text(report))
            self.assertIn("<!doctype html>", report_html(report))
            paths = export_report(report, Path(tmp) / "informe")
            self.assertEqual(len(paths), 3)
            data = json.loads(paths[1].read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 3)

    def test_cancelled_capacity_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = DeviceInfo(mount=tmp, total_bytes=1024**3, free_bytes=1024**3, removable=True)
            stop = threading.Event(); stop.set()
            result = run_capacity_test(device, maximum_bytes=64 * 1024**2, exhaustive=False, reserve_bytes=0, stop=stop)
            self.assertTrue(result.stopped)
            self.assertFalse((Path(tmp) / ".mediaprobe-test").exists())

    def test_destructive_identity_guard(self):
        original = DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=3, serial="ABC123", removable=True)
        self.assertEqual(destructive_confirmation(original), "BORRAR X: ABC123")
        validate_destructive_target(original, DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=3, serial="ABC123", removable=True))
        with self.assertRaises(SafetyError):
            validate_destructive_target(original, DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=4, serial="ABC123", removable=True))
        with self.assertRaises(SafetyError):
            validate_destructive_target(original, DeviceInfo(mount="X:\\", total_bytes=128_000_000_000, disk_number=3, serial="ABC123", removable=True, system_disk=True))


if __name__ == "__main__":
    unittest.main()
