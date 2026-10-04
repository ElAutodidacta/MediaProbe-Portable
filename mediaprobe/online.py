"""Best-effort public product search. Search hits never certify the connected unit."""
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .models import DeviceInfo, utc_now

OFFICIAL = {
    "kingston": ("kingston.com",), "sandisk": ("sandisk.com", "westerndigital.com"),
    "western digital": ("westerndigital.com",), "samsung": ("samsung.com",),
    "lexar": ("lexar.com",), "transcend": ("transcend-info.com",),
    "crucial": ("crucial.com",), "micron": ("micron.com",), "kioxia": ("kioxia.com",),
    "toshiba": ("toshiba.com", "kioxia.com"), "adata": ("adata.com",),
    "pny": ("pny.com",), "patriot": ("patriotmemory.com",), "silicon power": ("silicon-power.com",),
    "teamgroup": ("teamgroupinc.com",), "seagate": ("seagate.com",),
    "corsair": ("corsair.com",), "sony": ("sony.com",), "xiaomi": ("mi.com", "xiaomi.com"),
}
GENERIC = {"usb", "disk", "device", "storage", "mass", "generic", "reader", "card", "flash", "sd", "scsi", "ata", "external"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in GENERIC}


def detected_brand(model: str) -> str:
    return next((brand for brand in OFFICIAL if brand in model.lower()), "")


