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

from typing import Dict, Any, Iterable, Optional, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

try:
    from statsmodels.formula.api import logit as _sm_logit
    _SM_OK = True
except ImportError:
    _SM_OK = False


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


# ===========================================================================
# OE4 — Análisis de datos categóricos
# ===========================================================================
#
# Responde a la pregunta auxiliar 4 del anteproyecto:
#   ¿Existen asociaciones estadísticamente significativas (α = 0.05) entre el
#   cumplimiento del Decreto 57-2008 y las variables operativas de los portales
#   (departamento, cabecera, calidad técnica, tipo de hosting), evaluadas con
#   pruebas no paramétricas y regresión logística?
#
# DISEÑO: estas funciones consumen la TABLA CONSOLIDADA (1 fila por portal),
# que ya trae las variables dependientes derivadas sin pseudoreplicación:
#   - cumple_LAIP (0/1), tiene_vulnerabilidad (0/1)
#   - predictores: departamento, cabecera, tipo_hosting, calidad_tecnica
# Si en cambio recibe un resultados.csv ad-hoc (una sola medición por portal),
# deriva las dependientes al vuelo, para que el reporte ad-hoc también tenga OE4.


def _categorizar_calidad_tecnica(score: float) -> Optional[str]:
    if pd.isna(score):
        return None
    if score >= 70:
        return "Buena"
    if score >= 40:
        return "Aceptable"
    return "Deficiente"


def _resp_binaria(serie: pd.Series, etiqueta_1: str, etiqueta_0: str) -> pd.Series:
    """Mapea una columna 0/1 (o NaN) a etiquetas legibles."""
    def f(v):
        if pd.isna(v):
            return None
        return etiqueta_1 if int(v) == 1 else etiqueta_0
    return serie.apply(f)


def preparar_variables_categoricas(
    df: pd.DataFrame,
    umbral_laip: float = 50.0,
) -> pd.DataFrame:
    """
    Construye el DataFrame de variables categóricas para OE4. Detecta si el
    input es el consolidado (usa cumple_LAIP / tiene_vulnerabilidad) o un
    resultados.csv ad-hoc (deriva las dependientes).

    Columnas generadas (las que apliquen):
      cat_departamento, cat_cabecera, cat_tipo_hosting, cat_calidad_tecnica
      cat_cumple_laip   (Cumple/No cumple)   ← respuesta principal
      cat_vulnerable    (Vulnerable/Seguro)  ← respuesta secundaria
    """
    out = pd.DataFrame(index=df.index)

    # ---- Predictores ----
    if "departamento" in df.columns:
        out["cat_departamento"] = df["departamento"]
    if "cabecera" in df.columns:
        out["cat_cabecera"] = df["cabecera"].apply(
            lambda v: "Cabecera" if bool(v) else "No cabecera"
        )
    if "tipo_hosting" in df.columns:
        out["cat_tipo_hosting"] = df["tipo_hosting"]

    if "calidad_tecnica" in df.columns:
        out["cat_calidad_tecnica"] = df["calidad_tecnica"]
    elif "score_perf_mediana" in df.columns:
        out["cat_calidad_tecnica"] = pd.to_numeric(
            df["score_perf_mediana"], errors="coerce"
        ).apply(_categorizar_calidad_tecnica)
    elif "score_local_performance" in df.columns:
        out["cat_calidad_tecnica"] = pd.to_numeric(
            df["score_local_performance"], errors="coerce"
        ).apply(_categorizar_calidad_tecnica)

    # ---- Respuesta 1: cumplimiento LAIP ----
    if "cumple_LAIP" in df.columns:
        out["cat_cumple_laip"] = _resp_binaria(df["cumple_LAIP"], "Cumple", "No cumple")
    elif "laip_pct_cumplimiento" in df.columns:
        out["cat_cumple_laip"] = pd.to_numeric(
            df["laip_pct_cumplimiento"], errors="coerce"
        ).apply(lambda v: None if pd.isna(v) else ("Cumple" if v >= umbral_laip else "No cumple"))

    # ---- Respuesta 2: vulnerabilidad ----
    if "tiene_vulnerabilidad" in df.columns:
        out["cat_vulnerable"] = _resp_binaria(df["tiene_vulnerabilidad"], "Vulnerable", "Seguro")
    else:
        # Derivar de un resultados.csv ad-hoc
        def _vuln(row):
            flags = []
            if "ssl_ok" in df.columns:
                flags.append(not bool(row.get("ssl_ok")))
            if "redirige_a_https" in df.columns:
                flags.append(not bool(row.get("redirige_a_https")))
            if "header_hsts" in df.columns:
                flags.append(not bool(row.get("header_hsts")))
            if not flags:
                return None
            return "Vulnerable" if any(flags) else "Seguro"
        if any(c in df.columns for c in ("ssl_ok", "redirige_a_https", "header_hsts")):
            out["cat_vulnerable"] = df.apply(_vuln, axis=1)

    return out


