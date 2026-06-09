"""
Análisis del estudio longitudinal: consolida los snapshots diarios y genera
los reportes finales (Excel con OE4 + dashboard HTML).

Flujo:
    data/daily/*.jsonl  →  consolidar (1 fila/portal)  →  data/consolidated/
                        →  Excel (con OE4) + dashboard HTML

La consolidación a un registro por portal es OBLIGATORIA antes de cualquier
análisis (evita la pseudoreplicación de tratar las corridas repetidas como
observaciones independientes).

Uso:
    python analizar.py                 # consolida + Excel + dashboard
    python analizar.py --wayback       # además consulta frescura histórica (red)
    python analizar.py --solo-consolidar
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from config.settings import CONSOLIDATED_DIR
from src.collect.store import cargar_snapshots_df, resumen_cobertura, rebuild_sqlite
from src.consolidate.consolidator import consolidar, a_formato_reporte
from src.reports.generator import generar_reporte
from src.reports.dashboard import generar_dashboard
from src.logger import get_logger

log = get_logger("analizar")


def main() -> int:
    ap = argparse.ArgumentParser(description="Consolidación y análisis longitudinal e-Gov")
    ap.add_argument("--wayback", action="store_true",
                    help="Consultar Wayback Machine por portal (frescura histórica; hace red)")
    ap.add_argument("--solo-consolidar", action="store_true",
                    help="Solo generar el CSV consolidado, sin Excel ni dashboard")
    args = ap.parse_args()

    df_snap = cargar_snapshots_df()
    if df_snap.empty:
        log.error("No hay snapshots en data/daily. Corré primero `python run_daily.py` "
                  "o esperá a que el workflow de recolección acumule datos.")
        return 1

    cobertura = resumen_cobertura()
    log.info("Cobertura acumulada: %s", cobertura)
    rebuild_sqlite()  # mantiene el índice SQLite local al día

    consol = consolidar(df_snap, enriquecer_wayback=args.wayback)
    if consol.empty:
        log.error("La consolidación resultó vacía.")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = CONSOLIDATED_DIR / f"consolidado_{ts}.csv"
    consol.to_csv(out_csv, index=False)
    consol.to_csv(CONSOLIDATED_DIR / "consolidado_latest.csv", index=False)
    log.info("Consolidado: %s (%d portales, %d columnas)", out_csv, len(consol), len(consol.columns))

    if args.solo_consolidar:
        return 0

    df_rep = a_formato_reporte(consol)
    try:
        xlsx = generar_reporte(df_rep, sufijo="_consolidado")
        log.info("✅ Excel: %s", xlsx)
    except Exception as ex:
        log.exception("Error generando Excel: %s", ex)
    try:
        dash = generar_dashboard(df_rep)
        log.info("✅ Dashboard: %s", dash)
    except Exception as ex:
        log.exception("Error generando dashboard: %s", ex)

    return 0


if __name__ == "__main__":
    sys.exit(main())