def domain(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def reference_speeds(text: str) -> dict[str, float]:
    """Only explicit read/write pairs in a short source excerpt; never infer numbers."""
    match = re.search(r"(?:read\s*[/&]\s*write|lectura\s*[/&]\s*escritura)[^;.!?]{0,90}?(\d[\d.,]*)\s*/\s*(\d[\d.,]*)\s*MB\s*/\s*s", text, re.I)
    if not match:
        return {}
    def number(value: str) -> float:
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
            return float(value.replace(",", "").replace(".", ""))
        return float(value.replace(",", "."))
    try:
        read, write = number(match[1]), number(match[2])
        return {"read_mbps": read, "write_mbps": write} if 0 < read <= 100_000 and 0 < write <= 100_000 else {}
    except ValueError:
        return {}


def official_domain(url: str, brand: str = "") -> bool:
    domains = OFFICIAL.get(brand.lower(), ()) if brand else tuple(d for group in OFFICIAL.values() for d in group)
    host = domain(url)
    return any(host == d or host.endswith("." + d) for d in domains)


def public_https(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Solo se consultan fuentes HTTPS públicas.")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("Fuente con dirección privada o reservada rechazada.")
    return url


class _PublicRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, brand: str = ""):
        super().__init__()
        self.brand = brand

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl)
        if self.brand and not official_domain(newurl, self.brand):
            raise ValueError("La fuente redirige fuera de los dominios reconocidos del fabricante.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, timeout: float = 7, brand: str = "") -> str:
    public_https(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MediaProbe/1.2 (public product reference)", "Accept": "text/html,application/rss+xml,application/xml;q=0.9", "Accept-Encoding": "identity"})
    with urllib.request.build_opener(_PublicRedirect(brand)).open(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type == "application/pdf":
            raise ValueError("Esta fuente es PDF; ábrala desde su enlace para revisar la ficha. La consulta directa admite HTML.")
        data = response.read(1_500_001)
        if len(data) > 1_500_000:
            raise ValueError("Respuesta demasiado grande.")
        return data.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


class _DuckParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.current = None; self.capture = ""; self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); classes = a.get("class", "")
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            url = a.get("href", "")
            if url.startswith("//"): url = "https:" + url
            url = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("uddg", [url])[0]
            self.current = {"title": "", "url": url, "snippet": ""}; self.rows.append(self.current); self.capture = "title"; self.depth = 1
        elif self.current and ("result__snippet" in classes or "result-snippet" in classes):
            self.capture = "snippet"; self.depth = 1
        elif self.capture:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.capture:
            self.depth -= 1
            if self.depth <= 0: self.capture = ""

    def handle_data(self, data):
        if self.capture and self.current: self.current[self.capture] += data


def search(query: str) -> tuple[list[dict[str, str]], str]:
    # These public search interfaces may change or require CAPTCHA. No API key.
    errors = []
    for provider, url in (("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)),
                          ("DuckDuckGo HTML", "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query))):
        try:
            text = fetch(url)
            parser = _DuckParser(); parser.feed(text); rows = parser.rows
            if rows:
                return [{"title": row.get("title", "").strip()[:250], "url": row.get("url", "")[:2048], "snippet": re.sub(r"\s+", " ", row.get("snippet", "")).strip()[:600]} for row in rows[:10]], provider
            errors.append(provider + ": sin resultados o bloqueo del buscador")
        except Exception as exc:
            errors.append(provider + ": " + type(exc).__name__)
    raise OSError("; ".join(errors))


def rank_candidate(row: dict[str, str], product: dict[str, Any], device: DeviceInfo) -> dict[str, Any]:
    text = " ".join((row.get("title", ""), row.get("snippet", ""), urllib.parse.unquote(row.get("url", "")))).lower()
    brand = product.get("brand") or detected_brand(device.model)
    requested = tokens(product.get("model", ""))
    found = tokens(text)
    model_match = bool(requested) and requested.issubset(found)
    detected = tokens(device.model) - tokens(brand)
    hardware_match = bool(detected) and detected.issubset(found)
    brand_match = bool(brand) and brand.lower() in text
    official = official_domain(row.get("url", ""), brand)
    capacity = product.get("capacity_gb")
    capacities = [float(x.replace(",", ".")) * (1000 if unit.lower() == "tb" else 1)
                  for x, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(GB|TB)\b", text, re.I)]
    capacity_match = bool(capacity) and any(abs(x - capacity) < .5 for x in capacities)
    reasons = []
    if brand_match: reasons.append("marca mencionada")
    if model_match: reasons.append("modelo indicado mencionado")
    if hardware_match: reasons.append("modelo reportado mencionado (puede ser el lector)")
    if capacity_match: reasons.append("capacidad mencionada; puede listar varias variantes")
    if official: reasons.append("dominio del fabricante reconocido")
    score = 30 * model_match + 20 * hardware_match + 15 * brand_match + 10 * capacity_match + 25 * official
    useful = model_match or hardware_match or (brand_match and capacity_match)
    level = "Referencia oficial compatible con el modelo" if official and model_match and brand_match else ("Coincidencia posible; revisar variante" if useful else "Coincidencia débil")
    reference = reference_speeds(row.get("snippet", "")) if official and useful else {}
    disagreements = []
    for key, value in reference.items():
        announced = product.get(key)
        if announced and abs(announced - value) / value > .05:
            disagreements.append(f"{'Lectura' if key == 'read_mbps' else 'Escritura'}: indicó {announced:g} MB/s; el extracto menciona {value:g} MB/s. Revise generación y capacidad.")
    return {**row, "official": official, "match_points": score, "match": level, "reasons": reasons, "relevant": bool(useful), "reference_speeds": reference, "spec_disagreements": disagreements}


def lookup_product(product: dict[str, Any], device: DeviceInfo, source_url: str = "") -> dict[str, Any]:
    brand = product.get("brand") or detected_brand(device.model)
    reported_model = device.model
    for private in (device.serial, device.unique_id, device.cid, device.csd, device.ocr):
        if private and len(private) >= 4:
            reported_model = reported_model.replace(private, "")
    model = product.get("model") or (reported_model if tokens(reported_model) else "")
    capacity = product.get("capacity_gb")
    terms = [brand, model, f"{capacity:g}GB" if capacity else ""]
    if not model and product.get("type") != "Sin especificar":
        terms.append(product.get("type", ""))
    query = " ".join(x for x in terms if x).strip()
    result: dict[str, Any] = {"status": "pending", "checked_at": utc_now(), "query": query, "candidates": [], "connectivity": "unknown",
                             "note": "Las coincidencias web identifican referencias de producto; no autentican esta unidad. VID/PID y modelo pueden pertenecer al lector."}
    if not (model or brand):
        result.update(status="insufficient", message="Añada marca y modelo: el dispositivo reporta una identidad genérica.")
        return result
    try:
        if source_url:
            if not official_domain(source_url, brand):
                raise ValueError("La URL debe pertenecer a un dominio reconocido del fabricante indicado.")
            text = fetch(source_url, brand=brand.lower())
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
            clean = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
            clean = html.unescape(re.sub(r"<[^>]+>", " ", clean))
            clean = re.sub(r"\s+", " ", clean)
            # Keep only a short excerpt near the requested model, no entire article.
            position = clean.lower().find(model.lower()) if model else 0
            excerpt = clean[max(0, position):max(0, position) + 500]
            rows = [{"title": html.unescape(title.group(1)) if title else domain(source_url), "url": source_url, "snippet": excerpt}]
            provider = "Fuente oficial indicada"
        else:
            suffix = " site:" + OFFICIAL[brand.lower()][0] if brand.lower() in OFFICIAL else " storage specifications"
            rows, provider = search(query + suffix)
            if not any(rank_candidate(row, product, device)["relevant"] for row in rows):
                rows, provider = search(query + " specifications")
            if product.get("model") and tokens(reported_model) and tokens(reported_model) != tokens(model):
                detected_query = reported_model + " storage specifications"
                try:
                    extra, _ = search(detected_query)
                    known = {row["url"] for row in rows}
                    rows.extend(row for row in extra if row["url"] not in known)
                    result["detected_query"] = detected_query
                except OSError:
                    result["detected_query_note"] = "La consulta adicional del modelo detectado no estuvo disponible."
        candidates = [rank_candidate(row, product, device) for row in rows if row.get("url", "").startswith("https://")]
        candidates.sort(key=lambda x: x["match_points"], reverse=True)
        result.update(status="done", connectivity="online", provider=provider, candidates=candidates[:6],
                      message="Referencias encontradas; compruebe modelo, capacidad y generación." if any(x["relevant"] for x in candidates) else "Internet disponible, pero no se encontró una referencia suficientemente coincidente.")
        hardware_brand = detected_brand(device.model)
        if brand and hardware_brand and brand.lower() != hardware_brand:
            result["identity_warning"] = "La marca indicada difiere de la marca del modelo reportado. Puede ser identidad del lector/puente o una discrepancia del producto."
    except ValueError as exc:
        result.update(status="unavailable", message=str(exc), error="Fuente no consultable")
    except Exception as exc:
        result.update(status="unavailable", message="No se pudo consultar Internet: desconexión, proxy, tiempo agotado o bloqueo del buscador. Puede abrir la búsqueda manual.", error=type(exc).__name__ + ": " + str(exc)[:240])
    result["search_url"] = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    return result
