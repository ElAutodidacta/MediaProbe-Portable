from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .models import ProbeReport
from .util import human_bytes


def _fmt(value: float | None, suffix: str = "") -> str:
    return "No medido" if value is None else f"{value:.2f}{suffix}"


def report_text(report: ProbeReport) -> str:
    d, b, c, a = report.device, report.benchmark, report.capacity, report.assessment
    lines = [
        "MEDIAPROBE PORTABLE — INFORME TÉCNICO", "=" * 52,
        f"Fecha: {report.created_at}", f"Versión: {report.app_version}  Modo: {report.mode}", "",
        "IDENTIFICACIÓN Y CAPACIDAD",
        f"Unidad: {d.mount}  Etiqueta: {d.label or '—'}  Sistema de archivos: {d.filesystem or '—'}",
        f"Anunciada: {str(report.declared_capacity_gb) + ' GB' if report.declared_capacity_gb else 'No indicada'}",
        f"Disco físico reportado: {human_bytes(d.physical_bytes) if d.physical_bytes else 'No expuesto'}",
        f"Volumen visible: {human_bytes(d.total_bytes)}  Libre al inspeccionar: {human_bytes(d.free_bytes)}",
        f"Realmente verificado y coincidente: {human_bytes(c.verified_bytes)} ({c.coverage_of_volume_percent:.2f}% del volumen)",
        f"Cobertura del disco reportado: {c.coverage_of_physical_percent:.2f}%" if c.coverage_of_physical_percent is not None else "Cobertura del disco reportado: no calculable",
        f"Modelo: {d.model or 'No expuesto'}  Serie: {d.serial or 'No expuesta'}",
        f"VID/PID: {d.vid or '—'}/{d.pid or '—'}  Controlador: {d.controller or 'No expuesto'}",
        f"Bus: {d.bus_type}  Enlace: {d.bus_speed}",
        f"Máximo teórico del enlace: {d.usb_link_mbps / 8:.1f} MB/s (antes de sobrecarga)" if d.usb_link_mbps else "Máximo teórico del enlace: no expuesto",
        f"Salud: {d.health}  Temperatura: {_fmt(d.temperature_c, ' °C')}",
        f"Contadores E/S: lectura={d.read_errors if d.read_errors is not None else '—'}; escritura={d.write_errors if d.write_errors is not None else '—'}",
        f"Indicadores de medio SMART: {json.dumps(d.media_error_indicators, ensure_ascii=False) if d.media_error_indicators else 'No expuestos'}",
        "", "REGISTROS SD/MMC",
        f"CID: {d.cid or 'No accesible'}", f"CSD: {d.csd or 'No accesible'}", f"OCR: {d.ocr or 'No accesible'}",
        f"Nota: {d.register_note}", "", "RENDIMIENTO",
        f"Secuencial: escritura {_fmt(b.sequential_write_mbps, ' MB/s')} / lectura {_fmt(b.sequential_read_mbps, ' MB/s')}",
        f"Escritura por tramos: mínimo {_fmt(b.sustained_min_mbps, ' MB/s')} / P05 {_fmt(b.sustained_p05_mbps, ' MB/s')} / {len(b.write_samples)} tramos",
        f"Caída inicio→final: {_fmt(b.cache_drop_percent, '%')}  Inicio aproximado: {human_bytes(b.cache_drop_at_bytes) if b.cache_drop_at_bytes else 'no localizado'}",
        f"Aleatorio 4 KiB: escritura {_fmt(b.random_write_iops, ' IOPS')} / lectura {_fmt(b.random_read_iops, ' IOPS')}",
        f"Archivos pequeños: escritura {_fmt(b.small_write_iops, ' ops/s')} / lectura {_fmt(b.small_read_iops, ' ops/s')}",
        f"Posible cuello de botella: {a.reader_bottleneck}", "", "INTEGRIDAD",
        f"Modo: {c.mode}  Escrito: {human_bytes(c.written_bytes)}  Coincidente: {human_bytes(c.verified_bytes)}",
        f"Bloques discrepantes: {c.mismatched_blocks}  Errores E/S: {len(c.io_errors)}  Desconexión: {'Sí' if c.disconnected or b.disconnected else 'No'}",
        f"Desplazamientos lógicos: {json.dumps(c.mismatched_offsets[:20], ensure_ascii=False)}",
        f"Espacio libre cubierto salvo reserva: {'Sí' if c.complete_volume_coverage else 'No'}",
        f"Integridad: {'Correcta en bytes verificados' if c.integrity_ok is True else ('Falló' if c.integrity_ok is False else 'No probada')}",
        f"Nota: {c.note or '—'}", "", "EVALUACIÓN",
        f"Conclusión: {a.verdict}",
        f"Puntuación técnica: {a.score if a.score is not None else '—'}/100  Confianza: {a.confidence}",
        f"Riesgo de capacidad falsa: {a.fake_risk}",
        f"Umbrales SD observados: {a.sd_speed_class}  Aplicaciones: {a.application_class}",
        f"Tiempo estimado para llenar: {_fmt(a.estimated_fill_hours, ' h')}",
        f"Clases impresas: {', '.join(report.claimed_classes) or 'No indicadas'}",
        *[f"- {item['claim']}: {item['result']}" for item in a.claimed_class_results],
        "", "RECOMENDACIONES", *[f"- {x}" for x in a.recommendations],
        "", "ADVERTENCIAS", *([f"- {x}" for x in a.warnings] or ["- Ninguna adicional."]),
        "", "LÍMITES",
        "La prueba de archivos no verifica sectores no particionados ni localiza sectores físicos defectuosos.",
        "La clase observada no certifica un logotipo SD. El CID tampoco certifica originalidad.",
        "El rendimiento depende de dispositivo, lector, puerto, cable, sistema y caché.",
    ]
    product_lines = ["FICHA DEL PRODUCTO", f"Tipo: {report.product.get('type', 'No indicado')}",
                     f"Marca / modelo indicado: {report.product.get('brand') or '—'} / {report.product.get('model') or '—'}",
                     "Velocidades anunciadas: " + ("mínimo sostenido indicado" if report.product.get('speed_basis') == 'sustained' else "hasta / máximo anunciado")]
    for row in report.product_comparison:
        product_lines.append(f"{row['metric']}: anunciado={_fmt(row['advertised'], ' ' + row['unit'])}; observado={_fmt(row['observed'], ' ' + row['unit'])}; {_fmt(row['percent'], '%')} · {row['note']}")
    online = report.online_lookup
    product_lines.extend(["", "REFERENCIAS EN INTERNET", online.get('message', 'Sin consulta'), f"Consulta: {online.get('checked_at', '—')}", f"Búsqueda: {online.get('query', '—')}", online.get('identity_warning', '')])
    for row in online.get('candidates', []):
        product_lines.extend([f"- {row['title']} · {row['match']}", f"  {row['url']}"])
        if row.get('reference_speeds'):
            product_lines.append("  Referencia publicada en extracto (revise variante): " + json.dumps(row['reference_speeds'], ensure_ascii=False))
        product_lines.extend("  " + warning for warning in row.get('spec_disagreements', []))
    product_lines.extend([online.get('note', 'Una referencia web no autentica esta unidad.'), ""])
    lines[6:6] = product_lines
    return "\n".join(lines)


