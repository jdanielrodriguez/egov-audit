"""
Punto de entrada: orquesta todo el flujo de auditoría.

v2 (mayo 2026):
- Soporte para múltiples URLs por municipio (campo `urls:` además de `url:`)
- Filtros por tipo de portal (oficial, transparencia_iap, alternativa)
- Auditoría también de instituciones gubernamentales no municipales

Uso:
    python main.py --all
    python main.py --url https://www.muniquetzaltenango.gob.gt
    python main.py --departamento Quetzaltenango
    python main.py --all --solo performance
    python main.py --all --no-pagespeed --no-wayback
    python main.py --reporte
    python main.py --descubrir
    python main.py --descubrir-iap            # busca portales de transparencia IAP
    python main.py --tipo-portal oficial      # filtrar por tipo
    python main.py --instituciones            # auditar entidades gubernamentales no municipales
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Dict, Any, Optional

import yaml
import pandas as pd
from tqdm import tqdm

from config.settings import (
    RAW_DIR,
    PROCESSED_DIR,
    REQUEST_DELAY,
    CONFIG_DIR,
)
from src.portales import cargar_municipios, expandir_urls, filtrar_municipios
from src.scraper.fetcher import fetch
from src.scraper.discoverer import descubrir, descubrir_iap_transparencia
from src.audits.performance import auditar_performance
from src.audits.content_freshness import auditar_freshness
from src.audits.security import auditar_security
from src.reports.generator import generar_reporte
from src.reports.dashboard import generar_dashboard
from src.logger import get_logger

log = get_logger("main")

# Archivo opcional con instituciones gubernamentales no municipales
INSTITUCIONES_YAML = CONFIG_DIR / "instituciones.yaml"


def cargar_instituciones() -> List[Dict[str, Any]]:
    """Carga instituciones gubernamentales no municipales (si existe el YAML)."""
    if not INSTITUCIONES_YAML.exists():
        log.info(
            "No existe %s — se omiten instituciones no municipales", INSTITUCIONES_YAML
        )
        return []
    with open(INSTITUCIONES_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("instituciones", [])


def auditar_uno(
    municipio: Dict[str, Any],
    *,
    solo: Optional[str] = None,
    usar_pagespeed: bool = True,
    consultar_wayback: bool = True,
) -> Dict[str, Any]:
    """Ejecuta las auditorías para un municipio/institución. Devuelve dict consolidado."""
    nombre = municipio.get("nombre", "N/A")
    departamento = municipio.get("departamento", "N/A")
    url = municipio.get("url")
    tipo_portal = municipio.get("tipo_portal", "oficial")

    registro: Dict[str, Any] = {
        "municipio": nombre,
        "departamento": departamento,
        "url": url,
        "tipo_portal": tipo_portal,
        "codigo_ine": municipio.get("codigo_ine"),
        "timestamp_auditoria": pd.Timestamp.now().isoformat(),
    }

    if not url:
        registro["error_fetch"] = "Sin URL configurada"
        registro["reachable"] = False
        return registro

    log.info("→ Auditando %s [%s] (%s) %s", nombre, tipo_portal, departamento, url)

    # 1) Visita
    fres = fetch(url)
    registro.update(
        {
            "url_final": fres.url_final,
            "status_code": fres.status_code,
            "reachable": fres.reachable,
            "ttfb_ms": fres.ttfb_ms,
            "tiempo_total_ms": fres.tiempo_total_ms,
            "tamanio_bytes": fres.tamanio_bytes,
            "tamanio_kb": (
                round(fres.tamanio_bytes / 1024, 2) if fres.tamanio_bytes else None
            ),
            "redirecciones": fres.redirecciones,
            "https": fres.https,
            "error_fetch": fres.error,
        }
    )

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
            registro.update(
                auditar_freshness(fres, consultar_wayback=consultar_wayback)
            )
        except Exception as ex:
            log.exception("Error en freshness %s: %s", url, ex)
            registro["error_freshness"] = str(ex)

    if solo in (None, "security"):
        try:
            registro.update(auditar_security(fres))
        except Exception as ex:
            log.exception("Error en security %s: %s", url, ex)
            registro["error_security"] = str(ex)

    # Guardar JSON crudo individual
    safe_nombre = "".join(c if c.isalnum() else "_" for c in nombre)
    safe_dep = "".join(c if c.isalnum() else "_" for c in (departamento or "N_A"))
    safe_tipo = "".join(c if c.isalnum() else "_" for c in tipo_portal)
    raw_path = RAW_DIR / f"{safe_dep}_{safe_nombre}_{safe_tipo}.json"
    try:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=2, default=str)
    except Exception as ex:
        log.warning("No se pudo guardar JSON crudo: %s", ex)

    return registro


def ejecutar_descubrimiento(
    municipios: List[Dict[str, Any]],
    *,
    incluir_iap: bool = False,
) -> None:
    """Recorre municipios sin URL e intenta descubrirla. Si incluir_iap=True,
    también prueba portales de transparencia IAP."""

    def _tiene_url_oficial(m: Dict[str, Any]) -> bool:
        if m.get("url"):
            return True
        urls_list = m.get("urls", [])
        if isinstance(urls_list, list):
            for it in urls_list:
                if isinstance(it, dict):
                    if it.get("tipo", "oficial") == "oficial" and it.get("url"):
                        return True
                elif isinstance(it, str) and it:
                    return True
        return False

    sin_url = [m for m in municipios if not _tiene_url_oficial(m)]
    log.info(
        "Intentando descubrir URLs para %d municipios sin URL oficial", len(sin_url)
    )

    hallazgos = []
    for m in tqdm(sin_url, desc="Descubriendo"):
        # 1) URL oficial
        r = descubrir(m["nombre"], m.get("departamento"))
        if r:
            hallazgos.append(
                {
                    "municipio": m["nombre"],
                    "departamento": m.get("departamento"),
                    "tipo_portal": "oficial",
                    **r,
                }
            )

        # 2) Portal IAP de transparencia (opcional)
        if incluir_iap:
            r_iap = descubrir_iap_transparencia(m["nombre"], m.get("departamento"))
            if r_iap:
                hallazgos.append(
                    {
                        "municipio": m["nombre"],
                        "departamento": m.get("departamento"),
                        "tipo_portal": "transparencia_iap",
                        **r_iap,
                    }
                )

    if hallazgos:
        df = pd.DataFrame(hallazgos)
        out = PROCESSED_DIR / "descubrimiento_urls.csv"
        df.to_csv(out, index=False)
        log.info("Hallazgos guardados en %s (%d URLs encontradas)", out, len(hallazgos))
    else:
        log.info("No se descubrieron URLs nuevas.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auditoría e-Gov Suroccidente Guatemala"
    )
    parser.add_argument(
        "--all", action="store_true", help="Audita todos los municipios con URL"
    )
    parser.add_argument("--url", help="Audita una sola URL ad-hoc")
    parser.add_argument("--departamento", help="Filtra por departamento")
    parser.add_argument(
        "--tipo-portal",
        dest="tipo_portal",
        choices=["oficial", "transparencia_iap", "alternativa", "ad-hoc"],
        help="Filtra por tipo de portal",
    )
    parser.add_argument(
        "--solo",
        choices=["performance", "freshness", "security"],
        help="Ejecuta solo una de las auditorías",
    )
    parser.add_argument(
        "--no-pagespeed",
        action="store_true",
        help="Omitir consulta a Google PageSpeed Insights",
    )
    parser.add_argument(
        "--no-wayback", action="store_true", help="Omitir consulta a Wayback Machine"
    )
    parser.add_argument(
        "--reporte",
        action="store_true",
        help="Solo regenera el reporte desde resultados.csv",
    )
    parser.add_argument(
        "--descubrir",
        action="store_true",
        help="Intenta descubrir URLs de municipios sin URL configurada",
    )
    parser.add_argument(
        "--descubrir-iap",
        dest="descubrir_iap",
        action="store_true",
        help="Igual que --descubrir, pero también busca portales IAP de transparencia",
    )
    parser.add_argument(
        "--escribir",
        action="store_true",
        help=(
            "Con --descubrir: modo actualización del catálogo. Verifica las URLs "
            "en uso, reemplaza las que fallan (si encuentra alternativa), descubre "
            "las vacías y escribe config/urls_overrides.json + url_registro.json. "
            "NO genera CSV ni toca municipios.yaml. Sin esta flag, --descubrir solo "
            "genera el reporte CSV (comportamiento clásico)."
        ),
    )
    parser.add_argument(
        "--instituciones",
        action="store_true",
        help="Audita también instituciones gubernamentales (config/instituciones.yaml)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Limita el número de URLs a auditar (debug)",
    )
    args = parser.parse_args()

    municipios = cargar_municipios()
    log.info("Cargados %d municipios del Suroccidente", len(municipios))

    # Modo descubrimiento (no audita)
    if args.descubrir or args.descubrir_iap:
        if args.escribir:
            # Modo actualización del catálogo (workflow semanal): verifica/reemplaza/
            # descubre y escribe overrides + registro JSON; no genera CSV.
            from src.scraper.url_updater import actualizar_catalogo
            resumen = actualizar_catalogo(escribir=True)
            print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
        else:
            ejecutar_descubrimiento(municipios, incluir_iap=args.descubrir_iap)
        return 0

    # Modo regenerar reporte (no audita)
    if args.reporte:
        csv_path = PROCESSED_DIR / "resultados.csv"
        if not csv_path.exists():
            log.error("No existe %s. Corra primero la auditoría.", csv_path)
            return 1
        df = pd.read_csv(csv_path)
        out = generar_reporte(df)
        log.info("Reporte regenerado: %s", out)
        dash = generar_dashboard(df)
        log.info("Dashboard regenerado: %s", dash)
        return 0

    # Validar que se especificó qué auditar
    if not (args.all or args.url or args.departamento):
        parser.print_help()
        return 1

    # Construir lista objetivo
    objetivo = filtrar_municipios(
        municipios,
        departamento=args.departamento,
        url=args.url,
        tipo_portal=args.tipo_portal,
        solo_con_url=not bool(args.url),
    )

    # Si se pidió --instituciones, agregar también las instituciones gubernamentales
    if args.instituciones:
        instituciones = cargar_instituciones()
        log.info("Cargadas %d instituciones del YAML", len(instituciones))
        for inst in instituciones:
            objetivo.extend(expandir_urls(inst))

    if args.max:
        objetivo = objetivo[: args.max]

    log.info("Auditando %d URLs", len(objetivo))
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
            log.warning(
                "Interrumpido por el usuario. Guardando resultados parciales..."
            )
            break
        except Exception as ex:
            log.exception("Error catastrófico en %s: %s", m.get("nombre"), ex)
            resultados.append(
                {
                    "municipio": m.get("nombre"),
                    "departamento": m.get("departamento"),
                    "url": m.get("url"),
                    "tipo_portal": m.get("tipo_portal", "oficial"),
                    "error_general": str(ex),
                }
            )

        time.sleep(REQUEST_DELAY)

    # Consolidar
    df = pd.DataFrame(resultados)
    csv_path = PROCESSED_DIR / "resultados.csv"
    df.to_csv(csv_path, index=False)
    log.info(
        "Resultados consolidados: %s (%d filas, %d columnas)",
        csv_path,
        len(df),
        len(df.columns),
    )

    # Reporte Excel
    try:
        xlsx = generar_reporte(df)
        log.info("✅ Reporte Excel: %s", xlsx)
    except Exception as ex:
        log.exception("Error generando reporte: %s", ex)
        return 2

    # Dashboard HTML
    try:
        dash = generar_dashboard(df)
        log.info("✅ Dashboard HTML: %s", dash)
    except Exception as ex:
        log.exception("Error generando dashboard: %s", ex)

    return 0


if __name__ == "__main__":
    sys.exit(main())
