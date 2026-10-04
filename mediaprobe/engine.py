from __future__ import annotations

import os
import errno
import random
import shutil
import stat
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .models import BenchmarkResult, CapacityResult, DeviceInfo
from .util import APP_DIR_NAME, deterministic_block, same_path


Progress = Callable[[str, float], None]


class ProbeCancelled(Exception):
    pass


class ProbeDeadline(Exception):
    pass


class SafetyError(Exception):
    pass


def _cancelled(stop: threading.Event | None) -> None:
    if stop and stop.is_set():
        raise ProbeCancelled("Prueba detenida por el usuario")


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise ProbeDeadline("Tiempo objetivo alcanzado; resultado parcial.")


def _is_disconnect(exc: OSError, mount: str) -> bool:
    return not os.path.isdir(mount) or exc.errno in {errno.ENODEV, errno.ENXIO, errno.ENOTCONN}


def analyze_write_samples(samples: list[dict[str, float]]) -> tuple[float | None, float | None, float | None, int | None]:
    speeds = sorted(s["mbps"] for s in samples if s.get("mbps", 0) > 0)
    if not speeds:
        return None, None, None, None
    minimum = speeds[0]
    p05 = speeds[max(0, int((len(speeds) - 1) * 0.05))]
    if len(samples) < 6:
        return minimum, p05, None, None
    early = sorted(s["mbps"] for s in samples[:3])[1]
    late = sorted(s["mbps"] for s in samples[-3:])[1]
    drop = max(0.0, (early - late) / max(early, 0.000001) * 100)
    if drop < 35:
        return minimum, p05, drop, None
    threshold = early * 0.65
    at = next((int(s["end_bytes"]) for s in samples[3:] if s["mbps"] < threshold), None)
    return minimum, p05, drop, at


def _test_directory(device: DeviceInfo) -> Path:
    root = Path(device.mount)
    if not root.is_dir():
        raise SafetyError("El punto de montaje ya no esta disponible.")
    folder = root / APP_DIR_NAME / f"sesion-{uuid.uuid4().hex[:12]}"
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _cleanup(folder: Path) -> list[str]:
    errors: list[str] = []
    try:
        shutil.rmtree(folder)
        parent = folder.parent
        if parent.name == APP_DIR_NAME and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError as exc:
        errors.append(f"No se pudo retirar por completo la carpeta temporal: {exc}")
    return errors


