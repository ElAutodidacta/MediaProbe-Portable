"""Declared product data and honest comparisons independent of the technical score."""
from __future__ import annotations

import math
from typing import Any

from .models import BenchmarkResult, DeviceInfo

TYPES = ("Sin especificar", "microSD", "SD", "Memoria USB", "SSD externo", "SSD interno", "HDD externo", "HDD interno", "Otro")


def validate_product(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("La ficha del producto debe ser un objeto.")
    out: dict[str, Any] = {}
    for key in ("brand", "model"):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > 120 or any(ord(x) < 32 for x in value):
            raise ValueError("Marca o modelo inválido (máximo 120 caracteres).")
        out[key] = value.strip()
    out["type"] = raw.get("type", "Sin especificar")
    if out["type"] not in TYPES:
        raise ValueError("Tipo de almacenamiento desconocido.")
    out["speed_basis"] = raw.get("speed_basis", "up_to")
    if out["speed_basis"] not in ("up_to", "sustained"):
        raise ValueError("Indique si la velocidad es 'hasta' o mínima sostenida.")
    for key, maximum in (("capacity_gb", 1_000_000), ("read_mbps", 100_000), ("write_mbps", 100_000)):
        raw_value = raw.get(key)
        if raw_value in (None, ""):
            out[key] = None
            continue
        try:
            value = float(str(raw_value).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Valor inválido: {key}.") from exc
        if not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(f"Valor fuera de rango: {key}.")
        out[key] = value
    out["auto_lookup"] = raw.get("auto_lookup", True)
    if not isinstance(out["auto_lookup"], bool):
        raise ValueError("La búsqueda automática debe estar activada o desactivada.")
    return out


def compare_product(product: dict[str, Any], device: DeviceInfo, bench: BenchmarkResult) -> list[dict[str, Any]]:
    rows = []
    physical = device.physical_bytes
    specs = [("Capacidad reportada", product.get("capacity_gb"), physical / 1e9 if physical else None, "GB"),
             ("Lectura secuencial", product.get("read_mbps"), bench.sequential_read_mbps, "MB/s"),
             ("Escritura secuencial", product.get("write_mbps"), bench.sequential_write_mbps, "MB/s"),
             ("Escritura sostenida P05", product.get("write_mbps"), bench.sustained_p05_mbps, "MB/s")]
    for label, advertised, observed, unit in specs:
        ratio = observed / advertised * 100 if advertised and observed is not None else None
        if ratio is None:
            note = "Falta dato anunciado o medición"
        elif unit == "GB":
            note = "Capacidad reportada por el controlador; falta verificar bytes" if 95 <= ratio <= 105 else "Discrepancia: revise capacidad, particiones y variante"
        elif product.get("speed_basis") == "sustained":
            note = "Alcanzó la referencia en esta sesión" if ratio >= 100 else "Por debajo de la referencia mínima indicada en este equipo"
        else:
            note = "Porcentaje frente a un máximo anunciado ('hasta'); no es un mínimo garantizado"
        rows.append({"metric": label, "advertised": advertised, "observed": observed, "unit": unit, "percent": ratio, "note": note})
    return rows
