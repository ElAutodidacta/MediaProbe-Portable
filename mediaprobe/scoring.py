from __future__ import annotations

from .models import BenchmarkResult, CapacityResult, DeviceInfo, TechnicalAssessment


SPEED_THRESHOLDS = {"C10": 10, "U1": 10, "U3": 30, "V10": 10, "V30": 30, "V60": 60, "V90": 90}
APP_THRESHOLDS = {"A1": (1500, 500, 10), "A2": (4000, 2000, 10)}


def _speed_class(write: float | None) -> str:
    if write is None:
        return "No determinada"
    if write >= 90:
        return "Umbrales medidos de C10/U3/V90"
    if write >= 60:
        return "Umbrales medidos de C10/U3/V60"
    if write >= 30:
        return "Umbrales medidos de C10/U3/V30"
    if write >= 10:
        return "Umbrales medidos de C10/U1/V10"
    return "Por debajo de 10 MB/s medidos"


def _claimed_results(claims: list[str], bench: BenchmarkResult) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    write = bench.sustained_p05_mbps or bench.sequential_write_mbps
    long_enough = len(bench.write_samples) >= 6
    for raw in claims:
        claim = raw.upper().strip()
        if claim in SPEED_THRESHOLDS:
            threshold = SPEED_THRESHOLDS[claim]
            if write is None:
                verdict = "Sin prueba de escritura"
            elif write < threshold:
                verdict = f"No alcanzó {threshold} MB/s en este equipo ({write:.1f} MB/s observados)"
            elif not long_enough:
                verdict = f"Alcanzó {threshold} MB/s en prueba corta; falta ensayo sostenido"
            else:
                verdict = f"Umbral observado ({write:.1f} MB/s P05); no certifica el logotipo"
        elif claim in APP_THRESHOLDS:
            read_req, write_req, seq_req = APP_THRESHOLDS[claim]
            if None in (bench.random_read_iops, bench.random_write_iops, write):
                verdict = "Sin datos suficientes de IOPS y escritura"
            elif (bench.random_read_iops or 0) < read_req or (bench.random_write_iops or 0) < write_req or (write or 0) < seq_req:
                verdict = "No alcanzó todos los umbrales medidos en este equipo"
            else:
                verdict = "Umbrales medidos; no certifica funciones de host ni método SD"
        else:
            verdict = "Marcación desconocida"
        results.append({"claim": claim, "result": verdict})
    return results


def _reader_bottleneck(device: DeviceInfo, bench: BenchmarkResult) -> str:
    link = device.usb_link_mbps
    if not link:
        return "No determinable: velocidad USB negociada no expuesta"
    theoretical = link / 8
    observed = max(bench.sequential_read_mbps or 0, bench.sequential_write_mbps or 0)
    if observed <= 0:
        return f"Enlace: {link:g} Mb/s ({theoretical:.0f} MB/s teóricos); falta benchmark"
    practical = theoretical * (0.70 if link <= 480 else 0.80)
    if observed >= practical * 0.75:
        return f"Posible cuello de botella del enlace/lector: {observed:.1f} MB/s medidos frente a ~{practical:.0f} MB/s prácticos estimados"
    return f"Enlace {theoretical:.0f} MB/s teóricos; con {observed:.1f} MB/s medidos no se identifica el cuello de botella"