def tabla_contingencia(df_cat, var_fila, var_columna):
    if var_fila not in df_cat.columns or var_columna not in df_cat.columns:
        return None
    sub = df_cat[[var_fila, var_columna]].dropna()
    if sub.empty:
        return None
    return pd.crosstab(sub[var_fila], sub[var_columna], margins=True, margins_name="Total")


def _v_de_cramer(chi2: float, n: int, filas: int, cols: int) -> float:
    if n == 0:
        return 0.0
    phi2 = chi2 / n
    k = min(filas - 1, cols - 1)
    return float(np.sqrt(phi2 / k)) if k > 0 else 0.0


def _interpretar_cramer(v: float) -> str:
    if v < 0.10:
        return "Insignificante"
    if v < 0.30:
        return "Pequeña"
    if v < 0.50:
        return "Mediana"
    return "Grande"


def pruebas_chi_cuadrado(
    df_cat: pd.DataFrame,
    var_respuesta: str,
    predictores: List[str],
) -> pd.DataFrame:
    """
    χ² de independencia + Fisher (2x2) o Monte Carlo (RxC) cuando hay celdas
    escasas, + V de Cramér, para cada predictor vs la respuesta.
    """
    filas: List[Dict[str, Any]] = []
    if var_respuesta not in df_cat.columns:
        return pd.DataFrame()

    for pred in predictores:
        if pred not in df_cat.columns:
            continue
        sub = df_cat[[pred, var_respuesta]].dropna()
        if len(sub) < 5:
            continue
        tabla = pd.crosstab(sub[pred], sub[var_respuesta])
        if tabla.shape[0] < 2 or tabla.shape[1] < 2:
            continue

        n = int(tabla.values.sum())
        try:
            chi2, p_chi, dof, esperado = stats.chi2_contingency(
                tabla.values, correction=(tabla.shape == (2, 2))
            )
        except ValueError:
            continue

        esperado_min = float(np.min(esperado))
        freq_bajas = esperado_min < 5

        p_fisher = None
        metodo_fisher = ""
        if tabla.shape == (2, 2):
            try:
                _, p_fisher = stats.fisher_exact(tabla.values)
                metodo_fisher = "Fisher exacta (2x2)"
            except ValueError:
                p_fisher = None
        elif freq_bajas:
            try:
                res = stats.chi2_contingency(tabla.values, method="monte-carlo")
                p_fisher = float(res.pvalue)
                metodo_fisher = "Chi² Monte Carlo (RxC)"
            except (ValueError, TypeError, AttributeError):
                p_fisher = None

        v_cramer = _v_de_cramer(chi2, n, tabla.shape[0], tabla.shape[1])
        usa_fisher = freq_bajas and p_fisher is not None
        p_rep = p_fisher if usa_fisher else p_chi
        prueba = metodo_fisher if usa_fisher else "Chi² de independencia"

        filas.append({
            "predictor": pred.replace("cat_", ""),
            "variable_respuesta": var_respuesta.replace("cat_", ""),
            "n": n,
            "filas_x_cols": f"{tabla.shape[0]}x{tabla.shape[1]}",
            "chi2": round(float(chi2), 4),
            "gl": int(dof),
            "p_chi2": round(float(p_chi), 6),
            "freq_esperada_min": round(esperado_min, 2),
            "freq_esperada_baja_<5": freq_bajas,
            "p_fisher_o_mc": round(float(p_fisher), 6) if p_fisher is not None else None,
            "prueba_recomendada": prueba,
            "p_recomendado": round(float(p_rep), 6),
            "significativo_alfa005": bool(p_rep < 0.05),
            "V_cramer": round(v_cramer, 4),
            "magnitud_asociacion": _interpretar_cramer(v_cramer),
        })

    return pd.DataFrame(filas)


