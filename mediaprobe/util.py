from __future__ import annotations

import os
import platform
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


APP_DIR_NAME = ".mediaprobe-test"


def human_bytes(value: int | float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    number = float(value or 0)
    for unit in units:
        if abs(number) < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TiB"


def safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def run_command(args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    flags = 0
    if platform.system() == "Windows":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
        return done.returncode, done.stdout.strip(), done.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def find_optional_tool(name: str) -> str | None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    local = executable_dir() / "tools" / f"{name}{suffix}"
    if local.is_file():
        return str(local)
    return shutil.which(name)


def parse_vid_pid(text: str) -> tuple[str, str]:
    match = re.search(r"VID[_:=]?([0-9A-F]{4}).*PID[_:=]?([0-9A-F]{4})", text or "", re.I)
    return (match.group(1).upper(), match.group(2).upper()) if match else ("", "")


def deterministic_block(file_index: int, offset: int, size: int) -> bytes:
    """Generate repeatable, non-compressible-enough data without storing a reference file."""
    seed = 0x4D50524F4245 ^ (file_index << 33) ^ offset
    return random.Random(seed).randbytes(size)


def same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False
