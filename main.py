"""
Punto de entrada: orquesta todo el flujo de auditoría.

Uso:
    python main.py --all
    python main.py --url https://www.muniquetzaltenango.gob.gt
    python main.py --departamento Quetzaltenango
    python main.py --all --solo performance
    python main.py --all --no-pagespeed --no-wayback   # más rápido / sin APIs externas
    python main.py --reporte    # solo regenera reportes desde data/processed/
    python main.py --descubrir  # intenta encontrar URLs faltantes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
import pandas as pd
from tqdm import tqdm

from config.settings import (
    MUNICIPIOS_YAML, RAW_DIR, PROCESSED_DIR, REQUEST_DELAY,
)
from src.scraper.fetcher import fetch
from src.scraper.discoverer import descubrir
from src.audits.performance import auditar_performance
from src.audits.content_freshness import auditar_freshness
from src.audits.security import auditar_security
from src.reports.generator import generar_reporte
from src.logger import get_logger

log = get_logger("main")


def cargar_municipios() -> List[Dict[str, Any]]:
    with open(MUNICIPIOS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("municipios", [])


def filtrar_municipios(
    municipios: List[Dict[str, Any]],
    *,
    departamento: Optional[str] = None,
    url: Optional[str] = None,
    solo_con_url: bool = True,
) -> List[Dict[str, Any]]:
    out = municipios
    if departamento:
        out = [m for m in out if m.get("departamento", "").lower() == departamento.lower()]
    if url:
        out = [{"nombre": "URL ad-hoc", "departamento": "N/A", "url": url}]
    if solo_con_url:
        out = [m for m in out if m.get("url")]
    return out


def auditar_uno(
    municipio: Dict[str, Any],
    *,
    solo: Optional[str] = None,
    usar_pagespeed: bool = True,
    consultar_wayback: bool = True,
) -> Dict[str, Any]:
    """Ejecuta las auditorías para un municipio. Devuelve dict consolidado."""
    nombre = municipio.get("nombre", "N/A")
    departamento = municipio.get("departamento", "N/A")
    url = municipio.get("url")

    registro: Dict[str, Any] = {
        "municipio": nombre,
        "departamento": departamento,
        "url": url,
        "timestamp_auditoria": pd.Timestamp.now().isoformat(),
    }

    if not url:
        registro["error_fetch"] = "Sin URL configurada"
        registro["reachable"] = False
        return registro

    log.info("→ Auditando %s (%s) %s", nombre, departamento, url)

    # 1) Visita
    fres = fetch(url)
    registro.update({
        "url_final": fres.url_final,
        "status_code": fres.status_code,
        "reachable": fres.reachable,
        "ttfb_ms": fres.ttfb_ms,
        "tiempo_total_ms": fres.tiempo_total_ms,
        "tamanio_bytes": fres.tamanio_bytes,
        "tamanio_kb": round(fres.tamanio_bytes / 1024, 2) if fres.tamanio_bytes else None,
        "redirecciones": fres.redirecciones,
        "https": fres.https,
        "error_fetch": fres.error,
    })

    if not fres.reachable and not fres.contenido_html:
        log.warning("  No alcanzable: %s", fres.error)
        return registro

    # 2) Auditorías
    if solo in (None, "performance"):
        try:
            registro.update(auditar_performance(fres, usar_pagespeed=usar_pagespeed))
        except Exception as ex:
            log.exception("Error en performance %s: %s", url, ex)
            registro["error_performance"] = str(ex)

    if solo in (None, "freshness"):
        try:
            registro.update(auditar_freshness(fres, consultar_wayback=consultar_wayback))
        except Exception as ex:
            log.exception("Error en freshness %s: %s", url, ex)
            registro["error_freshness"] = str(ex)

    if solo in (None, "security"):
        try:
            registro.update(auditar_security(fres))
        except Exception as ex:
            log.exception("Error en security %s: %s", url, ex)
            registro["error_security"] = str(ex)

    # Guardar JSON crudo individual (sanitizar nombre y departamento)
    safe_nombre = "".join(c if c.isalnum() else "_" for c in nombre)
    safe_dep = "".join(c if c.isalnum() else "_" for c in (departamento or "N_A"))
    raw_path = RAW_DIR / f"{safe_dep}_{safe_nombre}.json"
    try:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=2, default=str)
    except Exception as ex:
        log.warning("No se pudo guardar JSON crudo: %s", ex)

    return registro


def ejecutar_descubrimiento(municipios: List[Dict[str, Any]]) -> None:
    """Recorre municipios sin URL e intenta descubrirla."""
    sin_url = [m for m in municipios if not m.get("url")]
    log.info("Intentando descubrir URLs para %d municipios sin URL configurada", len(sin_url))

    hallazgos = []
    for m in tqdm(sin_url, desc="Descubriendo"):
        r = descubrir(m["nombre"])
        if r:
            hallazgos.append({
                "municipio": m["nombre"],
                "departamento": m.get("departamento"),
                **r,
            })

    if hallazgos:
        df = pd.DataFrame(hallazgos)
        out = PROCESSED_DIR / "descubrimiento_urls.csv"
        df.to_csv(out, index=False)
        log.info("Hallazgos guardados en %s (%d URLs encontradas)", out, len(hallazgos))
    else:
        log.info("No se descubrieron URLs nuevas.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría e-Gov Suroccidente Guatemala")
    parser.add_argument("--all", action="store_true", help="Audita todos los municipios con URL")
    parser.add_argument("--url", help="Audita una sola URL ad-hoc")
    parser.add_argument("--departamento", help="Filtra por departamento")
    parser.add_argument("--solo", choices=["performance", "freshness", "security"],
                        help="Ejecuta solo una de las auditorías")
    parser.add_argument("--no-pagespeed", action="store_true",
                        help="Omitir consulta a Google PageSpeed Insights")
    parser.add_argument("--no-wayback", action="store_true",
                        help="Omitir consulta a Wayback Machine")
    parser.add_argument("--reporte", action="store_true",
                        help="Solo regenera el reporte desde resultados.csv")
    parser.add_argument("--descubrir", action="store_true",
                        help="Intenta descubrir URLs de municipios sin URL configurada")
    parser.add_argument("--max", type=int, default=None,
                        help="Limita el número de municipios a auditar (debug)")
    args = parser.parse_args()

    municipios = cargar_municipios()
    log.info("Cargados %d municipios del YAML", len(municipios))

    if args.descubrir:
        ejecutar_descubrimiento(municipios)
        return 0

    if args.reporte:
        csv_path = PROCESSED_DIR / "resultados.csv"
        if not csv_path.exists():
            log.error("No existe %s. Corra primero la auditoría.", csv_path)
            return 1
        df = pd.read_csv(csv_path)
        out = generar_reporte(df)
        log.info("Reporte regenerado: %s", out)
        return 0

    if not (args.all or args.url or args.departamento):
        parser.print_help()
        return 1

    objetivo = filtrar_municipios(
        municipios,
        departamento=args.departamento,
        url=args.url,
        solo_con_url=not bool(args.url),
    )
    if args.max:
        objetivo = objetivo[: args.max]

    log.info("Auditando %d municipios", len(objetivo))
    if not objetivo:
        log.warning("Nada que auditar.")
        return 0

    resultados: List[Dict[str, Any]] = []
    for m in tqdm(objetivo, desc="Auditando"):
        try:
            r = auditar_uno(
                m,
                solo=args.solo,
                usar_pagespeed=not args.no_pagespeed,
                consultar_wayback=not args.no_wayback,
            )
            resultados.append(r)
        except KeyboardInterrupt:
            log.warning("Interrumpido por el usuario. Guardando resultados parciales...")
            break
        except Exception as ex:
            log.exception("Error catastrófico en %s: %s", m.get("nombre"), ex)
            resultados.append({
                "municipio": m.get("nombre"),
                "departamento": m.get("departamento"),
                "url": m.get("url"),
                "error_general": str(ex),
            })

        time.sleep(REQUEST_DELAY)

    # Consolidar
    df = pd.DataFrame(resultados)
    csv_path = PROCESSED_DIR / "resultados.csv"
    df.to_csv(csv_path, index=False)
    log.info("Resultados consolidados: %s (%d filas, %d columnas)",
             csv_path, len(df), len(df.columns))

    # Reporte
    try:
        xlsx = generar_reporte(df)
        log.info("✅ Reporte final: %s", xlsx)
    except Exception as ex:
        log.exception("Error generando reporte: %s", ex)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
