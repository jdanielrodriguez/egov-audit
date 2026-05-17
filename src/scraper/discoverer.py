"""
Descubre URLs candidatas para municipalidades sin URL conocida.

Estrategia (de menos a más invasiva):
1. Patrones comunes de dominio: muniNOMBRE.gob.gt, municipalidadnombre.gob.gt, etc.
2. Verificación HEAD a cada candidata.
3. Si se encuentra una con respuesta 200/3xx → se reporta como hallazgo.

Este módulo NO modifica el YAML directamente: genera un reporte que el
investigador puede revisar manualmente antes de incorporar.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from src.scraper.fetcher import fetch
from src.logger import get_logger

log = get_logger(__name__)


def _slug(s: str) -> str:
    """Convierte 'San Pedro Sacatepéquez' → 'sanpedrosacatepequez'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "", s).lower()
    return s


def candidatas_para(nombre_municipio: str) -> List[str]:
    """Genera URLs candidatas a partir del nombre del municipio."""
    slug = _slug(nombre_municipio)
    plantillas = [
        f"https://www.muni{slug}.gob.gt",
        f"https://muni{slug}.gob.gt",
        f"https://www.municipalidad{slug}.gob.gt",
        f"https://www.muni-{slug}.gob.gt",
        f"https://muni{slug}.com.gt",
        f"https://www.muni{slug}.com",
    ]
    # Eliminar duplicados conservando orden
    vistos = set()
    out = []
    for p in plantillas:
        if p not in vistos:
            out.append(p)
            vistos.add(p)
    return out


def descubrir(nombre_municipio: str) -> Optional[dict]:
    """
    Intenta cada URL candidata. Devuelve dict con la primera que responde
    o None si ninguna funciona.
    """
    log.info("Descubriendo URLs para: %s", nombre_municipio)
    for cand in candidatas_para(nombre_municipio):
        res = fetch(cand)
        if res.reachable and res.status_code and res.status_code < 400:
            log.info("  ✓ %s → %s (%d)", cand, res.url_final, res.status_code)
            return {
                "candidata_probada": cand,
                "url_funcional": res.url_final,
                "status_code": res.status_code,
            }
        else:
            log.debug("  ✗ %s → %s", cand, res.error or res.status_code)
    log.info("  No se encontró URL funcional para %s", nombre_municipio)
    return None
