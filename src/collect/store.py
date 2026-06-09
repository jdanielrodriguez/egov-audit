"""
Persistencia de los snapshots diarios.

Modelo de datos (decidido con el investigador):
- FUENTE DE VERDAD versionada en git: JSONL append-only, particionado por mes
  (`data/daily/YYYY-MM.jsonl`). Cada línea es un snapshot (un portal en una
  corrida). Append puro: nunca se reescribe el archivo → sin conflictos de
  merge cuando GitHub Actions commitea, y diff-friendly.
- ÍNDICE DERIVADO local: una base SQLite (`data/egov.db`) que se RECONSTRUYE
  desde los JSONL con `rebuild_sqlite()`. No se versiona (va en .gitignore);
  sirve para consultar con SQL cómodamente en la PC del investigador.

Por qué JSONL y no commitear el .db directamente: SQLite es binario y git no
hace delta eficiente de él; 5 commits/día durante meses inflarían el repo.
El JSONL crece de forma lineal y se diffea como texto.

`SNAPSHOT_FIELDS` es el contrato del esquema: cualquier registro se proyecta
a estas columnas antes de persistir, de modo que el JSONL es estable aunque
los módulos de auditoría agreguen campos internos.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pandas as pd

from config.settings import DAILY_DIR, SQLITE_DB
from src.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Esquema canónico del snapshot diario (orden de columnas = orden lógico)
# ---------------------------------------------------------------------------
SNAPSHOT_FIELDS: List[str] = [
    # Identidad de la corrida
    "run_id",
    "run_ts",            # ISO con offset -06:00 (hora de Guatemala)
    "run_date",          # fecha local GT (agrupa el "día guatemalteco")
    "run_hour",          # hora local GT 0-23 (para análisis noche/día)
    # Identidad del portal
    "municipio",
    "departamento",
    "codigo_ine",
    "cabecera",
    "tipo_portal",
    "url",
    # Disponibilidad
    "reachable",
    "status_code",
    "error_fetch",
    # Rendimiento (lo volátil que varía con la carga del servidor)
    "ttfb_ms",
    "tiempo_total_ms",
    "tamanio_kb",
    "tiene_viewport",
    "score_local_performance",
    # Seguridad
    "https",
    "redirige_a_https",
    "ssl_ok",
    "ssl_estado",
    "ssl_self_signed",
    "ssl_dias_restantes",
    "ssl_tls_version",
    "header_hsts",
    "header_csp",
    "header_x_frame_options",
    "header_referrer_policy",
    "score_local_security",
    # Transparencia LAIP (presencia por apartado; sin Wayback en el ciclo diario)
    "laip_transparencia",
    "laip_presupuesto",
    "laip_compras",
    "laip_personal",
    "laip_servicios",
    "laip_estructura",
    "laip_contacto",
    "laip_pct_cumplimiento",
]


def proyectar_snapshot(registro: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce un registro de auditoría al esquema canónico (rellena faltantes con None)."""
    return {campo: registro.get(campo) for campo in SNAPSHOT_FIELDS}


# ---------------------------------------------------------------------------
# Escritura: append a JSONL mensual
# ---------------------------------------------------------------------------
def _jsonl_del_mes(run_date: str, daily_dir: Path = DAILY_DIR) -> Path:
    """`data/daily/YYYY-MM.jsonl` a partir de una fecha 'YYYY-MM-DD'."""
    mes = run_date[:7]  # 'YYYY-MM'
    return daily_dir / f"{mes}.jsonl"


def append_snapshots(
    registros: List[Dict[str, Any]],
    *,
    daily_dir: Path = DAILY_DIR,
) -> Optional[Path]:
    """
    Añade una lista de snapshots (ya proyectados o no) al JSONL del mes.
    Todos los registros deben compartir el mismo run_date.
    Devuelve la ruta del archivo escrito, o None si la lista está vacía.
    """
    if not registros:
        return None

    daily_dir.mkdir(parents=True, exist_ok=True)
    proyectados = [proyectar_snapshot(r) for r in registros]
    run_date = proyectados[0].get("run_date") or ""
    destino = _jsonl_del_mes(run_date, daily_dir)

    with open(destino, "a", encoding="utf-8") as f:
        for snap in proyectados:
            f.write(json.dumps(snap, ensure_ascii=False, default=str) + "\n")

    log.info("Escritos %d snapshots en %s", len(proyectados), destino.name)
    return destino


# ---------------------------------------------------------------------------
# Lectura: iterar / cargar todos los JSONL
# ---------------------------------------------------------------------------
def iter_snapshots(daily_dir: Path = DAILY_DIR) -> Iterator[Dict[str, Any]]:
    """Itera todos los snapshots de todos los JSONL del directorio."""
    for jsonl in sorted(daily_dir.glob("*.jsonl")):
        with open(jsonl, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    yield json.loads(linea)
                except json.JSONDecodeError as ex:
                    log.warning("Línea inválida en %s: %s", jsonl.name, ex)


def cargar_snapshots_df(daily_dir: Path = DAILY_DIR) -> pd.DataFrame:
    """Carga todos los snapshots a un DataFrame (vacío con columnas si no hay datos)."""
    filas = list(iter_snapshots(daily_dir))
    if not filas:
        return pd.DataFrame(columns=SNAPSHOT_FIELDS)
    df = pd.DataFrame(filas)
    # Garantizar todas las columnas del esquema y su orden
    for c in SNAPSHOT_FIELDS:
        if c not in df.columns:
            df[c] = None
    return df[SNAPSHOT_FIELDS]


# ---------------------------------------------------------------------------
# Índice derivado: reconstruir SQLite desde los JSONL
# ---------------------------------------------------------------------------
def rebuild_sqlite(
    daily_dir: Path = DAILY_DIR,
    db_path: Path = SQLITE_DB,
) -> int:
    """
    Reconstruye `data/egov.db` (tabla `mediciones`) desde cero a partir de los
    JSONL. Idempotente: se puede correr cuantas veces se quiera.
    Devuelve el número de filas cargadas.
    """
    df = cargar_snapshots_df(daily_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        df.to_sql("mediciones", con, if_exists="replace", index=False)
        # Índices útiles para las consultas típicas (por portal, por hora)
        cur = con.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS ix_url ON mediciones(url)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_run_hour ON mediciones(run_hour)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_run_date ON mediciones(run_date)")
        con.commit()
    finally:
        con.close()

    log.info("SQLite reconstruido: %s (%d filas)", db_path, len(df))
    return len(df)


def resumen_cobertura(daily_dir: Path = DAILY_DIR) -> Dict[str, Any]:
    """Resumen rápido de cuántas corridas/portales hay acumulados."""
    df = cargar_snapshots_df(daily_dir)
    if df.empty:
        return {"snapshots": 0, "corridas": 0, "portales": 0, "dias": 0}
    return {
        "snapshots": len(df),
        "corridas": df["run_id"].nunique(),
        "portales": df["url"].nunique(),
        "dias": df["run_date"].nunique(),
        "primera": df["run_ts"].min(),
        "ultima": df["run_ts"].max(),
    }
