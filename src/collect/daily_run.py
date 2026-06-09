"""
Orquesta UNA corrida de recolección sobre los portales con URL.

Cada corrida produce un snapshot por portal (1 fila con run_id/run_ts) y lo
añade al JSONL del mes vía `store.append_snapshots`.

Diferencias deliberadas respecto a la auditoría ad-hoc de main.py:
- PageSpeed apagado por defecto: el muestreo intradía mide la latencia real
  del servidor (TTFB / tiempo total) que es lo que varía con la hora; PageSpeed
  es lento (~20-40 s/URL) y mide desde Google, no aporta al objetivo del muestreo.
- Wayback fuera del ciclo: la frecuencia histórica no cambia entre corridas del
  mismo día; se consulta una sola vez en la consolidación.
- No abre navegador, no genera reportes: es un job desatendido para Actions.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import TZ_GUATEMALA, REQUEST_DELAY
from src.portales import cargar_municipios, filtrar_municipios
from src.scraper.fetcher import fetch
from src.audits.performance import auditar_performance
from src.audits.security import auditar_security
from src.audits.content_freshness import auditar_freshness
from src.collect.store import append_snapshots
from src.logger import get_logger

log = get_logger(__name__)

# Campos que copiamos de cada auditoría al snapshot (el resto del esquema lo
# rellena store.proyectar_snapshot con None).
_CAMPOS_PERF = ("tiene_viewport", "score_local_performance")
_CAMPOS_SEC = (
    "redirige_a_https", "ssl_ok", "ssl_estado", "ssl_self_signed",
    "ssl_dias_restantes", "ssl_tls_version", "header_hsts", "header_csp",
    "header_x_frame_options", "header_referrer_policy", "score_local_security",
)
_CAMPOS_LAIP = (
    "laip_transparencia", "laip_presupuesto", "laip_compras", "laip_personal",
    "laip_servicios", "laip_estructura", "laip_contacto", "laip_pct_cumplimiento",
)


def _auditar_portal(
    portal: Dict[str, Any],
    run_meta: Dict[str, Any],
    *,
    usar_pagespeed: bool = False,
) -> Dict[str, Any]:
    """Audita un portal y devuelve un snapshot (dict con claves del esquema)."""
    url = portal.get("url")
    reg: Dict[str, Any] = {
        **run_meta,
        "municipio": portal.get("nombre"),
        "departamento": portal.get("departamento"),
        "codigo_ine": portal.get("codigo_ine"),
        "cabecera": bool(portal.get("cabecera", False)),
        "tipo_portal": portal.get("tipo_portal", "oficial"),
        "url": url,
    }

    fres = fetch(url)
    reg.update({
        "reachable": fres.reachable,
        "status_code": fres.status_code,
        "error_fetch": fres.error,
        "ttfb_ms": fres.ttfb_ms,
        "tiempo_total_ms": fres.tiempo_total_ms,
        "tamanio_kb": round(fres.tamanio_bytes / 1024, 2) if fres.tamanio_bytes else None,
        "https": fres.https,
    })

    # Si no respondió ni dejó HTML, no hay nada más que medir (queda como caída).
    if not fres.reachable and not fres.contenido_html:
        return reg

    try:
        perf = auditar_performance(fres, usar_pagespeed=usar_pagespeed)
        reg.update({k: perf.get(k) for k in _CAMPOS_PERF})
    except Exception as ex:
        log.warning("performance %s: %s", url, ex)

    try:
        sec = auditar_security(fres)
        reg.update({k: sec.get(k) for k in _CAMPOS_SEC})
    except Exception as ex:
        log.warning("security %s: %s", url, ex)

    try:
        fr = auditar_freshness(fres, consultar_wayback=False)
        reg.update({k: fr.get(k) for k in _CAMPOS_LAIP})
    except Exception as ex:
        log.warning("freshness %s: %s", url, ex)

    return reg


def ejecutar_corrida(
    *,
    usar_pagespeed: bool = False,
    max_portales: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Ejecuta una corrida completa sobre los portales con URL del Suroccidente
    (config/municipios.yaml) y persiste los snapshots. Devuelve un resumen con
    run_id, conteos y la ruta del JSONL.
    """
    ahora = datetime.now(TZ_GUATEMALA)
    run_id = f"{ahora.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_meta = {
        "run_id": run_id,
        "run_ts": ahora.isoformat(timespec="seconds"),
        "run_date": ahora.strftime("%Y-%m-%d"),
        "run_hour": ahora.hour,
    }

    municipios = cargar_municipios()  # Suroccidente fijo
    portales = filtrar_municipios(municipios, solo_con_url=True)
    if max_portales:
        portales = portales[:max_portales]

    log.info(
        "Corrida %s — %d portales (Suroccidente) hora_GT=%02d",
        run_id, len(portales), ahora.hour,
    )

    registros: List[Dict[str, Any]] = []
    for p in portales:
        try:
            registros.append(_auditar_portal(p, run_meta, usar_pagespeed=usar_pagespeed))
        except Exception as ex:
            log.exception("Fallo auditando %s: %s", p.get("nombre"), ex)
            registros.append({**run_meta, "municipio": p.get("nombre"),
                              "url": p.get("url"), "reachable": False,
                              "error_fetch": f"fatal: {ex}"})
        time.sleep(REQUEST_DELAY)

    jsonl = append_snapshots(registros)
    n_ok = sum(1 for r in registros if r.get("reachable"))

    resumen = {
        "run_id": run_id,
        "run_ts": run_meta["run_ts"],
        "run_hour": ahora.hour,
        "n_portales": len(registros),
        "n_exitosos": n_ok,
        "n_caidos": len(registros) - n_ok,
        "jsonl": str(jsonl) if jsonl else None,
    }
    log.info("Corrida %s lista: %d/%d alcanzables", run_id, n_ok, len(registros))
    return resumen