def _rows(mapping: list[tuple[str, Any]]) -> str:
    return "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in mapping)


def _chart(report: ProbeReport) -> str:
    samples = report.benchmark.write_samples
    if not samples:
        return "<p>Sin serie de escritura.</p>"
    top = max(1.0, max(s["mbps"] for s in samples))
    points = " ".join(f"{(i/max(1,len(samples)-1))*700:.1f},{130-(s['mbps']/top)*115:.1f}" for i, s in enumerate(samples))
    return f'<svg viewBox="0 0 720 150" role="img" aria-label="Velocidad de escritura por tramo"><rect width="720" height="150" fill="#f4f8f7"/><polyline points="{points}" fill="none" stroke="#087f73" stroke-width="3"/></svg>'


def report_html(report: ProbeReport) -> str:
    d, b, c, a = report.device, report.benchmark, report.capacity, report.assessment
    warnings = "".join(f"<li>{html.escape(x)}</li>" for x in a.warnings) or "<li>Ninguna adicional</li>"
    recs = "".join(f"<li>{html.escape(x)}</li>" for x in a.recommendations)
    claimed = "".join(f"<li><b>{html.escape(x['claim'])}</b>: {html.escape(x['result'])}</li>" for x in a.claimed_class_results) or "<li>No indicadas</li>"
    device_rows = _rows([
        ("Unidad", d.mount), ("Etiqueta / sistema", f"{d.label or '—'} / {d.filesystem or '—'}"),
        ("Anunciada", f"{report.declared_capacity_gb} GB" if report.declared_capacity_gb else "No indicada"),
        ("Disco físico reportado", human_bytes(d.physical_bytes) if d.physical_bytes else "No expuesto"),
        ("Volumen / libre", f"{human_bytes(d.total_bytes)} / {human_bytes(d.free_bytes)}"),
        ("Modelo / serie", f"{d.model or 'No expuesto'} / {d.serial or 'No expuesta'}"),
        ("VID / PID", f"{d.vid or '—'} / {d.pid or '—'}"),
        ("Bus / enlace", f"{d.bus_type} / {d.bus_speed}"),
        ("Enlace teórico", f"{d.usb_link_mbps / 8:.1f} MB/s" if d.usb_link_mbps else "No expuesto"),
        ("Controlador", d.controller or "No expuesto"),
        ("Salud / temperatura", f"{d.health} / {_fmt(d.temperature_c, ' °C')}"),
        ("Indicadores de medio SMART", json.dumps(d.media_error_indicators, ensure_ascii=False) if d.media_error_indicators else "No expuestos"),
    ])
    register_rows = _rows([("CID", d.cid or "No accesible"), ("CSD", d.csd or "No accesible"), ("OCR", d.ocr or "No accesible"), ("Explicación", d.register_note)])
    speed_rows = _rows([
        ("Secuencial escritura / lectura", f"{_fmt(b.sequential_write_mbps, ' MB/s')} / {_fmt(b.sequential_read_mbps, ' MB/s')}"),
        ("Escritura P05 / mínimo", f"{_fmt(b.sustained_p05_mbps, ' MB/s')} / {_fmt(b.sustained_min_mbps, ' MB/s')}"),
        ("Caída de caché estimada", _fmt(b.cache_drop_percent, "%")),
        ("Aleatorio 4 KiB escritura / lectura", f"{_fmt(b.random_write_iops, ' IOPS')} / {_fmt(b.random_read_iops, ' IOPS')}"),
        ("Archivos pequeños escritura / lectura", f"{_fmt(b.small_write_iops, ' ops/s')} / {_fmt(b.small_read_iops, ' ops/s')}"),
    ])
    capacity_rows = _rows([
        ("Modo", c.mode), ("Escrito / coincidente", f"{human_bytes(c.written_bytes)} / {human_bytes(c.verified_bytes)}"),
        ("Cobertura del volumen", f"{c.coverage_of_volume_percent:.2f}%"),
        ("Cobertura del disco físico", f"{c.coverage_of_physical_percent:.2f}%" if c.coverage_of_physical_percent is not None else "No calculable"),
        ("Integridad", "Correcta en bytes verificados" if c.integrity_ok is True else ("Falló" if c.integrity_ok is False else "No probada")),
        ("Desplazamientos lógicos discrepantes", json.dumps(c.mismatched_offsets[:20], ensure_ascii=False)),
        ("Nota", c.note or "—"),
    ])
    assessment_rows = _rows([
        ("Clase medida", a.sd_speed_class), ("Aplicaciones", a.application_class),
        ("Riesgo de capacidad falsa", a.fake_risk), ("Cuello de botella", a.reader_bottleneck),
        ("Llenado estimado", _fmt(a.estimated_fill_hours, " h")),
    ])
    product_rows = _rows([("Tipo", report.product.get("type", "—")), ("Marca / modelo indicado", f"{report.product.get('brand') or '—'} / {report.product.get('model') or '—'}"),
                          ("Promesa de velocidad", "Mínimo sostenido indicado" if report.product.get('speed_basis') == 'sustained' else "Hasta / máximo anunciado")])
    comparison = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in (row['metric'], _fmt(row['advertised'], ' '+row['unit']), _fmt(row['observed'], ' '+row['unit']), _fmt(row['percent'], '%'), row['note'])) + '</tr>' for row in report.product_comparison)
    online = report.online_lookup
    references = ''.join(f"<li>{html.escape(row['title'])} — {html.escape(row['match'])}<br>{html.escape(row['url'])}<p>{html.escape('Referencia en extracto: ' + json.dumps(row['reference_speeds'], ensure_ascii=False)) if row.get('reference_speeds') else ''}</p>{''.join('<p>' + html.escape(warning) + '</p>' for warning in row.get('spec_disagreements', []))}</li>" for row in online.get('candidates', []))
    product_html = f"<h2>Producto anunciado</h2><table>{product_rows}</table><table><tr><th>Dato</th><th>Anunciado</th><th>Observado</th><th>Porcentaje</th><th>Interpretación</th></tr>{comparison}</table><h2>Referencias en Internet</h2><p>{html.escape(online.get('message', 'Sin consulta'))}</p><p>Consulta: {html.escape(online.get('checked_at', '—'))}</p><p>{html.escape(online.get('identity_warning', ''))}</p><ul>{references}</ul><p>{html.escape(online.get('note', 'Una referencia web no autentica esta unidad.'))}</p>"
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe MediaProbe</title>
<style>body{{font:15px system-ui,sans-serif;color:#18212b;max-width:980px;margin:36px auto;padding:0 24px}}h1{{color:#0b6b64}}h2{{border-bottom:2px solid #d8ebe8;padding-bottom:6px}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #ddd}}th{{width:34%;color:#425466}}.score{{font-size:38px;font-weight:700;color:#0b6b64}}.warn{{background:#fff4df;padding:12px 18px;border-left:5px solid #d58b00}}.foot{{color:#596875;font-size:13px}}svg{{width:100%;height:auto}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>MediaProbe Portable</h1><p>Informe técnico del {html.escape(report.created_at)} · {html.escape(report.mode)}</p>
<p class="score">{a.score if a.score is not None else '—'}/100</p><p><strong>{html.escape(a.verdict)}</strong><br>Confianza: {html.escape(a.confidence)}</p>
{product_html}<h2>Identificación y capacidad</h2><table>{device_rows}</table>
<h2>Registros SD/MMC</h2><table>{register_rows}</table>
<h2>Rendimiento</h2><table>{speed_rows}</table>{_chart(report)}
<h2>Capacidad e integridad</h2><table>{capacity_rows}</table>
<h2>Evaluación</h2><table>{assessment_rows}</table><h2>Marcación impresa</h2><ul>{claimed}</ul>
<h2>Recomendaciones</h2><ul>{recs}</ul><div class="warn"><strong>Advertencias</strong><ul>{warnings}</ul></div>
<p class="foot">La puntuación resume rendimiento y porcentaje del volumen verificado; no certifica marca, garantía, resistencia, logotipos SD ni sectores físicos no cubiertos. El método de archivos depende del lector y sistema operativo. Imprima esta página para obtener PDF.</p></body></html>'''


def export_report(report: ProbeReport, base_path: str | Path) -> list[Path]:
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    outputs = [base.with_suffix(".txt"), base.with_suffix(".json"), base.with_suffix(".html")]
    outputs[0].write_text(report_text(report), encoding="utf-8")
    outputs[1].write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    outputs[2].write_text(report_html(report), encoding="utf-8")
    return outputs
