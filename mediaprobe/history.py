"""Small local SQLite history; never stores data on the medium under test."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import ProbeReport
from .util import executable_dir


def device_key(device: dict[str, Any]) -> str:
    identity = "|".join(str(device.get(k) or "") for k in ("unique_id", "serial", "vid", "pid", "model", "physical_bytes", "total_bytes"))
    if not any(device.get(k) for k in ("unique_id", "serial", "vid", "pid", "model")):
        identity += "|" + str(device.get("mount") or "")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _within(path: Path, root: str) -> bool:
    try:
        left = os.path.normcase(str(path.resolve()))
        right = os.path.normcase(str(Path(root).resolve()))
        return os.path.commonpath((left, right)) == right
    except (OSError, ValueError):
        return False


def default_history_path(avoid_mount: str = "") -> Path:
    portable = executable_dir() / "data" / "history.sqlite3"
    if avoid_mount and _within(portable, avoid_mount):
        return _fallback_path()
    try:
        portable.parent.mkdir(parents=True, exist_ok=True)
        probe = portable.parent / ".write-test"
        with probe.open("x", encoding="ascii") as handle:
            handle.write("ok")
        probe.unlink()
        return portable
    except OSError:
        return _fallback_path()


def _fallback_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "MediaProbe" / "history.sqlite3"
    base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "mediaprobe" / "history.sqlite3"


def local_history_path() -> Path:
    """Host-local history avoids any write to the removable medium being tested."""
    return _fallback_path()


class HistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                device_key TEXT NOT NULL,
                model TEXT NOT NULL,
                mount TEXT NOT NULL,
                mode TEXT NOT NULL,
                verdict TEXT NOT NULL,
                score INTEGER,
                verified_bytes INTEGER NOT NULL,
                report_json TEXT NOT NULL
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_reports_device ON reports(device_key, id DESC)")
            con.execute("CREATE TABLE IF NOT EXISTS product_profiles (device_key TEXT PRIMARY KEY, data_json TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    @contextmanager
    def _connection(self):
        con = self._connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def save(self, report: ProbeReport) -> int:
        data = report.to_dict()
        device = data["device"]
        with self._connection() as con:
            cursor = con.execute(
                "INSERT INTO reports (created_at,device_key,model,mount,mode,verdict,score,verified_bytes,report_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (data["created_at"], device_key(device), device.get("model") or "No expuesto", device.get("mount") or "",
                 data.get("mode") or "", data["assessment"].get("verdict") or "", data["assessment"].get("score"),
                 data["capacity"].get("verified_bytes") or 0, json.dumps(data, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id,created_at,device_key,model,mount,mode,verdict,score,verified_bytes FROM reports ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, report_id: int) -> dict[str, Any] | None:
        with self._connection() as con:
            row = con.execute("SELECT report_json FROM reports WHERE id=?", (report_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def compare(self, ids: list[int]) -> list[dict[str, Any]]:
        return [data for report_id in ids[:5] if (data := self.get(report_id)) is not None]

    def save_profile(self, key: str, product: dict[str, Any], lookup: dict[str, Any]) -> None:
        with self._connection() as con:
            con.execute("INSERT INTO product_profiles VALUES (?,?) ON CONFLICT(device_key) DO UPDATE SET data_json=excluded.data_json",
                        (key, json.dumps({"product": product, "online_lookup": lookup}, ensure_ascii=False)))

    def get_profile(self, key: str) -> dict[str, Any]:
        with self._connection() as con:
            row = con.execute("SELECT data_json FROM product_profiles WHERE device_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else {}
