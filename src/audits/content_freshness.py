"""
OE2 — Frecuencia de actualización y cumplimiento de transparencia (LAIP).

Responde a la pregunta auxiliar 2:
"¿Cuál es la frecuencia de actualización histórica de estos portales y el
nivel de disponibilidad de apartados de información pública (transparencia
y servicios)?"

Métricas:
- Total de snapshots en Wayback Machine (2021-2026)
- Snapshots por año (serie temporal)
- Fecha del primer y último snapshot
- Intervalo promedio entre snapshots (días)
- Última modificación detectada en HTML (meta + Last-Modified header)
- % de indicadores LAIP encontrados (Art. 10 del Decreto 57-2008):
    transparencia, presupuesto, compras, personal, servicios, estructura, contacto
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from datetime import datetime
from typing import Dict, Any, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config.settings import (
    WAYBACK_CDX_ENDPOINT, ANALISIS_DESDE, ANALISIS_HASTA,
    HTTP_TIMEOUT, USER_AGENT, INDICADORES_LAIP,
)
from src.scraper.fetcher import FetchResult
from src.logger import get_logger

log = get_logger(__name__)


def _normalizar_texto(s: str) -> str:
    """Quita acentos y baja a minúsculas para matching robusto."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


# ---------- Wayback Machine ----------

