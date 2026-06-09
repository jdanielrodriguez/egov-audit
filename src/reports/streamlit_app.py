"""
Dashboard interactivo (Streamlit) para explorar el estudio longitudinal.

Ejecutar con:
    streamlit run src/reports/streamlit_app.py

Consume la tabla consolidada (1 fila por portal). Si no existe el CSV
consolidado, lo genera al vuelo desde los snapshots de data/daily.
Complementa al dashboard HTML estático (que sirve como entregable de la tesis):
aquí se filtra y explora en vivo; aquel se adjunta y se abre sin servidor.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from config.settings import CONSOLIDATED_DIR
from src.collect.store import cargar_snapshots_df
from src.consolidate.consolidator import consolidar
from src.analysis import stats as A


# ---------------------------------------------------------------------------
# Carga de datos (sin dependencia de Streamlit → testeable por separado)
# ---------------------------------------------------------------------------
def cargar_consolidado() -> Tuple[Optional[pd.DataFrame], str]:
    """
    Devuelve (df_consolidado, fuente). Prioriza consolidado_latest.csv; si no
    existe, consolida desde los snapshots. (None, motivo) si no hay datos.
    """
    latest = CONSOLIDATED_DIR / "consolidado_latest.csv"
    if latest.exists():
        return pd.read_csv(latest), f"CSV consolidado ({latest.name})"

    df_snap = cargar_snapshots_df()
    if df_snap.empty:
        return None, "No hay snapshots en data/daily ni consolidado previo."
    return consolidar(df_snap), "consolidado al vuelo desde snapshots"


def _pct(serie: pd.Series) -> Optional[float]:
    s = serie.dropna()
    return round(s.astype(bool).mean() * 100, 1) if len(s) else None


# ---------------------------------------------------------------------------
# UI (solo se ejecuta bajo `streamlit run`)
# ---------------------------------------------------------------------------
def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Auditoría e-Gov Suroccidente", layout="wide")
    st.title("Auditoría Técnica de Portales E-Gov — Suroccidente de Guatemala")
    st.caption("Estudio longitudinal · Maestría en Estadística Aplicada")

    df, fuente = cargar_consolidado()
    if df is None:
        st.warning(fuente)
        st.info("Corré `python run_daily.py` (o esperá a GitHub Actions) y luego recargá.")
        return
    st.caption(f"Fuente de datos: {fuente} · {len(df)} portales")

    # --- Filtro por departamento ---
    deps = sorted(df["departamento"].dropna().unique()) if "departamento" in df.columns else []
    sel = st.sidebar.multiselect("Departamentos", deps, default=deps)
    if sel:
        df = df[df["departamento"].isin(sel)]

    # --- KPIs ---
    c = st.columns(4)
    c[0].metric("Portales", len(df))
    if "uptime_pct" in df.columns:
        c[1].metric("Uptime medio", f"{pd.to_numeric(df['uptime_pct'], errors='coerce').mean():.1f}%")
    if "cumple_LAIP" in df.columns:
        c[2].metric("% cumple LAIP", f"{_pct(df['cumple_LAIP'])}%")
    if "tiene_vulnerabilidad" in df.columns:
        c[3].metric("% con vulnerabilidad", f"{_pct(df['tiene_vulnerabilidad'])}%")

    tabs = st.tabs(["Resumen", "OE1 Rendimiento", "OE2 LAIP", "OE3 Seguridad", "OE4 Categórico"])

    with tabs[0]:
        st.subheader("Tabla consolidada por portal")
        st.dataframe(df, use_container_width=True)

    with tabs[1]:
        st.subheader("OE1 — Rendimiento")
        if "score_perf_mediana" in df.columns and "departamento" in df.columns:
            st.bar_chart(df.groupby("departamento")["score_perf_mediana"].mean())
        if "ttfb_mediana" in df.columns:
            st.bar_chart(df.set_index("municipio")["ttfb_mediana"])

    with tabs[2]:
        st.subheader("OE2 — Transparencia LAIP")
        laip_cols = [c for c in df.columns if c.startswith("laip_") and c.endswith("_modal")]
        if laip_cols:
            pres = {c.replace("laip_", "").replace("_modal", ""):
                    df[c].dropna().astype(bool).mean() * 100 for c in laip_cols}
            st.bar_chart(pd.Series(pres, name="% portales con la sección"))

    with tabs[3]:
        st.subheader("OE3 — Seguridad")
        if "ssl_estado_modal" in df.columns:
            st.bar_chart(df["ssl_estado_modal"].value_counts())

    with tabs[4]:
        st.subheader("OE4 — Análisis de datos categóricos")
        try:
            oe4 = A.analisis_oe4_completo(df)
            st.markdown("**χ² / Fisher — Cumplimiento LAIP**")
            st.dataframe(oe4["chi2_laip"], use_container_width=True)
            st.markdown("**χ² / Fisher — Vulnerabilidad**")
            st.dataframe(oe4["chi2_vuln"], use_container_width=True)
            st.markdown("**Regresión logística — LAIP**")
            if oe4["logit_laip_coef"] is not None:
                st.dataframe(oe4["logit_laip_coef"], use_container_width=True)
                st.json(oe4["logit_laip_metricas"])
            else:
                st.info(f"Modelo LAIP no ajustado: {oe4['logit_laip_metricas'].get('error')}")
        except Exception as ex:
            st.error(f"No se pudo calcular OE4: {ex}")


if __name__ == "__main__":
    main()
