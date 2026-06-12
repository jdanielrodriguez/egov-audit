"""
Carga y expansión de la lista de portales desde los YAML de configuración.

Lógica compartida entre `main.py` (auditoría ad-hoc / reportes) y
`src/collect/` (recolección diaria), para no duplicar el manejo de los dos
formatos de YAML (url simple vs lista de urls por tipo).
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Optional

import yaml

from config.settings import MUNICIPIOS_YAML, URLS_OVERRIDES_JSON
from src.logger import get_logger

log = get_logger(__name__)


def _clave_municipio(m: Dict[str, Any]) -> str:
    """Clave estable para casar un municipio con su override (código INE o nombre)."""
    return str(m.get("codigo_ine") or m.get("nombre") or "")


def _cargar_overrides() -> Dict[str, Any]:
    """Lee config/urls_overrides.json (URLs descubiertas/reemplazadas). {} si no existe."""
    if not URLS_OVERRIDES_JSON.exists():
        return {}
    try:
        with open(URLS_OVERRIDES_JSON, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError) as ex:
        log.warning("No se pudo leer %s: %s", URLS_OVERRIDES_JSON.name, ex)
        return {}


def _aplicar_overrides(municipios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Fusiona los overrides sobre la lista del YAML SIN modificar el archivo.
    Un override (por código INE / nombre) define la URL oficial vigente del
    municipio: gana sobre lo que diga el YAML. El municipios.yaml curado queda
    intacto en disco.
    """
    overrides = _cargar_overrides()
    if not overrides:
        return municipios
    aplicados = 0
    for m in municipios:
        ov = overrides.get(_clave_municipio(m))
        if ov and ov.get("url"):
            m["url"] = ov["url"]
            m["urls"] = None  # la URL oficial del override es la vigente
            m["_url_fuente"] = "override"
            aplicados += 1
    if aplicados:
        log.info("Aplicados %d overrides de URL sobre el catálogo", aplicados)
    return municipios


def cargar_municipios(aplicar_overrides: bool = True) -> List[Dict[str, Any]]:
    """
    Carga la lista de municipios del Suroccidente (config/municipios.yaml) y,
    por defecto, fusiona los overrides de URL (config/urls_overrides.json) que
    haya generado el workflow de actualización.
    """
    with open(MUNICIPIOS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    municipios = data.get("municipios", [])
    log.info("Municipios cargados desde %s", MUNICIPIOS_YAML.name)
    if aplicar_overrides:
        municipios = _aplicar_overrides(municipios)
    return municipios


def expandir_urls(entidad: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Expande una entidad (municipio o institución) en una o más URLs auditables.

    Soporta dos formatos en el YAML:

    Formato A (simple, retrocompatible):
        - nombre: X
          url: https://...

    Formato B (multi-URL):
        - nombre: X
          urls:
            - tipo: oficial
              url: https://...
            - tipo: transparencia_iap
              url: https://....iap.gob.gt
    """
    base = {k: v for k, v in entidad.items() if k not in ("url", "urls")}

    expansions: List[Dict[str, Any]] = []

    # Formato A: campo "url" simple
    if entidad.get("url"):
        expansions.append(
            {
                **base,
                "url": entidad["url"],
                "tipo_portal": entidad.get("tipo_portal", "oficial"),
            }
        )

    # Formato B: campo "urls" como lista
    urls_list = entidad.get("urls", [])
    if isinstance(urls_list, list):
        for item in urls_list:
            if isinstance(item, dict) and item.get("url"):
                expansions.append(
                    {
                        **base,
                        "url": item["url"],
                        "tipo_portal": item.get("tipo", "oficial"),
                    }
                )
            elif isinstance(item, str):
                expansions.append(
                    {
                        **base,
                        "url": item,
                        "tipo_portal": "oficial",
                    }
                )

    return expansions


def filtrar_municipios(
    municipios: List[Dict[str, Any]],
    *,
    departamento: Optional[str] = None,
    url: Optional[str] = None,
    tipo_portal: Optional[str] = None,
    solo_con_url: bool = True,
) -> List[Dict[str, Any]]:
    # Si se pasa una URL específica, ignorar todo y auditar solo esa
    if url:
        return [
            {
                "nombre": "URL ad-hoc",
                "departamento": "N/A",
                "url": url,
                "tipo_portal": "ad-hoc",
            }
        ]

    # Filtrar por departamento si se especifica
    objetivo = municipios
    if departamento:
        objetivo = [
            m
            for m in objetivo
            if m.get("departamento", "").lower() == departamento.lower()
        ]

    # Expandir cada entidad a una o más URLs auditables
    expandidas: List[Dict[str, Any]] = []
    for m in objetivo:
        expandidas.extend(expandir_urls(m))

    # Filtrar por tipo de portal si se especifica
    if tipo_portal:
        expandidas = [
            m
            for m in expandidas
            if m.get("tipo_portal", "").lower() == tipo_portal.lower()
        ]

    if solo_con_url:
        expandidas = [m for m in expandidas if m.get("url")]

    return expandidas