def _consultar_wayback(url: str) -> Dict[str, Any]:
    """
    Llama a la CDX API del Internet Archive.
    Devuelve métricas agregadas sobre la frecuencia de actualización del portal.
    """
    parsed = urlparse(url)
    dominio = parsed.netloc or url

    params = {
        "url": dominio,
        "from": ANALISIS_DESDE,
        "to": ANALISIS_HASTA,
        "output": "json",
        "fl": "timestamp,statuscode,digest",
        "collapse": "digest",  # importante: agrupa por contenido idéntico
        "limit": 5000,
    }

    out: Dict[str, Any] = {
        "wayback_consultado": True,
        "snapshots_total": 0,
        "snapshots_unicos": 0,
        "primer_snapshot": None,
        "ultimo_snapshot": None,
        "snapshots_por_anio": {},
        "intervalo_medio_dias": None,
        "intervalo_mediana_dias": None,
        "dias_desde_ultima_actualizacion": None,
        "actualizaciones_unicas_2025_2026": 0,
        "wayback_error": None,
    }

    try:
        resp = requests.get(
            WAYBACK_CDX_ENDPOINT,
            params=params,
            timeout=HTTP_TIMEOUT * 2,  # CDX puede ser lento
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            out["wayback_error"] = f"HTTP {resp.status_code}"
            return out

        data = resp.json()
        if not data or len(data) < 2:
            return out  # Sin snapshots

        # data[0] son headers, data[1:] son filas
        filas = data[1:]
        out["snapshots_total"] = len(filas)
        out["snapshots_unicos"] = len(set(f[2] for f in filas if len(f) >= 3))

        timestamps: List[datetime] = []
        por_anio: Dict[str, int] = {}
        unicos_recientes = 0

        for fila in filas:
            ts_str = fila[0]
            try:
                ts = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
                timestamps.append(ts)
                anio = ts.year
                por_anio[str(anio)] = por_anio.get(str(anio), 0) + 1
                if anio >= 2025:
                    unicos_recientes += 1
            except ValueError:
                continue

        if timestamps:
            timestamps.sort()
            out["primer_snapshot"] = timestamps[0].isoformat()
            out["ultimo_snapshot"] = timestamps[-1].isoformat()
            out["snapshots_por_anio"] = dict(sorted(por_anio.items()))
            out["actualizaciones_unicas_2025_2026"] = unicos_recientes

            ahora = datetime.utcnow()
            out["dias_desde_ultima_actualizacion"] = (ahora - timestamps[-1]).days

            if len(timestamps) >= 2:
                intervalos = [
                    (timestamps[i] - timestamps[i-1]).days
                    for i in range(1, len(timestamps))
                ]
                out["intervalo_medio_dias"] = round(statistics.mean(intervalos), 1)
                out["intervalo_mediana_dias"] = round(statistics.median(intervalos), 1)

    except requests.exceptions.RequestException as ex:
        log.warning("Error Wayback para %s: %s", url, ex)
        out["wayback_error"] = str(ex)
    except ValueError as ex:
        log.warning("Error JSON Wayback para %s: %s", url, ex)
        out["wayback_error"] = f"JSON inválido: {ex}"
    except Exception as ex:
        log.warning("Error inesperado Wayback para %s: %s", url, ex)
        out["wayback_error"] = str(ex)

    return out


# ---------- Indicadores LAIP en el HTML ----------

def _analizar_indicadores_laip(html: str) -> Dict[str, Any]:
    """
    Busca patrones de transparencia (LAIP) en HTML.
    Por cada categoría busca:
      a) Texto visible que contenga las palabras clave.
      b) Enlaces (a[href]) que contengan las palabras clave en su texto o URL.
    """
    if not html:
        return {
            "laip_indicadores_encontrados": 0,
            "laip_indicadores_total": len(INDICADORES_LAIP),
            "laip_pct_cumplimiento": 0.0,
            **{f"laip_{cat}": False for cat in INDICADORES_LAIP},
        }

    soup = BeautifulSoup(html, "lxml")
    texto_pagina = _normalizar_texto(soup.get_text(separator=" "))
    enlaces = soup.find_all("a", href=True)
    enlaces_norm = [
        (_normalizar_texto(a.get_text(strip=True)), _normalizar_texto(a["href"]))
        for a in enlaces
    ]

    encontrados: Dict[str, bool] = {}
    for categoria, palabras in INDICADORES_LAIP.items():
        palabras_norm = [_normalizar_texto(p) for p in palabras]
        # En texto visible
        en_texto = any(p in texto_pagina for p in palabras_norm)
        # En enlaces (texto del enlace o URL del enlace)
        en_enlaces = any(
            any(p in t or p in h for p in palabras_norm)
            for t, h in enlaces_norm
        )
        encontrados[categoria] = en_texto or en_enlaces

    n_encontrados = sum(1 for v in encontrados.values() if v)
    total = len(INDICADORES_LAIP)
    pct = round(n_encontrados / total * 100, 2) if total else 0.0

    out = {
        "laip_indicadores_encontrados": n_encontrados,
        "laip_indicadores_total": total,
        "laip_pct_cumplimiento": pct,
    }
    out.update({f"laip_{k}": v for k, v in encontrados.items()})
    return out


# ---------- Última modificación del HTML ----------

def _detectar_ultima_modificacion(html: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Intenta inferir la fecha de última actualización del contenido a partir de:
    - Header HTTP Last-Modified
    - <meta name="last-modified">
    - <meta property="article:modified_time">
    - <time datetime="...">
    - Patrones tipo "fecha: dd/mm/yyyy" en el HTML
    """
    out = {
        "ultima_modificacion_header": None,
        "ultima_modificacion_meta": None,
        "fechas_detectadas_html": [],
    }

    # Header
    lm = headers.get("Last-Modified") or headers.get("last-modified")
    if lm:
        out["ultima_modificacion_header"] = lm

    if not html:
        return out

    soup = BeautifulSoup(html, "lxml")

    metas = [
        soup.find("meta", attrs={"name": re.compile("modified", re.I)}),
        soup.find("meta", attrs={"property": re.compile("modified", re.I)}),
        soup.find("meta", attrs={"name": "date"}),
    ]
    for m in metas:
        if m and m.get("content"):
            out["ultima_modificacion_meta"] = m["content"]
            break

    # <time datetime>
    tiempos = soup.find_all("time", datetime=True)
    fechas = [t.get("datetime") for t in tiempos[:10]]

    # Patrones simples en texto
    texto = soup.get_text(separator=" ")
    patrones = re.findall(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b", texto)
    fechas.extend(patrones[:5])

    out["fechas_detectadas_html"] = fechas
    return out


# ---------- API pública ----------

def auditar_freshness(fetch_result: FetchResult, *, consultar_wayback: bool = True) -> Dict[str, Any]:
    """
    Devuelve dict con métricas de frescura y transparencia.
    """
    url = fetch_result.url_final or fetch_result.url_original
    out: Dict[str, Any] = {"url_audit_freshness": url}

    # 1) LAIP
    out.update(_analizar_indicadores_laip(fetch_result.contenido_html or ""))

    # 2) Última modificación
    out.update(_detectar_ultima_modificacion(
        fetch_result.contenido_html or "",
        fetch_result.headers or {},
    ))

    # 3) Wayback
    if consultar_wayback and url:
        out.update(_consultar_wayback(url))

    # 4) Score local de frescura/transparencia (0-100)
    out["score_local_freshness"] = _calcular_score(out)
    return out


def _calcular_score(m: Dict[str, Any]) -> int:
    """
    Pesos:
      - % LAIP * 0.5   (max 50 puntos)
      - Snapshots ≥ 12 (uno por mes promedio): 20
                  ≥ 6: 12
                  ≥ 3: 6
      - Última actualización wayback ≤ 90 días: 20
                                    ≤ 365 días: 10
      - Actualizaciones únicas 2025-2026 ≥ 6: 10
                                        ≥ 3: 5
    """
    s = 0
    pct = m.get("laip_pct_cumplimiento", 0.0)
    s += int(pct * 0.5)

    snaps = m.get("snapshots_unicos", 0) or 0
    if snaps >= 12:
        s += 20
    elif snaps >= 6:
        s += 12
    elif snaps >= 3:
        s += 6

    dias = m.get("dias_desde_ultima_actualizacion")
    if dias is not None:
        if dias <= 90:
            s += 20
        elif dias <= 365:
            s += 10

    rec = m.get("actualizaciones_unicas_2025_2026", 0) or 0
    if rec >= 6:
        s += 10
    elif rec >= 3:
        s += 5

    return min(s, 100)