def _sync(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def run_benchmark(
    device: DeviceInfo,
    file_size_mib: int = 256,
    random_operations: int = 1500,
    small_file_count: int = 250,
    progress: Progress | None = None,
    stop: threading.Event | None = None,
    deadline: float | None = None,
) -> BenchmarkResult:
    result = BenchmarkResult(started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    progress = progress or (lambda _m, _p: None)
    folder = _test_directory(device)
    path = folder / "benchmark.bin"
    file_size = file_size_mib * 1024 * 1024
    result.test_bytes = file_size
    min_free = file_size + 128 * 1024 * 1024
    try:
        free = shutil.disk_usage(device.mount).free
        if free < min_free:
            raise SafetyError(
                f"Espacio libre insuficiente. Se requieren al menos {min_free // (1024**2)} MiB."
            )
        block_size = 4 * 1024 * 1024
        blocks = [deterministic_block(0, i * block_size, block_size) for i in range(16)]
        result.sample_interval_bytes = 32 * 1024 * 1024
        progress("Escritura secuencial", 0.02)
        started = time.perf_counter()
        sample_started = started
        sample_bytes = 0
        total_written = 0
        with path.open("wb", buffering=0) as handle:
            remaining = file_size
            while remaining:
                _cancelled(stop)
                _check_deadline(deadline)
                piece = blocks[(total_written // block_size) % len(blocks)][: min(block_size, remaining)]
                handle.write(piece)
                remaining -= len(piece)
                total_written += len(piece)
                sample_bytes += len(piece)
                if sample_bytes >= result.sample_interval_bytes or remaining == 0:
                    _sync(handle)
                    now = time.perf_counter()
                    result.write_samples.append({"end_bytes": float(total_written), "mbps": sample_bytes / 1_000_000 / max(now - sample_started, 0.000001)})
                    sample_started = now
                    sample_bytes = 0
                progress("Escritura secuencial", 0.05 + 0.28 * (1 - remaining / file_size))
            _sync(handle)
        elapsed = max(time.perf_counter() - started, 0.000001)
        result.sequential_write_mbps = file_size / 1_000_000 / elapsed
        result.sustained_write_mbps = result.sequential_write_mbps
        result.sustained_min_mbps, result.sustained_p05_mbps, result.cache_drop_percent, result.cache_drop_at_bytes = analyze_write_samples(result.write_samples)

        progress("Lectura secuencial y verificacion", 0.35)
        read_bytes = 0
        mismatch = False
        started = time.perf_counter()
        with path.open("rb", buffering=0) as handle:
            while True:
                _cancelled(stop)
                data = handle.read(block_size)
                if not data:
                    break
                expected = blocks[(read_bytes // block_size) % len(blocks)][:len(data)]
                if data != expected:
                    mismatch = True
                    if len(result.mismatched_offsets) < 32:
                        result.mismatched_offsets.append(read_bytes)
                read_bytes += len(data)
                progress("Lectura secuencial y verificacion", 0.35 + 0.22 * read_bytes / file_size)
        elapsed = max(time.perf_counter() - started, 0.000001)
        result.sequential_read_mbps = read_bytes / 1_000_000 / elapsed
        if mismatch:
            result.errors.append("Los datos leidos no coinciden con los escritos en el benchmark secuencial.")

        progress("Acceso aleatorio 4 KiB", 0.59)
        rng = random.Random(0x4D5052)
        max_block = file_size // 4096
        positions = [rng.randrange(max_block) * 4096 for _ in range(random_operations)]
        samples = [deterministic_block(7, i, 4096) for i in range(min(random_operations, 32))]
        expected_random: dict[int, bytes] = {}
        with path.open("r+b", buffering=0) as handle:
            started = time.perf_counter()
            for index, offset in enumerate(positions):
                _cancelled(stop)
                _check_deadline(deadline)
                handle.seek(offset)
                payload = samples[index % len(samples)]
                handle.write(payload)
                expected_random[offset] = payload
            _sync(handle)
            elapsed = max(time.perf_counter() - started, 0.000001)
            result.random_write_iops = random_operations / elapsed
            result.random_write_mbps = random_operations * 4096 / 1_000_000 / elapsed

            started = time.perf_counter()
            for offset in positions:
                _cancelled(stop)
                _check_deadline(deadline)
                handle.seek(offset)
                actual = handle.read(4096)
                if actual != expected_random[offset]:
                    result.errors.append(f"Lectura aleatoria corrupta o incompleta en desplazamiento {offset}.")
                    if len(result.mismatched_offsets) < 32:
                        result.mismatched_offsets.append(offset)
                    break
            elapsed = max(time.perf_counter() - started, 0.000001)
            result.random_read_iops = random_operations / elapsed
            result.random_read_mbps = random_operations * 4096 / 1_000_000 / elapsed

        progress("Archivos pequenos", 0.75)
        small_dir = folder / "small"
        small_dir.mkdir()
        payload = deterministic_block(9, 0, 32 * 1024)
        started = time.perf_counter()
        for index in range(small_file_count):
            _cancelled(stop)
            _check_deadline(deadline)
            with (small_dir / f"f-{index:05d}.bin").open("wb", buffering=0) as handle:
                handle.write(payload)
        elapsed = max(time.perf_counter() - started, 0.000001)
        result.small_write_iops = small_file_count / elapsed

        started = time.perf_counter()
        for index in range(small_file_count):
            _cancelled(stop)
            _check_deadline(deadline)
            with (small_dir / f"f-{index:05d}.bin").open("rb", buffering=0) as handle:
                if handle.read() != payload:
                    result.errors.append(f"Archivo pequeno corrupto: f-{index:05d}.bin")
                    break
        elapsed = max(time.perf_counter() - started, 0.000001)
        result.small_read_iops = small_file_count / elapsed
        result.notes.append("Velocidades medidas mediante el sistema de archivos; incluyen cache y sobrecarga del sistema operativo.")
        progress("Benchmark finalizado", 1.0)
    except ProbeCancelled as exc:
        result.notes.append(str(exc))
    except ProbeDeadline as exc:
        result.timed_out = True
        result.notes.append(str(exc))
    except (OSError, SafetyError) as exc:
        result.errors.append(str(exc))
        if isinstance(exc, OSError):
            result.disconnected = _is_disconnect(exc, device.mount)
    finally:
        result.errors.extend(_cleanup(folder))
        result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return result


def run_capacity_test(
    device: DeviceInfo,
    maximum_bytes: int | None,
    exhaustive: bool,
    reserve_bytes: int = 512 * 1024 * 1024,
    progress: Progress | None = None,
    stop: threading.Event | None = None,
    deadline: float | None = None,
) -> CapacityResult:
    """Write and verify unique files. Existing user files are never opened or replaced."""
    progress = progress or (lambda _m, _p: None)
    result = CapacityResult(mode="Exhaustiva segura" if exhaustive else "Muestra segura")
    folder = _test_directory(device)
    started = time.perf_counter()
    file_limit = 256 * 1024 * 1024
    chunk_size = 4 * 1024 * 1024
    manifest: list[tuple[Path, int, int]] = []
    try:
        free = shutil.disk_usage(device.mount).free
        usable = max(0, free - reserve_bytes)
        requested = usable if exhaustive else min(usable, maximum_bytes or 2 * 1024**3)
        result.requested_bytes = requested
        if requested < 64 * 1024 * 1024:
            raise SafetyError("No hay 64 MiB libres ademas de la reserva de seguridad.")
        remaining = requested
        file_index = 0
        deadline_reached = False
        while remaining > 0 and not deadline_reached:
            _cancelled(stop)
            this_size = min(file_limit, remaining)
            path = folder / f"capacidad-{file_index:05d}.mpr"
            written = 0
            with path.open("xb", buffering=0) as handle:
                while written < this_size:
                    _cancelled(stop)
                    if deadline is not None and time.monotonic() >= deadline:
                        result.timed_out = True
                        deadline_reached = True
                        break
                    count = min(chunk_size, this_size - written)
                    data = deterministic_block(file_index, written, count)
                    handle.write(data)
                    written += count
                    result.written_bytes += count
                    progress("Llenando espacio de prueba", 0.48 * result.written_bytes / requested)
                _sync(handle)
            if written:
                manifest.append((path, file_index, written))
            else:
                path.unlink(missing_ok=True)
            remaining -= written
            file_index += 1

        for path, file_index, expected_size in manifest:
            offset = 0
            with path.open("rb", buffering=0) as handle:
                while offset < expected_size:
                    _cancelled(stop)
                    count = min(chunk_size, expected_size - offset)
                    actual = handle.read(count)
                    expected = deterministic_block(file_index, offset, count)
                    if actual != expected:
                        result.mismatched_blocks += 1
                        if len(result.mismatched_offsets) < 64:
                            result.mismatched_offsets.append({"file": path.name, "offset": offset})
                    else:
                        result.verified_bytes += len(actual)
                    if len(actual) != count:
                        result.io_errors.append(f"Lectura incompleta en {path.name}, desplazamiento {offset}.")
                        break
                    offset += count
                    progress("Verificando datos escritos", 0.5 + 0.5 * result.verified_bytes / requested)
        result.integrity_ok = (
            result.written_bytes > 0
            and result.verified_bytes == result.written_bytes
            and result.mismatched_blocks == 0
            and not result.io_errors
        )
        if result.timed_out and result.written_bytes == 0:
            result.integrity_ok = None
        # Coverage means all free addressable volume space except the documented reserve.
        result.coverage_of_volume_percent = min(100.0, 100.0 * result.verified_bytes / max(1, device.total_bytes))
        if device.physical_bytes:
            result.coverage_of_physical_percent = min(100.0, 100.0 * result.verified_bytes / device.physical_bytes)
        result.complete_volume_coverage = bool(exhaustive and not result.timed_out and result.written_bytes >= usable * 0.995 and result.integrity_ok)
        if result.complete_volume_coverage:
            result.note = (
                "Se verifico todo el espacio libre direccionable, salvo la reserva. "
                "Los datos que ya existian no fueron comprobados."
            )
        else:
            result.note = "Solo se verifico una parte del volumen; no demuestra la capacidad completa."
        progress("Verificacion de capacidad finalizada", 1.0)
    except ProbeCancelled:
        result.stopped = True
        result.note = "Prueba detenida; los archivos temporales se retiraron."
    except (OSError, SafetyError) as exc:
        result.io_errors.append(str(exc))
        result.integrity_ok = False
        if isinstance(exc, OSError):
            result.disconnected = _is_disconnect(exc, device.mount)
    finally:
        result.elapsed_seconds = time.perf_counter() - started
        result.io_errors.extend(_cleanup(folder))
    return result


def validate_destructive_target(original: DeviceInfo, current: DeviceInfo) -> None:
    if not original.removable or not current.removable:
        raise SafetyError("La unidad no esta identificada como extraible.")
    if original.system_disk or current.system_disk:
        raise SafetyError("MediaProbe nunca borra el disco del sistema.")
    if not same_path(original.mount, current.mount):
        raise SafetyError("Cambio el punto de montaje; operacion cancelada.")
    if original.disk_number is not None and current.disk_number != original.disk_number:
        raise SafetyError("Cambio el numero de disco; operacion cancelada.")
    if original.serial and current.serial and original.serial.strip() != current.serial.strip():
        raise SafetyError("Cambio el numero de serie; operacion cancelada.")
    if original.unique_id and current.unique_id and original.unique_id != current.unique_id:
        raise SafetyError("Cambio el identificador fisico; operacion cancelada.")
    if original.physical_bytes and current.physical_bytes and original.physical_bytes != current.physical_bytes:
        raise SafetyError("Cambio la capacidad del disco fisico; operacion cancelada.")
    tolerance = max(16 * 1024 * 1024, int(original.total_bytes * 0.01))
    if abs(original.total_bytes - current.total_bytes) > tolerance:
        raise SafetyError("Cambio la capacidad informada; operacion cancelada.")


def validate_safe_target(original: DeviceInfo, current: DeviceInfo) -> None:
    """Revalidate before any test file is created; no claim of hardware identity without IDs."""
    if original.system_disk or current.system_disk:
        raise SafetyError("El disco del sistema no se usa para pruebas de escritura.")
    if not same_path(original.mount, current.mount):
        raise SafetyError("Cambió el punto de montaje.")
    if original.disk_number is not None and current.disk_number != original.disk_number:
        raise SafetyError("Cambió el número de disco.")
    if original.serial and current.serial and original.serial.strip() != current.serial.strip():
        raise SafetyError("Cambió la serie del dispositivo.")
    if original.unique_id and current.unique_id and original.unique_id != current.unique_id:
        raise SafetyError("Cambió el identificador del disco.")
    if original.physical_bytes and current.physical_bytes and original.physical_bytes != current.physical_bytes:
        raise SafetyError("Cambió la capacidad del disco.")
    tolerance = max(16 * 1024 * 1024, int(original.total_bytes * 0.01))
    if abs(original.total_bytes - current.total_bytes) > tolerance:
        raise SafetyError("Cambió la capacidad del volumen.")


def destructive_confirmation(device: DeviceInfo) -> str:
    ident = device.serial.strip()[-8:] if device.serial.strip() else str(device.disk_number if device.disk_number is not None else "SIN-SERIE")
    return f"BORRAR {device.mount.rstrip('\\/')} {ident}"


def erase_volume_contents(device: DeviceInfo, progress: Progress | None = None, stop: threading.Event | None = None) -> list[str]:
    """Delete volume contents after the UI has completed all identity/phrase checks."""
    progress = progress or (lambda _m, _p: None)
    root = Path(device.mount)
    if not root.is_dir() or device.system_disk or not device.removable:
        raise SafetyError("Objetivo destructivo rechazado por las reglas de seguridad.")
    entries = list(root.iterdir())
    errors: list[str] = []
    for index, entry in enumerate(entries):
        _cancelled(stop)
        try:
            if entry.is_symlink() or entry.is_file():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.chmod(stat.S_IWRITE)
                entry.unlink()
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")
        progress("Borrando contenido de la unidad", (index + 1) / max(1, len(entries)))
    return errors
