"""
Consolida los snapshots diarios en 1 fila por portal.

Entrada: DataFrame de snapshots (de `store.cargar_snapshots_df`).
Salida:  DataFrame con una fila por URL (portal), listo para el análisis OE4.

Agregación:
  - continuas (ttfb, tiempo_total, tamanio_kb): mediana + std sobre corridas
    EXITOSAS (reachable=True). Las caídas no deben sesgar la latencia.
  - dicotómicas/categóricas (ssl_estado, headers, viewport, LAIP): valor MODAL
    sobre corridas exitosas, con desempate conservador (gana el peor caso en
    seguridad; "ausente" en LAIP).
  - uptime_pct: % de corridas exitosas sobre el TOTAL de intentos.

Variables dependientes (definición acordada con el investigador):
  cumple_LAIP          = 1 si TODOS los apartados obligatorios (modales) están
                         presentes; 0 si falta al menos uno.
  tiene_vulnerabilidad = 1 si al menos una de:
                           (a) ssl_estado_modal ∈ {invalido, autofirmado, hostname_mismatch}
                           (b) redirige_https_modal == False
                           (c) HSTS, X-Frame-Options y CSP los tres ausentes
                         0 si no presenta ninguna.
  (ambas = None si el portal no tuvo ninguna corrida exitosa → no evaluable)

Predictores: departamento, cabecera, tipo_hosting (heurístico por dominio),
calidad_tecnica (de la mediana de score_local_performance).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from src.logger import get_logger

log = get_logger(__name__)


# Apartados LAIP que se exigen para cumple_LAIP (los 7 indicadores del Art. 10/11).
APARTADOS_LAIP_OBLIGATORIOS: Sequence[str] = (
    "transparencia", "presupuesto", "compras", "personal",
    "servicios", "estructura", "contacto",
)
TOTAL_APARTADOS_LAIP = len(APARTADOS_LAIP_OBLIGATORIOS)   # 7
# "Mayoría" = más de la mitad de los 7 apartados → ≥ 4.
UMBRAL_MAYORIA_LAIP = 4

# Severidad de ssl_estado para el desempate de la moda (peor primero).
_SEVERIDAD_SSL = ["invalido", "autofirmado", "hostname_mismatch", "no_evaluable", "valido"]


def clasificar_nivel_laip(
    apartados_presentes: Optional[int],
    total: int = TOTAL_APARTADOS_LAIP,
    umbral_mayoria: int = UMBRAL_MAYORIA_LAIP,
) -> Optional[str]:
    """
    Nivel de cumplimiento LAIP en 3 categorías ordinales:
        Pleno      → presenta TODOS los apartados (cumplimiento perfecto)
        Limitado   → presenta la mayoría (≥ umbral) pero no todos
        No_cumple  → presenta menos de la mayoría
    Devuelve None si el portal no tuvo corridas exitosas (no evaluable).
    """
    if apartados_presentes is None:
        return None
    if apartados_presentes >= total:
        return "Pleno"
    if apartados_presentes >= umbral_mayoria:
        return "Limitado"
    return "No_cumple"


# ---------------------------------------------------------------------------
# Helpers de agregación
# ---------------------------------------------------------------------------
def _moda_bool(serie: pd.Series) -> Optional[bool]:
    """Moda booleana sobre valores no nulos. Empate → False (conservador)."""
    s = serie.dropna()
    if s.empty:
        return None
    s = s.astype(bool)
    modas = s.mode()
    if len(modas) == 0:
        return None
    if len(modas) > 1:
        return False  # empate → peor caso (ausente/no cumple)
    return bool(modas.iloc[0])


def _moda_ssl(serie: pd.Series) -> Optional[str]:
    """Moda de ssl_estado; empate → estado más severo entre los empatados."""
    s = serie.dropna()
    if s.empty:
        return None
    modas = list(s.mode())
    if not modas:
        return None
    if len(modas) == 1:
        return str(modas[0])
    for estado in _SEVERIDAD_SSL:  # peor primero
        if estado in modas:
            return estado
    return str(modas[0])


def _moda_cat(serie: pd.Series) -> Optional[Any]:
    """Moda de una categórica genérica (p. ej. tls_version). Empate → primera."""
    s = serie.dropna()
    if s.empty:
        return None
    modas = s.mode()
    return modas.iloc[0] if len(modas) else None


def _mediana_std(serie: pd.Series) -> tuple:
    """(mediana, std muestral) de una serie numérica; (None, None) si vacía."""
    s = pd.to_numeric(serie, errors="coerce").dropna()
    if s.empty:
        return None, None
    mediana = round(float(s.median()), 2)
    std = round(float(s.std(ddof=1)), 2) if len(s) > 1 else 0.0
    return mediana, std


# ---------------------------------------------------------------------------
# Predictores derivados
# ---------------------------------------------------------------------------
def clasificar_hosting(url: Optional[str]) -> str:
    """
    Heurística de tipo de hosting por dominio/TLD (sin lookups externos):
      gob_propio        → dominio .gob.gt propio (no IAP)
      transparencia_iap → subdominio en iap.gob.gt
      comercial_gt      → .com.gt / .org.gt / .net.gt
      comercial_generico→ .com / .org / .net
      otro              → cualquier otro
    """
    if not url:
        return "otro"
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "otro"
    if host.endswith(".iap.gob.gt") or ".iap.gob.gt" in host:
        return "transparencia_iap"
    if host.endswith(".gob.gt") or host == "gob.gt":
        return "gob_propio"
    if host.endswith((".com.gt", ".org.gt", ".net.gt")):
        return "comercial_gt"
    if host.endswith((".com", ".org", ".net")):
        return "comercial_generico"
    return "otro"


def categorizar_calidad_tecnica(score: Optional[float]) -> Optional[str]:
    """Trino ordinal sobre la mediana del score de performance (0–100)."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return None
    if score >= 70:
        return "Buena"
    if score >= 40:
        return "Aceptable"
    return "Deficiente"


