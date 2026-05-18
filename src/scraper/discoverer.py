"""
Descubre URLs candidatas para municipalidades sin URL conocida.

Estrategias (de menos a más invasiva):
1. Patrones comunes de dominio: muniNOMBRE.gob.gt, municipalidadnombre.gob.gt,
   muninombre-DEPARTAMENTO.gob.gt, etc.
2. Verificación HEAD/GET a cada candidata.
3. Validación adicional: confirmar que el contenido recuperado menciona
   el nombre del municipio (filtro contra falsos positivos como dominios
   estacionados o "404 amistosos").

Este módulo NO modifica el YAML directamente: genera un reporte CSV
que el investigador puede revisar manualmente antes de incorporar.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Dict, Any

from src.scraper.fetcher import fetch
from src.logger import get_logger

log = get_logger(__name__)


def _slug(s: str) -> str:
    """Convierte 'San Pedro Sacatepéquez' → 'sanpedrosacatepequez'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "", s).lower()
    return s


def _slug_guion(s: str) -> str:
    """Convierte 'San Pedro Sacatepéquez' → 'san-pedro-sacatepequez'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def candidatas_para(nombre_municipio: str, departamento: Optional[str] = None) -> List[str]:
    """Genera URLs candidatas a partir del nombre del municipio."""
    slug = _slug(nombre_municipio)
    slug_g = _slug_guion(nombre_municipio)
    dep_slug = _slug(departamento or "")

    plantillas = [
        # Patrón más común en Guatemala
        f"https://www.muni{slug}.gob.gt",
        f"https://muni{slug}.gob.gt",
        # Con guion
        f"https://www.muni-{slug_g}.gob.gt",
        f"https://muni-{slug_g}.gob.gt",
        # Con guion bajo
        f"https://www.muni_{slug_g}.gob.gt",
        f"https://muni_{slug_g}.gob.gt",
        # Patrón más común en Guatemala
        f"https://www.muni{slug}.com",
        f"https://muni{slug}.com",
        # Con guion
        f"https://www.muni-{slug_g}.com",
        f"https://muni-{slug_g}.com",
        # Con guion bajo
        f"https://www.muni_{slug_g}.com",
        f"https://muni_{slug_g}.com",
        # Variantes "municipalidad"
        f"https://www.municipalidad{slug}.gob.gt",
        f"https://municipalidad{slug}.gob.gt",
        # Variantes "municipalidad-"
        f"https://www.municipalidad-{slug}.gob.gt",
        f"https://municipalidad-{slug}.gob.gt",
        # Con sufijo de departamento (útil para municipios homónimos)
        *([
            f"https://www.muni{slug}{dep_slug}.gob.gt",
            f"https://www.muni{slug}-{dep_slug}.gob.gt",
            f"https://www.muni{slug}_{dep_slug}.gob.gt",
        ] if dep_slug else []),
        # TLDs alternativos
        f"https://muni{slug}.com.gt",
        f"https://www.muni{slug}.com.gt",
        f"https://www.muni{slug}.com",
        f"https://www.muni{slug}.br",
        f"https://www.muni{slug}.org",
    ]

    # Eliminar duplicados conservando orden
    vistos = set()
    out = []
    for p in plantillas:
        if p not in vistos:
            out.append(p)
            vistos.add(p)
    return out


def _confirma_identidad(html: str, nombre_municipio: str) -> bool:
    """
    Verifica que el HTML de la URL candidata menciona el nombre del municipio.
    Reduce falsos positivos (dominios estacionados, páginas genéricas, etc.).
    """
    if not html:
        return False
    nombre_norm = _slug(nombre_municipio)
    if len(nombre_norm) < 4:
        return True  # nombre muy corto, no podemos filtrar bien
    html_norm = _slug(html[:50000])
    return nombre_norm in html_norm


def descubrir(nombre_municipio: str, departamento: Optional[str] = None,
              *, validar_identidad: bool = True) -> Optional[Dict[str, Any]]:
    """
    Prueba cada URL candidata. Devuelve dict con la primera que responde
    y (opcional) confirma identidad por contenido, o None si nada funciona.
    """
    log.info("Descubriendo URLs para: %s (%s)", nombre_municipio, departamento or "")
    candidatas = candidatas_para(nombre_municipio, departamento)

    for cand in candidatas:
        res = fetch(cand)
        if not (res.reachable and res.status_code and res.status_code < 400):
            log.debug("  ✗ %s → %s", cand, res.error or res.status_code)
            continue

        identidad_ok = (
            _confirma_identidad(res.contenido_html or "", nombre_municipio)
            if validar_identidad else True
        )
        log.info("  %s %s → %s (%d) identidad=%s",
                 "✓" if identidad_ok else "?",
                 cand, res.url_final, res.status_code, identidad_ok)

        if identidad_ok:
            return {
                "candidata_probada": cand,
                "url_funcional": res.url_final,
                "status_code": res.status_code,
                "identidad_confirmada": True,
            }

    log.info("  No se encontró URL funcional con identidad confirmada para %s",
             nombre_municipio)
    return None