def assess(device: DeviceInfo, bench: BenchmarkResult, capacity: CapacityResult, claimed_classes: list[str] | None = None) -> TechnicalAssessment:
    a = TechnicalAssessment()
    claimed_classes = claimed_classes or []
    write = bench.sustained_p05_mbps or bench.sequential_write_mbps
    a.sd_speed_class = _speed_class(write)
    if write is not None and bench.random_read_iops is not None and bench.random_write_iops is not None:
        if write >= 10 and bench.random_read_iops >= 4000 and bench.random_write_iops >= 2000:
            a.application_class = "Umbrales medidos A2; funciones A2 no verificadas"
        elif write >= 10 and bench.random_read_iops >= 1500 and bench.random_write_iops >= 500:
            a.application_class = "Umbrales medidos A1"
        else:
            a.application_class = "No alcanzó A1 en esta configuración"
    a.claimed_class_results = _claimed_results(claimed_classes, bench)
    a.reader_bottleneck = _reader_bottleneck(device, bench)

    declared = device.raw.get("declared_capacity_gb")
    apparent_gap = False
    if declared:
        expected = float(declared) * 1_000_000_000
        physical = device.physical_bytes or device.total_bytes
        ratio = physical / expected if expected else 0
        if ratio < 0.88 or ratio > 1.05:
            apparent_gap = True
            a.warnings.append(f"La capacidad reportada ({physical / 1e9:.1f} GB) difiere de la anunciada ({float(declared):.1f} GB). Revise particiones y etiqueta.")

    bad_data = capacity.integrity_ok is False or capacity.mismatched_blocks > 0 or bool(capacity.io_errors) or bool(bench.errors)
    if bad_data:
        a.fake_risk = "Alto: corrupción o errores de E/S; posible falsificación o avería"
        a.verdict = "No recomendada: integridad o E/S falló"
    elif apparent_gap:
        a.fake_risk = "Alto: discrepancia de capacidad reportada; investigar particiones y etiqueta"
        a.verdict = "Investigar antes de comprar"
    elif capacity.integrity_ok and capacity.complete_volume_coverage and capacity.coverage_of_volume_percent >= 95:
        a.fake_risk = "Bajo para el espacio libre verificado; marca y área no probada sin certificar"
        a.verdict = "Apta para uso compatible con el rendimiento medido; no certifica autenticidad"
    elif capacity.integrity_ok:
        a.fake_risk = "Indeterminado: muestra correcta, capacidad restante no probada"
        a.verdict = "Resultado provisional: falta prueba completa de capacidad"
    elif write is not None:
        a.fake_risk = "Indeterminado: solo se midió rendimiento"
        a.verdict = "Resultado provisional: capacidad sin verificar"
    else:
        a.fake_risk = "Indeterminado: solo inspección"
        a.verdict = "Solo lectura: pendiente de pruebas"

    for item in a.claimed_class_results:
        if item["result"].startswith("No alcanzó"):
            a.warnings.append(f"Marcada {item['claim']}: {item['result']}.")

    # Fixed weights: an incomplete test cannot be normalized into a perfect score.
    points = 0.0
    if write is not None:
        points += min(25, max(0, write) / 90 * 25)
    if bench.sequential_read_mbps is not None:
        points += min(15, max(0, bench.sequential_read_mbps) / 170 * 15)
    if bench.random_read_iops is not None:
        points += min(10, max(0, bench.random_read_iops) / 4000 * 10)
    if bench.random_write_iops is not None:
        points += min(10, max(0, bench.random_write_iops) / 2000 * 10)
    if capacity.integrity_ok:
        points += 40 * min(1.0, capacity.coverage_of_volume_percent / 100)
    if write is not None or capacity.integrity_ok is not None:
        a.score = max(0, min(100, round(points)))
    if capacity.integrity_ok and capacity.complete_volume_coverage and capacity.coverage_of_volume_percent >= 95:
        a.confidence = "Alta para el volumen verificado; no para sectores no probados"
    elif capacity.integrity_ok and capacity.complete_volume_coverage:
        a.confidence = "Media: se verifico el espacio libre, pero el resto del volumen estaba ocupado"
    elif capacity.integrity_ok:
        a.confidence = "Media-baja: capacidad por muestra"
    elif write is not None:
        a.confidence = "Baja: rendimiento sin capacidad"
    else:
        a.confidence = "Solo inspección"

    if write:
        size = device.physical_bytes or device.total_bytes
        a.estimated_fill_hours = size / (write * 1_000_000) / 3600
        a.rationale.append(f"Llenar {size / 1e9:.1f} GB al ritmo observado llevaría al menos ~{a.estimated_fill_hours:.1f} h; puede ralentizarse.")
        if write >= 30 and not bad_data:
            a.recommendations.append("4K: el rendimiento observado es prometedor; valide el bitrate y la cámara reales.")
        else:
            a.recommendations.append("4K/U3: no recomendar con el rendimiento observado o los errores actuales.")
        if write >= 20 and not bad_data:
            a.recommendations.append("Dashcam: velocidad plausible, pero resistencia/endurance sin medir; busque una tarjeta High Endurance.")
        else:
            a.recommendations.append("Dashcam: no recomendar sin mejor rendimiento e integridad.")
        if (bench.random_read_iops or 0) >= 1500 and (bench.random_write_iops or 0) >= 500:
            a.recommendations.append("Aplicaciones: IOPS observados compatibles con umbrales A1, sin certificación.")
        else:
            a.recommendations.append("Almacenamiento básico: adecuado solo si la integridad posterior es correcta.")
    else:
        a.recommendations.append("Ejecute Modo tienda o una prueba completa antes de comprar.")

    if bench.cache_drop_at_bytes is not None:
        a.warnings.append(f"Caída de escritura tras ~{bench.cache_drop_at_bytes / 1e9:.2f} GB ({bench.cache_drop_percent:.0f}% entre inicio y final); posible agotamiento de caché.")
    if bench.disconnected or capacity.disconnected:
        a.warnings.append("Desconexión o desaparición de la unidad durante la prueba.")
    if capacity.mismatched_offsets:
        a.warnings.append("Hay desplazamientos lógicos corruptos; no se pueden traducir a sectores físicos con esta prueba de archivos.")
    if device.temperature_c is not None and device.temperature_c >= 70:
        a.warnings.append(f"Temperatura elevada: {device.temperature_c:.0f} °C.")
    if "fallo" in device.health.lower():
        a.warnings.append("SMART informó fallo; no use esta unidad para datos importantes.")
    if any(v > 0 for v in device.media_error_indicators.values()):
        a.warnings.append("SMART informa errores/sectores problemáticos; no use la unidad para datos importantes.")
    if not device.cid:
        a.warnings.append(device.register_note or "CID no disponible con este lector/sistema.")
    a.warnings.extend(bench.errors)
    a.warnings.extend(capacity.io_errors)
    a.rationale.append("El puntaje combina rendimiento y porcentaje real del volumen verificado; nunca certifica marca, logotipo SD ni sectores no cubiertos.")
    return a
