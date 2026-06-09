"""
Entrypoint de la recolección diaria — lo invoca el runner de GitHub Actions.

El estudio se limita a la Región VI Suroccidente (config/municipios.yaml).
La recolección NUNCA usa la lista nacional.

Uso:
    python run_daily.py                 # corrida normal (Suroccidente, sin PageSpeed)
    python run_daily.py --rebuild-db    # además reconstruye el SQLite local
    python run_daily.py --max 3         # solo 3 portales (debug)
    python run_daily.py --pagespeed     # incluir PageSpeed (lento)

Imprime un resumen JSON por stdout (lo aprovecha el workflow para el log).
"""
from __future__ import annotations

import argparse
import json
import sys

from src.collect.daily_run import ejecutar_corrida
from src.collect.store import rebuild_sqlite, resumen_cobertura


def main() -> int:
    ap = argparse.ArgumentParser(description="Corrida de recolección diaria e-Gov")
    ap.add_argument("--pagespeed", action="store_true",
                    help="Incluir PageSpeed Insights (lento; off por defecto)")
    ap.add_argument("--max", type=int, default=None,
                    help="Limitar número de portales (debug)")
    ap.add_argument("--rebuild-db", action="store_true",
                    help="Reconstruir data/egov.db desde los JSONL tras la corrida")
    args = ap.parse_args()

    resumen = ejecutar_corrida(
        usar_pagespeed=args.pagespeed,
        max_portales=args.max,
    )

    if args.rebuild_db:
        resumen["sqlite_filas"] = rebuild_sqlite()

    resumen["cobertura_acumulada"] = resumen_cobertura()
    print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
