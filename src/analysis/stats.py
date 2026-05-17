"""
Análisis estadístico de los resultados de auditoría.

Provee:
- Estadística descriptiva (media, mediana, desviación, IQR, mínimo, máximo)
- Intervalos de confianza al 95%
- Distribución por departamento
- Tasas de cumplimiento (proporciones) con intervalos de confianza Wilson
- Detección de outliers (IQR)
- Correlaciones entre variables (Pearson y Spearman)
- Pruebas de comparación entre departamentos (Kruskal-Wallis)

Todo retorna pandas DataFrames listos para exportar.
"""
from __future__ import annotations

from typing import Dict, Any, Iterable, Optional, List

import numpy as np
import pandas as pd
from scipy import stats


# ---------- Descriptiva ----------

def descriptiva_numerica(df: pd.DataFrame, columnas: Iterable[str]) -> pd.DataFrame:
    """Estadísticos descriptivos por columna numérica."""
    filas = []
    for col in columnas:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        ci_low, ci_high = _ic_media_95(s)
        filas.append({
            "variable": col,
            "n": len(s),
            "media": round(s.mean(), 3),
            "mediana": round(s.median(), 3),
            "desviacion": round(s.std(ddof=1), 3) if len(s) > 1 else 0.0,
            "min": round(s.min(), 3),
            "max": round(s.max(), 3),
            "q1": round(s.quantile(0.25), 3),
            "q3": round(s.quantile(0.75), 3),
            "iqr": round(s.quantile(0.75) - s.quantile(0.25), 3),
            "ic95_low": round(ci_low, 3) if ci_low is not None else None,
            "ic95_high": round(ci_high, 3) if ci_high is not None else None,
            "outliers_iqr": _contar_outliers_iqr(s),
        })
    return pd.DataFrame(filas)


def _ic_media_95(s: pd.Series):
    """Intervalo de confianza 95% de la media (t-student)."""
    n = len(s)
    if n < 2:
        return None, None
    m = s.mean()
    se = s.std(ddof=1) / np.sqrt(n)
    t = stats.t.ppf(0.975, n - 1)
    return m - t * se, m + t * se


def _contar_outliers_iqr(s: pd.Series) -> int:
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return int(((s < lo) | (s > hi)).sum())


# ---------- Proporciones (variables booleanas) ----------

def proporciones(df: pd.DataFrame, columnas_bool: Iterable[str]) -> pd.DataFrame:
    """
    Tasas de cumplimiento con IC95 (Wilson). Útil para preguntas como:
    '¿qué % de portales tiene HSTS?'
    """
    filas = []
    for col in columnas_bool:
        if col not in df.columns:
            continue
        s = df[col]
        # Convertir a booleano numpy
        s_bool = s.fillna(False).astype(bool)
        n = len(s_bool)
        k = int(s_bool.sum())
        if n == 0:
            continue
        p = k / n
        # IC Wilson
        low, high = _wilson(k, n)
        filas.append({
            "variable": col,
            "n": n,
            "k_cumplen": k,
            "proporcion": round(p, 4),
            "porcentaje": round(p * 100, 2),
            "ic95_low_pct": round(low * 100, 2),
            "ic95_high_pct": round(high * 100, 2),
        })
    return pd.DataFrame(filas)


def _wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z**2 / n
    centro = (p + z**2 / (2*n)) / den
    margen = z * np.sqrt(p*(1-p)/n + z**2 / (4*n*n)) / den
    return max(0.0, centro - margen), min(1.0, centro + margen)


# ---------- Distribución por departamento ----------

def resumen_por_departamento(df: pd.DataFrame, columnas: Iterable[str]) -> pd.DataFrame:
    """Estadísticos por departamento."""
    if "departamento" not in df.columns:
        return pd.DataFrame()
    filas = []
    for dep, sub in df.groupby("departamento"):
        for col in columnas:
            if col not in sub.columns:
                continue
            s = pd.to_numeric(sub[col], errors="coerce").dropna()
            if s.empty:
                continue
            filas.append({
                "departamento": dep,
                "variable": col,
                "n": len(s),
                "media": round(s.mean(), 3),
                "mediana": round(s.median(), 3),
                "desviacion": round(s.std(ddof=1), 3) if len(s) > 1 else 0.0,
            })
    return pd.DataFrame(filas)


# ---------- Pruebas estadísticas ----------

def comparar_departamentos_kruskal(df: pd.DataFrame, columnas: Iterable[str]) -> pd.DataFrame:
    """
    Aplica Kruskal-Wallis para detectar diferencias entre departamentos.
    No paramétrica → robusta a muestras pequeñas y no normales (caso típico aquí).
    """
    if "departamento" not in df.columns:
        return pd.DataFrame()
    filas = []
    for col in columnas:
        if col not in df.columns:
            continue
        grupos = []
        for _, sub in df.groupby("departamento"):
            s = pd.to_numeric(sub[col], errors="coerce").dropna().values
            if len(s) >= 2:
                grupos.append(s)
        if len(grupos) < 2:
            continue
        try:
            stat, pval = stats.kruskal(*grupos)
            filas.append({
                "variable": col,
                "k_grupos": len(grupos),
                "H_statistic": round(float(stat), 4),
                "p_value": round(float(pval), 6),
                "diferencia_significativa_α005": pval < 0.05,
            })
        except ValueError:
            continue
    return pd.DataFrame(filas)


def correlaciones(df: pd.DataFrame, columnas: List[str], metodo: str = "spearman") -> pd.DataFrame:
    """Matriz de correlación entre columnas numéricas."""
    cols_validas = [c for c in columnas if c in df.columns]
    sub = df[cols_validas].apply(pd.to_numeric, errors="coerce")
    return sub.corr(method=metodo).round(3)