# ---------------------------------------------------------------------------
# Consolidación de un portal
# ---------------------------------------------------------------------------
def _consolidar_portal(
    sub: pd.DataFrame,
    apartados_obligatorios: Sequence[str],
) -> Dict[str, Any]:
    """Reduce todas las corridas de un portal (mismo url) a una fila."""
    n_corridas = len(sub)
    exitosas = sub[sub["reachable"].fillna(False).astype(bool)]
    n_exitosas = len(exitosas)

    def _id(col):
        vals = sub[col].dropna()
        return vals.iloc[0] if len(vals) else None

    fila: Dict[str, Any] = {
        "municipio": _id("municipio"),
        "departamento": _id("departamento"),
        "codigo_ine": _id("codigo_ine"),
        "cabecera": bool(_id("cabecera")) if _id("cabecera") is not None else False,
        "tipo_portal": _id("tipo_portal"),
        "url": _id("url"),
        "n_corridas": n_corridas,
        "n_exitosas": n_exitosas,
        "uptime_pct": round(n_exitosas / n_corridas * 100, 2) if n_corridas else 0.0,
        "primera_corrida": sub["run_ts"].min(),
        "ultima_corrida": sub["run_ts"].max(),
    }

    # Continuas (mediana + std) sobre corridas exitosas
    for col, pref in [("ttfb_ms", "ttfb"), ("tiempo_total_ms", "tiempo_total"),
                      ("tamanio_kb", "tamanio_kb")]:
        med, std = _mediana_std(exitosas[col]) if not exitosas.empty else (None, None)
        fila[f"{pref}_mediana"] = med
        fila[f"{pref}_std"] = std

    # Scores medianos (performance, security) sobre exitosas
    for col, alias in [("score_local_performance", "score_perf_mediana"),
                       ("score_local_security", "score_sec_mediana")]:
        med, _ = _mediana_std(exitosas[col]) if not exitosas.empty else (None, None)
        fila[alias] = med

    # Modales (solo exitosas)
    if n_exitosas:
        fila["viewport_modal"] = _moda_bool(exitosas["tiene_viewport"])
        fila["ssl_estado_modal"] = _moda_ssl(exitosas["ssl_estado"])
        fila["redirige_https_modal"] = _moda_bool(exitosas["redirige_a_https"])
        fila["header_hsts_modal"] = _moda_bool(exitosas["header_hsts"])
        fila["header_csp_modal"] = _moda_bool(exitosas["header_csp"])
        fila["header_xfo_modal"] = _moda_bool(exitosas["header_x_frame_options"])
        fila["tls_version_modal"] = _moda_cat(exitosas["ssl_tls_version"])
        for ap in APARTADOS_LAIP_OBLIGATORIOS:
            fila[f"laip_{ap}_modal"] = _moda_bool(exitosas[f"laip_{ap}"])
        med_laip, _ = _mediana_std(exitosas["laip_pct_cumplimiento"])
        fila["laip_pct_mediana"] = med_laip
    else:
        for c in ("viewport_modal", "ssl_estado_modal", "redirige_https_modal",
                  "header_hsts_modal", "header_csp_modal", "header_xfo_modal",
                  "tls_version_modal", "laip_pct_mediana"):
            fila[c] = None
        for ap in APARTADOS_LAIP_OBLIGATORIOS:
            fila[f"laip_{ap}_modal"] = None

    # ---- Variables dependientes ----
    if n_exitosas == 0:
        fila["laip_apartados_presentes"] = None
        fila["cumple_LAIP"] = None
        fila["nivel_laip"] = None
        fila["tiene_vulnerabilidad"] = None
    else:
        presentes = [bool(fila.get(f"laip_{ap}_modal")) for ap in APARTADOS_LAIP_OBLIGATORIOS]
        fila["laip_apartados_presentes"] = int(sum(presentes))
        obligatorios = [bool(fila.get(f"laip_{ap}_modal")) for ap in apartados_obligatorios]
        # cumple_LAIP (0/1, estricto): se conserva como hallazgo descriptivo.
        fila["cumple_LAIP"] = int(all(obligatorios)) if obligatorios else None
        # nivel_laip (3 niveles ordinales): variable principal para el OE4.
        fila["nivel_laip"] = clasificar_nivel_laip(fila["laip_apartados_presentes"])

        ssl_malo = fila["ssl_estado_modal"] in {"invalido", "autofirmado", "hostname_mismatch"}
        sin_redir = fila["redirige_https_modal"] is False
        sin_headers = (
            fila["header_hsts_modal"] is False
            and fila["header_xfo_modal"] is False
            and fila["header_csp_modal"] is False
        )
        fila["tiene_vulnerabilidad"] = int(ssl_malo or sin_redir or sin_headers)

    # ---- Predictores ----
    fila["tipo_hosting"] = clasificar_hosting(fila["url"])
    fila["calidad_tecnica"] = categorizar_calidad_tecnica(fila["score_perf_mediana"])

    return fila


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def consolidar(
    df_snapshots: pd.DataFrame,
    *,
    apartados_obligatorios: Sequence[str] = APARTADOS_LAIP_OBLIGATORIOS,
    enriquecer_wayback: bool = False,
) -> pd.DataFrame:
    """
    Consolida snapshots → 1 fila/portal.

    apartados_obligatorios: subconjunto de apartados LAIP exigidos para
        cumple_LAIP=1 (por defecto los 7). Permite relajar la definición si
        resultara degenerada (todos 0) para el análisis.
    enriquecer_wayback: si True, consulta Wayback Machine una vez por portal
        para añadir frescura histórica y score_local_freshness (hace red).
    """
    if df_snapshots.empty:
        log.warning("No hay snapshots para consolidar.")
        return pd.DataFrame()

    filas: List[Dict[str, Any]] = []
    for url, sub in df_snapshots.groupby("url", dropna=True):
        filas.append(_consolidar_portal(sub, apartados_obligatorios))

    consolidado = pd.DataFrame(filas)
    log.info(
        "Consolidados %d portales desde %d snapshots",
        len(consolidado), len(df_snapshots),
    )

    if enriquecer_wayback:
        consolidado = _enriquecer_con_wayback(consolidado)

    return consolidado


