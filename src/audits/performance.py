"""
OE1 — Auditoría de rendimiento y accesibilidad móvil.

Responde a la pregunta auxiliar 1:
"¿Cuál es el nivel de rendimiento técnico (tiempos de carga, optimización
móvil) y las principales barreras de accesibilidad que presentan estos
sitios web gubernamentales?"

Métricas:
- TTFB y tiempo total de descarga
- Peso bruto de la página (KB)
- Número de recursos referenciados (img, script, link)
- Presencia de meta viewport (responsividad móvil)
- Presencia de atributo lang (accesibilidad i18n)
- % de imágenes con atributo alt (accesibilidad WCAG)
- Forma adicional: si hay API key, PageSpeed Insights de Google para móvil

Devuelve un dict listo para serializar a JSON / CSV.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config.settings import (
    PAGESPEED_API_KEY, PAGESPEED_ENDPOINT, HTTP_TIMEOUT,
    UMBRALES_PERFORMANCE,
)
from src.scraper.fetcher import FetchResult
from src.logger import get_logger

log = get_logger(__name__)


# ---------- Análisis local del HTML ----------

def _analizar_html(html: str) -> Dict[str, Any]:
    """Parsea HTML y extrae métricas de rendimiento y accesibilidad."""
    if not html:
        return {
            "tiene_viewport": False,
            "tiene_lang": False,
            "lang_value": None,
            "tiene_charset": False,
            "imgs_total": 0,
            "imgs_con_alt": 0,
            "imgs_pct_con_alt": None,
            "n_scripts": 0,
            "n_scripts_externos": 0,
            "n_stylesheets": 0,
            "n_links_internos": 0,
            "n_links_externos": 0,
            "n_iframes": 0,
            "tiene_h1": False,
            "n_h1": 0,
            "tiene_favicon": False,
        }

    soup = BeautifulSoup(html, "lxml")

    # Viewport (responsive)
    viewport = soup.find("meta", attrs={"name": "viewport"})

    # Lang
    html_tag = soup.find("html")
    lang_value = html_tag.get("lang") if html_tag else None

    # Charset
    charset_meta = soup.find("meta", attrs={"charset": True}) or \
                   soup.find("meta", attrs={"http-equiv": lambda v: v and v.lower() == "content-type"})

    # Imágenes
    imgs = soup.find_all("img")
    imgs_con_alt = sum(1 for i in imgs if i.get("alt") is not None and i.get("alt").strip())
    imgs_pct = round(imgs_con_alt / len(imgs) * 100, 2) if imgs else None

    # Scripts
    scripts = soup.find_all("script")
    scripts_ext = [s for s in scripts if s.get("src")]

    # Stylesheets
    stylesheets = soup.find_all("link", rel=lambda r: r and "stylesheet" in r)

    # Links (a)
    a_tags = soup.find_all("a", href=True)
    internos = sum(1 for a in a_tags if a["href"].startswith(("/", "#"))
                   or (a["href"].startswith("http") is False))
    externos = sum(1 for a in a_tags if a["href"].startswith("http"))

    # H1
    h1s = soup.find_all("h1")

    # Favicon
    favicon = soup.find("link", rel=lambda r: r and ("icon" in r.lower()))

    return {
        "tiene_viewport": viewport is not None,
        "tiene_lang": lang_value is not None,
        "lang_value": lang_value,
        "tiene_charset": charset_meta is not None,
        "imgs_total": len(imgs),
        "imgs_con_alt": imgs_con_alt,
        "imgs_pct_con_alt": imgs_pct,
        "n_scripts": len(scripts),
        "n_scripts_externos": len(scripts_ext),
        "n_stylesheets": len(stylesheets),
        "n_links_internos": internos,
        "n_links_externos": externos,
        "n_iframes": len(soup.find_all("iframe")),
        "tiene_h1": len(h1s) > 0,
        "n_h1": len(h1s),
        "tiene_favicon": favicon is not None,
    }


# ---------- PageSpeed Insights (opcional) ----------

def _consultar_pagespeed(url: str, strategy: str = "mobile") -> Optional[Dict[str, Any]]:
    """
    Consulta la API de PageSpeed Insights (requiere API key).
    Retorna métricas Core Web Vitals o None si falla.
    """
    if not PAGESPEED_API_KEY:
        return None

    try:
        resp = requests.get(
            PAGESPEED_ENDPOINT,
            params={
                "url": url,
                "key": PAGESPEED_API_KEY,
                "strategy": strategy,
                "category": ["performance", "accessibility", "best-practices", "seo"],
            },
            timeout=60,
        )
        if resp.status_code != 200:
            log.warning("PageSpeed devolvió %d para %s", resp.status_code, url)
            return None

        data = resp.json()
        lh = data.get("lighthouseResult", {})
        categorias = lh.get("categories", {})
        audits = lh.get("audits", {})

        def _score(cat):
            c = categorias.get(cat, {})
            s = c.get("score")
            return round(s * 100, 1) if isinstance(s, (int, float)) else None

        def _audit(key, field="numericValue"):
            a = audits.get(key, {})
            return a.get(field)

        return {
            "pagespeed_score_performance": _score("performance"),
            "pagespeed_score_accessibility": _score("accessibility"),
            "pagespeed_score_best_practices": _score("best-practices"),
            "pagespeed_score_seo": _score("seo"),
            "pagespeed_fcp_ms": _audit("first-contentful-paint"),
            "pagespeed_lcp_ms": _audit("largest-contentful-paint"),
            "pagespeed_cls": _audit("cumulative-layout-shift"),
            "pagespeed_tbt_ms": _audit("total-blocking-time"),
            "pagespeed_speed_index": _audit("speed-index"),
            "pagespeed_strategy": strategy,
        }
    except requests.exceptions.RequestException as ex:
        log.warning("Error PageSpeed para %s: %s", url, ex)
        return None
    except Exception as ex:
        log.warning("Error inesperado PageSpeed para %s: %s", url, ex)
        return None


# ---------- Clasificaciones de calidad ----------

def _clasificar_ttfb(ttfb_ms: Optional[float]) -> str:
    if ttfb_ms is None:
        return "N/A"
    if ttfb_ms <= UMBRALES_PERFORMANCE["ttfb_bueno_ms"]:
        return "Bueno"
    if ttfb_ms <= UMBRALES_PERFORMANCE["ttfb_aceptable_ms"]:
        return "Aceptable"
    return "Deficiente"


def _clasificar_carga(t_ms: Optional[float]) -> str:
    if t_ms is None:
        return "N/A"
    t_s = t_ms / 1000
    if t_s <= UMBRALES_PERFORMANCE["carga_total_buena_s"]:
        return "Bueno"
    if t_s <= UMBRALES_PERFORMANCE["carga_total_aceptable_s"]:
        return "Aceptable"
    return "Deficiente"


def _clasificar_peso(bytes_: Optional[int]) -> str:
    if bytes_ is None:
        return "N/A"
    kb = bytes_ / 1024
    if kb <= UMBRALES_PERFORMANCE["peso_pagina_bueno_kb"]:
        return "Bueno"
    if kb <= UMBRALES_PERFORMANCE["peso_pagina_aceptable_kb"]:
        return "Aceptable"
    return "Deficiente"


# ---------- API pública ----------

def auditar_performance(fetch_result: FetchResult, *, usar_pagespeed: bool = True) -> Dict[str, Any]:
    """
    Devuelve un dict con todas las métricas de rendimiento y accesibilidad.
    El input es un FetchResult ya obtenido (no se vuelve a descargar).
    """
    out: Dict[str, Any] = {
        "url": fetch_result.url_final or fetch_result.url_original,
        "reachable": fetch_result.reachable,
        "error_fetch": fetch_result.error,
        "status_code": fetch_result.status_code,
        "ttfb_ms": fetch_result.ttfb_ms,
        "tiempo_total_ms": fetch_result.tiempo_total_ms,
        "tamanio_bytes": fetch_result.tamanio_bytes,
        "tamanio_kb": round(fetch_result.tamanio_bytes / 1024, 2) if fetch_result.tamanio_bytes else None,
        "redirecciones": fetch_result.redirecciones,
        "https": fetch_result.https,
    }

    # Clasificaciones
    out["clasificacion_ttfb"] = _clasificar_ttfb(fetch_result.ttfb_ms)
    out["clasificacion_carga"] = _clasificar_carga(fetch_result.tiempo_total_ms)
    out["clasificacion_peso"] = _clasificar_peso(fetch_result.tamanio_bytes)

    # Análisis HTML
    html_metrics = _analizar_html(fetch_result.contenido_html or "")
    out.update(html_metrics)

    # PageSpeed (opcional)
    if usar_pagespeed and fetch_result.reachable:
        url = fetch_result.url_final or fetch_result.url_original
        ps_mobile = _consultar_pagespeed(url, strategy="mobile")
        if ps_mobile:
            out.update(ps_mobile)

    # Score local agregado (0-100) basado en heurísticas, para casos sin PageSpeed
    score = _calcular_score_local(out)
    out["score_local_performance"] = score

    return out


def _calcular_score_local(m: Dict[str, Any]) -> int:
    """
    Score 0-100 cuando no hay PageSpeed disponible.
    Pesos:
      - Reachable: 20 puntos
      - HTTPS: 10
      - Viewport: 10
      - Lang: 5
      - Charset: 5
      - TTFB bueno: 15 (aceptable=8, deficiente=0)
      - Carga total buena: 15 (aceptable=8, deficiente=0)
      - Peso bueno: 10 (aceptable=5, deficiente=0)
      - imgs alt >= 80%: 10
    """
    if not m.get("reachable"):
        return 0
    s = 20
    if m.get("https"):
        s += 10
    if m.get("tiene_viewport"):
        s += 10
    if m.get("tiene_lang"):
        s += 5
    if m.get("tiene_charset"):
        s += 5

    cls = {"Bueno": 1.0, "Aceptable": 0.5, "Deficiente": 0.0, "N/A": 0.0}
    s += int(15 * cls[m.get("clasificacion_ttfb", "N/A")])
    s += int(15 * cls[m.get("clasificacion_carga", "N/A")])
    s += int(10 * cls[m.get("clasificacion_peso", "N/A")])

    pct = m.get("imgs_pct_con_alt")
    if pct is None:
        s += 5  # neutral si no hay imgs
    elif pct >= 80:
        s += 10
    elif pct >= 50:
        s += 5

    return min(s, 100)