def regresion_logistica_binaria(
    df_cat: pd.DataFrame,
    var_respuesta: str,
    predictores: List[str],
    nivel_positivo: str,
) -> Tuple[Optional[pd.DataFrame], Dict[str, Any]]:
    """
    logit( P(Y = nivel_positivo) ) = β0 + Σ βi·Xi  con predictores categóricos.
    Devuelve (tabla_coeficientes, metricas) o (None, {error}).
    """
    if not _SM_OK:
        return None, {"error": "statsmodels no está instalado"}
    if var_respuesta not in df_cat.columns:
        return None, {"error": f"no existe {var_respuesta}"}

    cols = [var_respuesta] + [p for p in predictores if p in df_cat.columns]
    sub = df_cat[cols].dropna().copy()
    if len(sub) < 10:
        return None, {"error": f"n={len(sub)} insuficiente para regresión logística"}

    niveles = list(sub[var_respuesta].unique())
    if nivel_positivo not in niveles or len(niveles) != 2:
        return None, {"error": f"la respuesta debe tener 2 niveles con '{nivel_positivo}'; hay {niveles}"}

    sub["y_bin"] = (sub[var_respuesta] == nivel_positivo).astype(int)
    preds_validos = [p for p in predictores if p in sub.columns and sub[p].nunique() >= 2]
    if not preds_validos:
        return None, {"error": "ningún predictor con variabilidad suficiente"}

    formula = "y_bin ~ " + " + ".join(f"C(Q('{p}'))" for p in preds_validos)
    try:
        modelo = _sm_logit(formula, data=sub).fit(disp=False, maxiter=200)
    except Exception as ex:
        return None, {"error": f"ajuste fallido: {ex}"}

    coefs, se, z, p = modelo.params, modelo.bse, modelo.tvalues, modelo.pvalues
    ic = modelo.conf_int(alpha=0.05)
    ic.columns = ["lo", "hi"]

    tabla = pd.DataFrame({
        "termino": coefs.index,
        "coef": coefs.values.round(4),
        "std_err": se.values.round(4),
        "z": z.values.round(4),
        "p_valor": p.values.round(6),
        "OR": np.exp(coefs.values).round(4),
        "IC95_OR_low": np.exp(ic["lo"].values).round(4),
        "IC95_OR_high": np.exp(ic["hi"].values).round(4),
        "significativo_alfa005": (p.values < 0.05),
    })

    def _limpiar(t: str) -> str:
        return t.replace("C(Q('", "").replace("'))", "").replace("[T.", "=").replace("]", "")
    tabla["termino"] = tabla["termino"].apply(_limpiar)

    metricas = {
        "n_observaciones": int(modelo.nobs),
        "log_likelihood": round(float(modelo.llf), 3),
        "ll_nulo": round(float(modelo.llnull), 3),
        "pseudo_R2_McFadden": round(float(modelo.prsquared), 4),
        "aic": round(float(modelo.aic), 3),
        "bic": round(float(modelo.bic), 3),
        "p_LR_modelo": round(float(modelo.llr_pvalue), 6),
        "convergio": bool(modelo.mle_retvals.get("converged", False)),
        "formula": formula,
        "nivel_positivo": nivel_positivo,
    }
    return tabla, metricas


def analisis_oe4_completo(
    df: pd.DataFrame,
    umbral_laip: float = 50.0,
) -> Dict[str, Any]:
    """
    Ejecuta todo OE4 sobre la tabla consolidada (o un resultados.csv ad-hoc).
    Devuelve dict con df_categorico, pruebas χ²/Fisher y modelos logísticos
    para cumplimiento LAIP y vulnerabilidad.
    """
    df_cat = preparar_variables_categoricas(df, umbral_laip=umbral_laip)

    predictores = [c for c in (
        "cat_departamento", "cat_cabecera", "cat_tipo_hosting", "cat_calidad_tecnica"
    ) if c in df_cat.columns]

    chi2_laip = pruebas_chi_cuadrado(df_cat, "cat_cumple_laip", predictores) \
        if "cat_cumple_laip" in df_cat.columns else pd.DataFrame()
    chi2_vuln = pruebas_chi_cuadrado(df_cat, "cat_vulnerable", predictores) \
        if "cat_vulnerable" in df_cat.columns else pd.DataFrame()

    coef_laip, met_laip = (None, {"error": "sin variable cat_cumple_laip"})
    if "cat_cumple_laip" in df_cat.columns:
        coef_laip, met_laip = regresion_logistica_binaria(
            df_cat, "cat_cumple_laip", predictores, "Cumple"
        )
    coef_vuln, met_vuln = (None, {"error": "sin variable cat_vulnerable"})
    if "cat_vulnerable" in df_cat.columns:
        coef_vuln, met_vuln = regresion_logistica_binaria(
            df_cat, "cat_vulnerable", predictores, "Vulnerable"
        )

    tablas_cont = {}
    for p in predictores:
        if "cat_cumple_laip" in df_cat.columns:
            t = tabla_contingencia(df_cat, p, "cat_cumple_laip")
            if t is not None:
                tablas_cont[p.replace("cat_", "")] = t

    return {
        "df_categorico": df_cat,
        "chi2_laip": chi2_laip,
        "chi2_vuln": chi2_vuln,
        "logit_laip_coef": coef_laip,
        "logit_laip_metricas": met_laip,
        "logit_vuln_coef": coef_vuln,
        "logit_vuln_metricas": met_vuln,
        "tablas_contingencia_laip": tablas_cont,
        "umbral_laip_usado": umbral_laip,
    }