def _enriquecer_con_wayback(consolidado: pd.DataFrame) -> pd.DataFrame:
    """
    Añade frescura histórica (Wayback) por portal. Se llama UNA vez por portal
    (no por corrida) porque el historial no cambia entre corridas del día.
    Hace una consulta de red por portal; usar solo al generar el reporte final.
    """
    from src.audits.content_freshness import _consultar_wayback  # import diferido

    cols_wb = ["snapshots_unicos", "dias_desde_ultima_actualizacion",
               "intervalo_medio_dias", "actualizaciones_unicas_2025_2026"]
    for c in cols_wb:
        consolidado[c] = None

    for idx, fila in consolidado.iterrows():
        url = fila.get("url")
        if not url:
            continue
        try:
            wb = _consultar_wayback(url)
            for c in cols_wb:
                consolidado.at[idx, c] = wb.get(c)
        except Exception as ex:
            log.warning("Wayback %s: %s", url, ex)

    return consolidado


def consolidar_desde_jsonl(**kwargs) -> pd.DataFrame:
    """Atajo: carga los snapshots de data/daily y consolida."""
    from src.collect.store import cargar_snapshots_df
    return consolidar(cargar_snapshots_df(), **kwargs)


# Alias: consolidado (_mediana/_modal) → nombres del esquema ad-hoc, para que
# el generador de Excel y el dashboard existentes funcionen sin cambios.
_ALIAS_REPORTE = {
    "ttfb_mediana": "ttfb_ms",
    "tiempo_total_mediana": "tiempo_total_ms",
    "tamanio_kb_mediana": "tamanio_kb",
    "score_perf_mediana": "score_local_performance",
    "score_sec_mediana": "score_local_security",
    "laip_pct_mediana": "laip_pct_cumplimiento",
    "viewport_modal": "tiene_viewport",
    "redirige_https_modal": "redirige_a_https",
    "header_hsts_modal": "header_hsts",
    "header_csp_modal": "header_csp",
    "header_xfo_modal": "header_x_frame_options",
}


