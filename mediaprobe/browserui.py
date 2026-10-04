from __future__ import annotations

import json
import copy
import hashlib
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .discovery import discover_devices
from .engine import (
    SafetyError,
    destructive_confirmation,
    erase_volume_contents,
    run_benchmark,
    run_capacity_test,
    validate_destructive_target,
    validate_safe_target,
)
from .history import HistoryStore, local_history_path, device_key
from .product import validate_product, compare_product
from .online import lookup_product
from .models import BenchmarkResult, CapacityResult, DeviceInfo, ProbeReport, utc_now
from .reports import report_html, report_text
from .scoring import APP_THRESHOLDS, SPEED_THRESHOLDS, assess


PAGE = Path(__file__).with_name("frontend.html").read_text(encoding="utf-8")


class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.devices: list[DeviceInfo] = []
        self.device: DeviceInfo | None = None
        self.benchmark = BenchmarkResult()
        self.capacity = CapacityResult()
        self.errors: list[str] = []
        self.claimed_classes: list[str] = []
        self.mode = "Inspección"
        self.product = validate_product({})
        self.online_lookup: dict[str, Any] = {}
        self.product_key = ""
        self.lookup_generation = 0
        self.lookup_worker: threading.Thread | None = None
        self.lookup_pending = None
        self.history_error = ""
        try:
            self.history = HistoryStore(local_history_path())
        except OSError as exc:
            self.history = None
            self.history_error = f"Historial no disponible: {exc}"
        self.log: list[str] = ["MediaProbe iniciado. Las pruebas son locales; la consulta web opcional envía solo datos públicos del producto."]
        self.status = "Iniciando inventario…"
        self.progress = 0.0
        self.running = False
        self.stop = threading.Event()
        self.server: ThreadingHTTPServer | None = None
        self.worker: threading.Thread | None = None

    def refresh(self) -> list[DeviceInfo]:
        with self.lock:
            if self.running:
                raise SafetyError("Espere a que termine la prueba antes de actualizar unidades.")
        devices = discover_devices()
        with self.lock:
            self.devices = devices
            if self.device:
                match = next((d for d in devices if os.path.normcase(d.mount) == os.path.normcase(self.device.mount)), None)
                if match:
                    self.device = match
                else:
                    self.device = None
                    self.benchmark = BenchmarkResult()
                    self.capacity = CapacityResult()
            if not self.device and devices:
                self.device = devices[0]
            self.status = f"{len(devices)} volumen(es) detectado(s)" if devices else "No se encontraron volumenes; conecte una memoria y actualice"
        return devices

    def choose(self, mount: str) -> None:
        with self.lock:
            match = next((d for d in self.devices if os.path.normcase(d.mount) == os.path.normcase(mount)), None)
            if not match:
                raise SafetyError("La unidad seleccionada ya no esta disponible.")
            if not self.device or os.path.normcase(self.device.mount) != os.path.normcase(match.mount):
                self.benchmark = BenchmarkResult()
                self.capacity = CapacityResult()
                self.errors = []
                self.claimed_classes = []
                self.mode = "Inspección"
            self.device = match
            key = device_key(match.to_dict())
            if key != self.product_key:
                self.benchmark = BenchmarkResult()
                self.capacity = CapacityResult()
                self.errors = []
                self.product_key = key
                self.lookup_generation += 1
                profile = self.history.get_profile(key) if self.history else {}
                self.product = validate_product(profile.get("product", {}))
                self.online_lookup = profile.get("online_lookup", {})
            self._set_nominal(self.product.get("capacity_gb"))
            self.status = "Unidad seleccionada"

    def _persist_profile(self) -> None:
        if self.history and self.product_key:
            try:
                self.history.save_profile(self.product_key, self.product, self.online_lookup)
            except Exception as exc:
                self.history_error = f"No se pudo guardar la ficha: {exc}"

    def set_product(self, mount: str, raw: Any, search_online: bool = True) -> None:
        product = validate_product(raw)
        with self.lock:
            if self.running:
                raise SafetyError("Espere a que termine la prueba para cambiar la ficha.")
            self.choose(mount)
            if product != self.product:
                self.lookup_generation += 1
                self.lookup_pending = None
                self.online_lookup = {}
            self.product = product
            self._set_nominal(product.get("capacity_gb"))
            self._persist_profile()
        if search_online:
            self.start_lookup()

    def start_lookup(self, force: bool = False, source_url: str = "") -> None:
        with self.lock:
            if not self.device or (not force and not self.product.get("auto_lookup", True)):
                return
            product, device = copy.deepcopy(self.product), copy.deepcopy(self.device)
            signature = hashlib.sha256(json.dumps([product, device.model, source_url], sort_keys=True).encode()).hexdigest()
            if not force and self.online_lookup.get("signature") == signature:
                if self.online_lookup.get("status") in ("searching", "insufficient"):
                    return
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.online_lookup.get("checked_at", ""))).total_seconds()
                    if self.online_lookup.get("status") == "done" and age < 6 * 3600:
                        return
                except (ValueError, TypeError):
                    pass
            self.lookup_generation += 1
            generation, key = self.lookup_generation, self.product_key
            previous = copy.deepcopy(self.online_lookup)
            self.online_lookup = {"status": "searching", "message": "Comprobando conexión y buscando referencias del producto…", "signature": signature}
            task = (product, device, source_url, signature, generation, key, previous)
            self.lookup_pending = task
            if self.lookup_worker and self.lookup_worker.is_alive():
                return

            def work() -> None:
                while True:
                    with self.lock:
                        task = self.lookup_pending
                        self.lookup_pending = None
                        if task is None:
                            self.lookup_worker = None
                            return
                    p, d, url, sig, gen, task_key, previous = task
                    result = lookup_product(p, d, url)
                    if result.get("status") == "unavailable" and previous.get("candidates") and previous.get("signature") == sig:
                        result.update(candidates=previous["candidates"], cached=True, cached_at=previous.get("checked_at"),
                                      message=result["message"] + " Se muestran referencias guardadas de " + str(previous.get("checked_at", "fecha desconocida")) + ".")
                    result["signature"] = sig
                    with self.lock:
                        if self.lookup_generation == gen and self.product_key == task_key:
                            self.online_lookup = result
                            self._persist_profile()
            self.lookup_worker = threading.Thread(target=work, daemon=True)
            self.lookup_worker.start()

    def progress_cb(self, message: str, fraction: float) -> None:
        with self.lock:
            self.status = message
            self.progress = max(0.0, min(1.0, fraction))
            line = f"{self.progress * 100:5.1f}%  {message}"
            if self.log and "%" in self.log[-1]:
                self.log[-1] = line
            else:
                self.log.append(line)

    def _set_nominal(self, text: Any) -> None:
        if not self.device:
            return
        if text in (None, ""):
            self.device.raw.pop("declared_capacity_gb", None)
            return
        try:
            value = float(str(text).replace(",", "."))
        except ValueError as exc:
            raise SafetyError("Capacidad nominal invalida.") from exc
        if not 0 < value < 1_000_000:
            raise SafetyError("Capacidad nominal fuera de rango.")
        self.device.raw["declared_capacity_gb"] = value

    def _set_claims(self, values: Any) -> None:
        if values is None:
            return
        if not isinstance(values, list):
            raise SafetyError("Las clases impresas deben ser una lista.")
        allowed = set(SPEED_THRESHOLDS) | set(APP_THRESHOLDS)
        claims = [str(v).upper().strip() for v in values]
        if any(v not in allowed for v in claims):
            raise SafetyError("Clase impresa desconocida.")
        self.claimed_classes = list(dict.fromkeys(claims))

    def _save_history(self) -> None:
        if not self.history:
            return
        try:
            report = self.report()
            if report:
                self.history.save(report)
        except (OSError, ValueError) as exc:
            self.history_error = f"No se pudo guardar historial: {exc}"

    def inspect(self, mount: str, nominal: Any, claims: Any) -> None:
        with self.lock:
            if self.running:
                raise SafetyError("Ya hay una prueba activa.")
        self.refresh()
        with self.lock:
            self.choose(mount)
            self._set_nominal(nominal)
            self._set_claims(claims)
            self.mode = "Solo lectura"
            self.status = "Inspección completada sin escribir en la unidad"
            self.log.append(self.status)
            self._save_history()

    def start(self, kind: str, mount: str, size: int, nominal: Any, claims: Any = None, minutes: int = 3) -> None:
        with self.lock:
            if self.running:
                raise SafetyError("Ya hay una prueba activa.")
            if kind not in {"benchmark", "sample", "full", "sustained", "store"}:
                raise SafetyError("Tipo de prueba desconocido.")
            self.choose(mount)
            self._set_nominal(nominal)
            self._set_claims(claims)
            device = self.device
            if not device:
                raise SafetyError("Seleccione una unidad.")
            if device.system_disk:
                raise SafetyError("El disco del sistema no se usa para pruebas de escritura.")
            if kind == "store" and minutes not in (2, 3, 5):
                raise SafetyError("El modo tienda admite 2, 3 o 5 minutos.")
            self.mode = {"benchmark": "Benchmark rápido", "sample": "Muestra de capacidad", "full": "Profunda segura", "sustained": "Escritura sostenida", "store": "Modo tienda"}[kind]
            if kind == "store":
                self.benchmark = BenchmarkResult()
                self.capacity = CapacityResult()
            self.running = True; self.stop.clear(); self.progress = 0.0
            self.log.append(f"Iniciando {kind} en {device.mount}")
        def work() -> None:
            try:
                current = next((d for d in discover_devices() if os.path.normcase(d.mount) == os.path.normcase(device.mount)), None)
                if current is None:
                    raise SafetyError("La unidad seleccionada ya no está presente.")
                validate_safe_target(device, current)
                if kind == "benchmark":
                    result = run_benchmark(device, file_size_mib=max(128, min(size, 1024)), progress=self.progress_cb, stop=self.stop)
                    with self.lock: self.benchmark = result
                elif kind == "sustained":
                    result = run_benchmark(device, file_size_mib=max(512, min(size, 8192)), progress=self.progress_cb, stop=self.stop)
                    with self.lock: self.benchmark = result
                elif kind == "sample":
                    result = run_capacity_test(device, 2 * 1024**3, False, progress=self.progress_cb, stop=self.stop)
                    with self.lock: self.capacity = result
                elif kind == "full":
                    result = run_capacity_test(device, None, True, progress=self.progress_cb, stop=self.stop)
                    with self.lock: self.capacity = result
                elif kind == "store":
                    deadline = time.monotonic() + minutes * 60
                    result = run_benchmark(device, file_size_mib=128, random_operations=500, small_file_count=80, progress=self.progress_cb, stop=self.stop, deadline=deadline)
                    with self.lock: self.benchmark = result
                    if not self.stop.is_set() and not result.errors and not result.timed_out and time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        # Leave time to reread what is written. This is a target, not a hard I/O timeout.
                        sample_deadline = time.monotonic() + max(1, remaining * 0.45)
                        cap = run_capacity_test(device, 256 * 1024**2, False, progress=self.progress_cb, stop=self.stop, deadline=sample_deadline)
                        with self.lock: self.capacity = cap
            except Exception as exc:
                with self.lock: self.errors.append(str(exc)); self.log.append("ERROR: " + str(exc))
            finally:
                with self.lock:
                    self.running = False; self.status = "Prueba finalizada"; self.progress = 1.0
                    self._save_history()
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def start_destructive(self, mount: str, phrase: str, nominal: Any, claims: Any = None) -> None:
        with self.lock:
            if self.running:
                raise SafetyError("Ya hay una prueba activa.")
            self.choose(mount); self._set_nominal(nominal); self._set_claims(claims)
            original = self.device
            if not original or phrase != destructive_confirmation(original):
                raise SafetyError("La frase exacta no coincide. No se borro nada.")
            if not original.removable or original.system_disk:
                raise SafetyError("Objetivo destructivo rechazado.")
            if original.disk_number is None and not original.unique_id and not original.serial:
                raise SafetyError("Identidad de hardware insuficiente para borrado seguro; pruebe en un equipo que exponga número de disco o serie.")
            self.mode = "Destructiva de volumen"
            self.running = True; self.stop.clear(); self.progress = 0.0
            self.log.append(f"Revalidando objetivo destructivo {original.mount}")
        def work() -> None:
            try:
                current = next((d for d in discover_devices() if os.path.normcase(d.mount) == os.path.normcase(original.mount)), None)
                if not current:
                    raise SafetyError("La unidad ya no esta presente.")
                validate_destructive_target(original, current)
                errors = erase_volume_contents(current, self.progress_cb, self.stop)
                if errors:
                    with self.lock: self.errors.append("Elementos no borrados: " + " | ".join(errors))
                result = run_capacity_test(current, None, True, reserve_bytes=64 * 1024**2, progress=self.progress_cb, stop=self.stop)
                result.mode = "Destructiva (contenido borrado + volumen verificado)"
                with self.lock: self.capacity = result
            except Exception as exc:
                with self.lock: self.errors.append(str(exc)); self.log.append("ERROR: " + str(exc))
            finally:
                with self.lock:
                    self.running = False; self.status = "Prueba destructiva finalizada"; self.progress = 1.0
                    self._save_history()
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def report(self) -> ProbeReport | None:
        if not self.device:
            return None
        return ProbeReport(__version__, utc_now(), self.device, self.benchmark, self.capacity, assess(self.device, self.benchmark, self.capacity, self.claimed_classes), list(self.errors), self.mode, self.device.raw.get("declared_capacity_gb"), list(self.claimed_classes), copy.deepcopy(self.product), copy.deepcopy(self.online_lookup), compare_product(self.product, self.device, self.benchmark))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            report = self.report()
            assessment = report.assessment.to_dict() if report else {}
            return {
                "version": __version__, "status": self.status, "progress": self.progress, "running": self.running,
                "device": self.device.to_dict() if self.device else None,
                "benchmark": self.benchmark.to_dict(), "capacity": self.capacity.to_dict(),
                "assessment": assessment, "report_text": report_text(report) if report else "",
                "log": self.log[-80:],
                "destructive_phrase": destructive_confirmation(self.device) if self.device else "",
                "mode": self.mode, "claimed_classes": list(self.claimed_classes),
                "history_path": str(self.history.path) if self.history else "",
                "history_error": self.history_error,
                "product": copy.deepcopy(self.product), "online_lookup": copy.deepcopy(self.online_lookup),
                "product_key": self.product_key,
                "product_comparison": report.product_comparison if report else [],
            }


def _handler_factory(state: AppState, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MediaProbeLocal/1.2"
        def log_message(self, _format: str, *args) -> None:
            return
        def _authorized(self) -> bool:
            return self.path.startswith(f"/{token}") and (self.command == "GET" or self.headers.get("X-MediaProbe-Token") == token)
        def _send(self, code: int, body: bytes, content_type: str, disposition: str = "") -> None:
            self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; connect-src 'self'")
            if disposition: self.send_header("Content-Disposition", disposition)
            self.end_headers(); self.wfile.write(body)
        def _json(self, data: Any, code: int = 200) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        def _body(self) -> dict[str, Any]:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        def do_GET(self) -> None:
            if not self._authorized(): self._json({"error": "No autorizado"}, 403); return
            path = urllib.parse.urlparse(self.path).path
            if path in (f"/{token}", f"/{token}/"):
                page = PAGE.replace("__TOKEN__", json.dumps(token)).encode("utf-8")
                self._send(200, page, "text/html; charset=utf-8"); return
            if path == f"/{token}/api/status": self._json(state.snapshot()); return
            if path == f"/{token}/api/history":
                self._json({"rows": state.history.list() if state.history else [], "path": str(state.history.path) if state.history else "", "error": state.history_error}); return
            if path == f"/{token}/api/compare":
                raw_ids = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("ids", [""])[0]
                try:
                    ids = [int(x) for x in raw_ids.split(",") if x][:5]
                except ValueError:
                    self._json({"error": "IDs inválidos"}, 400); return
                self._json({"reports": state.history.compare(ids) if state.history else []}); return
            report = state.report()
            if not report: self._json({"error": "No hay informe"}, 404); return
            stamp = time.strftime("%Y%m%d-%H%M%S")
            if path.endswith("/report.txt"):
                self._send(200, report_text(report).encode("utf-8"), "text/plain; charset=utf-8", f'attachment; filename="MediaProbe-{stamp}.txt"'); return
            if path.endswith("/report.json"):
                self._send(200, json.dumps(report.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", f'attachment; filename="MediaProbe-{stamp}.json"'); return
            if path.endswith("/report.html"):
                self._send(200, report_html(report).encode("utf-8"), "text/html; charset=utf-8", f'attachment; filename="MediaProbe-{stamp}.html"'); return
            self._json({"error": "No encontrado"}, 404)
        def do_POST(self) -> None:
            if not self._authorized(): self._json({"error": "No autorizado"}, 403); return
            path = urllib.parse.urlparse(self.path).path
            try:
                data = self._body()
                if path.endswith("/api/devices"):
                    devices = state.refresh(); self._json({"devices": [{"mount": d.mount, "display": d.display_name} for d in devices]}); return
                if path.endswith("/api/select"):
                    state.choose(str(data.get("mount", ""))); state.start_lookup(); self._json(state.snapshot()); return
                if path.endswith("/api/product"):
                    state.set_product(str(data.get("mount", "")), data.get("product")); self._json(state.snapshot()); return
                if path.endswith("/api/lookup"):
                    state.start_lookup(force=True, source_url=str(data.get("source_url", ""))); self._json(state.snapshot()); return
                if path.endswith(("/api/run", "/api/inspect", "/api/destructive")) and "product" in data:
                    state.set_product(str(data.get("mount", "")), data["product"])
                if path.endswith("/api/run"):
                    state.start(str(data.get("kind", "")), str(data.get("mount", "")), int(data.get("size", 256)), data.get("nominal"), data.get("claims"), int(data.get("minutes", 3))); self._json(state.snapshot(), 202); return
                if path.endswith("/api/inspect"):
                    state.inspect(str(data.get("mount", "")), data.get("nominal"), data.get("claims")); self._json(state.snapshot()); return
                if path.endswith("/api/destructive"):
                    state.start_destructive(str(data.get("mount", "")), str(data.get("phrase", "")), data.get("nominal"), data.get("claims")); self._json(state.snapshot(), 202); return
                if path.endswith("/api/stop"):
                    state.stop.set(); state.status = "Deteniendo y retirando temporales…"; self._json(state.snapshot()); return
                if path.endswith("/api/shutdown"):
                    state.stop.set(); self._json({"ok": True})
                    def shutdown_after_cleanup() -> None:
                        if state.worker and state.worker.is_alive():
                            state.worker.join(timeout=60)
                        self.server.shutdown()
                    threading.Thread(target=shutdown_after_cleanup, daemon=True).start(); return
                self._json({"error": "No encontrado"}, 404)
            except (SafetyError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)
            except Exception as exc:
                self._json({"error": f"Error interno: {exc}"}, 500)
    return Handler


def run_browser_ui(no_browser: bool = False) -> None:
    state = AppState()
    token = secrets.token_urlsafe(18)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(state, token))
    state.server = server
    url = f"http://127.0.0.1:{server.server_port}/{token}/"
    port_file = Path(os.getenv("TEMP") or ".") / "MediaProbe-port.txt"
    try:
        port_file.write_text(url, encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=state.refresh, daemon=True).start()
    if not no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    finally:
        state.stop.set(); server.server_close()
        try: port_file.unlink()
        except OSError: pass