def a_formato_reporte(df_consolidado: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve una copia del consolidado con columnas-alias compatibles con el
    esquema del resultados.csv ad-hoc, preservando las columnas propias del
    consolidado (uptime_pct, *_mediana, cumple_LAIP, tiene_vulnerabilidad,
    tipo_hosting, calidad_tecnica). Así el reporte/dashboard se reutilizan tal
    cual y además ganan uptime + OE4.
    """
    df = df_consolidado.copy()
    if df.empty:
        return df

    for src, dst in _ALIAS_REPORTE.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]

    # reachable: en el consolidado, "alcanzable" = tuvo al menos una corrida exitosa
    if "n_exitosas" in df.columns and "reachable" not in df.columns:
        df["reachable"] = df["n_exitosas"].fillna(0).astype(int) > 0

    # ssl_ok / https desde ssl_estado_modal
    if "ssl_estado_modal" in df.columns:
        df["ssl_ok"] = df["ssl_estado_modal"].apply(
            lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else (v == "valido")
        )
        if "https" not in df.columns:
            df["https"] = df["ssl_ok"]

    # laip_<apartado> desde sus modales
    for ap in APARTADOS_LAIP_OBLIGATORIOS:
        m = f"laip_{ap}_modal"
        if m in df.columns and f"laip_{ap}" not in df.columns:
            df[f"laip_{ap}"] = df[m]

    return df
