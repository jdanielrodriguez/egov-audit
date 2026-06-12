"""
Dashboard HTML autocontenido con los resultados de la auditoría.

- Single-file HTML (sin servidor, sin build): se abre directo en el navegador.
- Datos embebidos como JSON; gráficas con Chart.js (CDN).
- Navegación sticky entre los 4 objetivos específicos (OE1–OE4).
- Funciona tanto con el resultados.csv ad-hoc como con la tabla consolidada
  (en cuyo caso muestra uptime y OE4 sobre cumple_LAIP / tiene_vulnerabilidad).

Secciones:
0. Cabecera + navegación entre OEs
1. Resumen general y KPIs (incluye uptime si viene del consolidado)
2. OE1 — Rendimiento y accesibilidad
3. OE2 — Frescura y transparencia LAIP
4. OE3 — Seguridad básica
5. OE4 — Análisis de datos categóricos (χ², Fisher, V de Cramér, logística)
6. Tabla detallada por municipalidad
"""
from __future__ import annotations

import json
import math
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import numpy as np

from config.settings import REPORTS_DIR
from src.analysis import stats as A
from src.logger import get_logger

# pandas 2.x emite un FutureWarning por el downcasting de `.fillna(False).astype(bool)`
# sobre columnas object. No altera el resultado; lo silenciamos puntualmente.
warnings.filterwarnings(
    "ignore", message="Downcasting object dtype arrays", category=FutureWarning
)

log = get_logger(__name__)


def _safe(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, (list, dict)):
        return v
    return v


def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    out = []
    for _, row in df.iterrows():
        out.append({k: _safe(v) for k, v in row.items()})
    return out


def _calcular_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    total = len(df)
    reachable = int(df["reachable"].fillna(False).astype(bool).sum()) if "reachable" in df.columns else 0

    def media(col):
        if col not in df.columns:
            return None
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return round(s.mean(), 1) if not s.empty else None

    def pct(col):
        if col not in df.columns:
            return None
        s = df[col].fillna(False).astype(bool)
        return round(s.mean() * 100, 1) if len(s) else None

    def pct_nivel_laip(niveles):
        """% de portales (evaluables) cuyo nivel_laip está en `niveles`."""
        if "nivel_laip" not in df.columns:
            return None
        s = df["nivel_laip"].dropna()
        return round(s.isin(niveles).mean() * 100, 1) if len(s) else None

    return {
        "total_municipios": total,
        "reachable": reachable,
        "reachable_pct": round(reachable / total * 100, 1) if total else 0,
        "uptime_medio": media("uptime_pct"),
        "score_perf": media("score_local_performance"),
        "score_fresh": media("score_local_freshness"),
        "score_sec": media("score_local_security"),
        "pct_https": pct("https"),
        "pct_viewport": pct("tiene_viewport"),
        "pct_ssl_ok": pct("ssl_ok"),
        "pct_hsts": pct("header_hsts"),
        "pct_redirige_https": pct("redirige_a_https"),
        # LAIP en 3 niveles: % que alcanza al menos la mayoría (Pleno+Limitado)
        # y % de cumplimiento pleno (los 7 apartados).
        "pct_laip_mayoria": pct_nivel_laip(["Pleno", "Limitado"]),
        "pct_laip_pleno": pct_nivel_laip(["Pleno"]),
        "pct_vulnerable": pct("tiene_vulnerabilidad") if "tiene_vulnerabilidad" in df.columns else None,
        "laip_medio": media("laip_pct_cumplimiento"),
        "tiempo_carga_medio_ms": media("tiempo_total_ms"),
        "snapshots_medio": media("snapshots_unicos"),
        "dias_ultima_act": media("dias_desde_ultima_actualizacion"),
        "n_departamentos": df["departamento"].nunique() if "departamento" in df.columns else 0,
        "es_consolidado": "uptime_pct" in df.columns,
    }


def _datos_por_departamento(df: pd.DataFrame) -> Dict[str, Any]:
    if "departamento" not in df.columns:
        return {}
    out: Dict[str, Any] = {}
    for dep, sub in df.groupby("departamento"):
        def m(col):
            return float(pd.to_numeric(sub[col], errors="coerce").mean() or 0) if col in sub.columns else 0
        out[str(dep)] = {
            "n": len(sub),
            "score_perf": m("score_local_performance"),
            "score_fresh": m("score_local_freshness"),
            "score_sec": m("score_local_security"),
            "tiempo_carga_ms": m("tiempo_total_ms"),
            "laip_pct": m("laip_pct_cumplimiento"),
            "uptime": m("uptime_pct"),
        }
    return out


def _laip_cumplimiento(df: pd.DataFrame) -> Dict[str, float]:
    cats = ["transparencia", "presupuesto", "compras", "personal", "servicios", "estructura", "contacto"]
    out = {}
    for c in cats:
        col = f"laip_{c}"
        out[c] = round(df[col].fillna(False).astype(bool).mean() * 100, 1) if col in df.columns else 0.0
    return out


def _headers_seguridad(df: pd.DataFrame) -> Dict[str, float]:
    headers = {
        "HSTS": "header_hsts", "CSP": "header_csp",
        "X-Frame-Options": "header_x_frame_options",
        "X-Content-Type-Options": "header_x_content_type_options",
        "Referrer-Policy": "header_referrer_policy",
        "Permissions-Policy": "header_permissions_policy",
    }
    out = {}
    for label, col in headers.items():
        out[label] = round(df[col].fillna(False).astype(bool).mean() * 100, 1) if col in df.columns else 0.0
    return out


def _distribucion_scores(df: pd.DataFrame) -> Dict[str, List[int]]:
    bins = [0, 20, 40, 60, 80, 100]
    out = {"labels": ["0-20", "21-40", "41-60", "61-80", "81-100"]}
    for tipo, col in [("performance", "score_local_performance"),
                      ("freshness", "score_local_freshness"),
                      ("security", "score_local_security")]:
        if col not in df.columns:
            out[tipo] = [0] * 5
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        h, _ = np.histogram(s, bins=bins)
        out[tipo] = h.tolist()
    return out


def _payload_oe4(df: pd.DataFrame) -> Dict[str, Any]:
    try:
        oe4 = A.analisis_oe4_completo(df)
    except Exception as ex:
        log.warning("OE4 dashboard: %s", ex)
        return {"disponible": False, "razon": str(ex)}

    def recs(d):
        return _df_to_records(d) if isinstance(d, pd.DataFrame) and not d.empty else []

    df_cat = oe4.get("df_categorico")
    dist_laip, dist_vuln = {}, {}
    if isinstance(df_cat, pd.DataFrame):
        # LAIP: nivel de 3 categorías (Pleno/Limitado/No_cumple) si está; si no, la dicotomía.
        col_laip = "cat_nivel_laip" if "cat_nivel_laip" in df_cat.columns else "cat_cumple_mayoria"
        if col_laip in df_cat.columns:
            dist_laip = df_cat[col_laip].dropna().value_counts().to_dict()
        if "cat_vulnerable" in df_cat.columns:
            dist_vuln = df_cat["cat_vulnerable"].dropna().value_counts().to_dict()

    return {
        "disponible": True,
        "umbral_laip": oe4.get("umbral_laip_usado", 50.0),
        "var_laip": oe4.get("var_laip_chi2", ""),
        "chi2_laip": recs(oe4.get("chi2_laip")),
        "chi2_vuln": recs(oe4.get("chi2_vuln")),
        "logit_laip_coef": recs(oe4.get("logit_laip_coef")),
        "logit_laip_metricas": {k: _safe(v) for k, v in (oe4.get("logit_laip_metricas") or {}).items()},
        "logit_vuln_coef": recs(oe4.get("logit_vuln_coef")),
        "logit_vuln_metricas": {k: _safe(v) for k, v in (oe4.get("logit_vuln_metricas") or {}).items()},
        "dist_laip": {str(k): int(v) for k, v in dist_laip.items()},
        "dist_vuln": {str(k): int(v) for k, v in dist_vuln.items()},
    }


# ---------------- HTML TEMPLATE ----------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es-GT">
<head>
<meta charset="UTF-8">
<title>Dashboard — Auditoría E-Gov Suroccidente Guatemala</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --primary:#1F4E78; --primary-light:#5B9BD5;
    --oe1:#5B9BD5; --oe2:#70AD47; --oe3:#C00000; --oe4:#7030A0;
    --success:#70AD47; --warning:#ED7D31; --danger:#C00000;
    --neutral-50:#F8F9FA; --neutral-100:#E9ECEF; --neutral-200:#DEE2E6;
    --neutral-700:#495057; --neutral-900:#212529;
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
    margin:0; background:var(--neutral-50); color:var(--neutral-900); line-height:1.5; }
  header.top { background:linear-gradient(135deg,var(--primary),var(--primary-light));
    color:white; padding:1.5rem 2rem 1rem; box-shadow:0 2px 8px rgba(0,0,0,0.1); }
  header.top h1 { margin:0 0 0.25rem; font-size:1.45rem; }
  header.top p { margin:0; opacity:0.92; font-size:0.88rem; }
  nav.oe-nav { position:sticky; top:0; z-index:50; background:white;
    border-bottom:1px solid var(--neutral-200); box-shadow:0 2px 4px rgba(0,0,0,0.04);
    display:flex; overflow-x:auto; }
  nav.oe-nav a { flex:1 1 0; min-width:150px; text-align:center; padding:0.85rem 0.6rem;
    text-decoration:none; color:var(--neutral-700); font-weight:600; font-size:0.92rem;
    border-bottom:3px solid transparent; transition:all 0.15s; white-space:nowrap; }
  nav.oe-nav a:hover { background:var(--neutral-50); color:var(--primary); }
  nav.oe-nav a.oe1:hover,nav.oe-nav a.oe1.active { border-bottom-color:var(--oe1); color:var(--oe1); }
  nav.oe-nav a.oe2:hover,nav.oe-nav a.oe2.active { border-bottom-color:var(--oe2); color:var(--oe2); }
  nav.oe-nav a.oe3:hover,nav.oe-nav a.oe3.active { border-bottom-color:var(--oe3); color:var(--oe3); }
  nav.oe-nav a.oe4:hover,nav.oe-nav a.oe4.active { border-bottom-color:var(--oe4); color:var(--oe4); }
  nav.oe-nav a small { display:block; font-weight:400; font-size:0.75rem; margin-top:0.15rem; color:var(--neutral-700); }
  main { max-width:1400px; margin:0 auto; padding:1.5rem; }
  section { margin-bottom:2.5rem; scroll-margin-top:80px; }
  .oe-banner { border-radius:10px; padding:1.25rem 1.5rem; margin-bottom:1.25rem; color:white;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); }
  .oe-banner.oe1 { background:linear-gradient(135deg,var(--oe1),#4584B8); }
  .oe-banner.oe2 { background:linear-gradient(135deg,var(--oe2),#5B913A); }
  .oe-banner.oe3 { background:linear-gradient(135deg,var(--oe3),#A00000); }
  .oe-banner.oe4 { background:linear-gradient(135deg,var(--oe4),#5C2685); }
  .oe-banner h2 { margin:0 0 0.4rem; font-size:1.3rem; border:none; padding:0; color:white; }
  .oe-banner .pregunta { background:rgba(255,255,255,0.18); padding:0.65rem 0.85rem;
    border-radius:6px; margin:0.6rem 0 0; font-style:italic; font-size:0.9rem; }
  .oe-banner .pregunta strong { font-style:normal; }
  h2 { color:var(--primary); border-bottom:3px solid var(--primary-light);
    padding-bottom:0.4rem; margin-top:0; font-size:1.2rem; }
  .kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; }
  .kpi-card { background:white; border-radius:8px; padding:1rem; box-shadow:0 1px 3px rgba(0,0,0,0.08);
    border-left:4px solid var(--primary); }
  .kpi-card.oe1 { border-left-color:var(--oe1); } .kpi-card.oe2 { border-left-color:var(--oe2); }
  .kpi-card.oe3 { border-left-color:var(--oe3); } .kpi-card.oe4 { border-left-color:var(--oe4); }
  .kpi-label { font-size:0.78rem; color:var(--neutral-700); text-transform:uppercase;
    letter-spacing:0.5px; margin-bottom:0.4rem; }
  .kpi-value { font-size:1.7rem; font-weight:700; color:var(--neutral-900); }
  .kpi-value .unit { font-size:0.85rem; color:var(--neutral-700); font-weight:500; }
  .grid-2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(450px,1fr)); gap:1.5rem; }
  .card { background:white; border-radius:8px; padding:1.25rem; box-shadow:0 1px 3px rgba(0,0,0,0.08); }
  .card h3 { margin-top:0; color:var(--primary); font-size:1rem; }
  .chart-container { position:relative; height:320px; }
  table { width:100%; border-collapse:collapse; background:white; font-size:0.85rem; }
  th,td { padding:0.5rem 0.6rem; text-align:left; border-bottom:1px solid var(--neutral-100); }
  th { background:var(--primary); color:white; cursor:pointer; user-select:none; position:sticky; top:0; }
  th:hover { background:var(--primary-light); }
  tr:hover { background:var(--neutral-50); }
  table.stats th { background:var(--oe4); cursor:default; position:static; }
  table.stats { font-size:0.83rem; }
  table.stats td.num { text-align:right; font-variant-numeric:tabular-nums; }
  table.stats td.sig { font-weight:700; }
  table.stats tr.significativo { background:#FFF7E6; }
  .badge { display:inline-block; padding:0.15rem 0.5rem; border-radius:12px; font-size:0.75rem; font-weight:600; }
  .badge-good { background:#D4EDDA; color:#155724; } .badge-warn { background:#FFF3CD; color:#856404; }
  .badge-bad { background:#F8D7DA; color:#721C24; } .badge-sig { background:#E5D7F5; color:#4A1B7A; }
  .filter-bar { display:flex; gap:0.75rem; margin-bottom:0.75rem; flex-wrap:wrap; }
  .filter-bar input,.filter-bar select { padding:0.4rem 0.6rem; border:1px solid var(--neutral-200);
    border-radius:4px; font-size:0.9rem; }
  .filter-bar input { flex:1; min-width:200px; }
  .table-wrapper { max-height:600px; overflow-y:auto; border:1px solid var(--neutral-200); border-radius:6px; }
  .metricas-modelo { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
    gap:0.5rem 1rem; background:#F4EFFA; padding:0.85rem 1rem; border-radius:6px; margin-bottom:0.85rem; font-size:0.85rem; }
  .metricas-modelo div { display:flex; justify-content:space-between; gap:0.5rem; }
  .metricas-modelo strong { color:var(--oe4); }
  .leyenda-test { font-size:0.82rem; color:var(--neutral-700); background:var(--neutral-50);
    padding:0.6rem 0.85rem; border-radius:6px; border-left:3px solid var(--oe4); margin-bottom:0.85rem; }
  footer { text-align:center; padding:1.5rem; color:var(--neutral-700); font-size:0.85rem; }
</style>
</head>
<body>

<header class="top">
  <h1>Auditoría Técnica de Portales E-Gov — Suroccidente de Guatemala</h1>
  <p>Generado el __FECHA__ · __MODO__ · Maestría en Estadística Aplicada</p>
</header>

<nav class="oe-nav" id="oe-nav">
  <a href="#resumen" data-section="resumen">Resumen<small>KPIs generales</small></a>
  <a href="#oe1" class="oe1" data-section="oe1">OE1<small>Rendimiento y accesibilidad</small></a>
  <a href="#oe2" class="oe2" data-section="oe2">OE2<small>Frescura y transparencia</small></a>
  <a href="#oe3" class="oe3" data-section="oe3">OE3<small>Seguridad básica</small></a>
  <a href="#oe4" class="oe4" data-section="oe4">OE4<small>Análisis categórico</small></a>
  <a href="#tabla" data-section="tabla">Detalle<small>Tabla por municipio</small></a>
</nav>

<main>

<section id="resumen">
  <h2>Resumen general</h2>
  <p style="color:var(--neutral-700); margin-top:-0.25rem; font-size:0.95rem;">
    Indicadores clave de las __TOTAL_MUN__ municipalidades evaluadas, por objetivo específico.
  </p>
  <div class="kpi-grid" id="kpi-grid"></div>
</section>

<section id="oe1">
  <div class="oe-banner oe1">
    <h2>OE1 — Rendimiento técnico y accesibilidad móvil</h2>
    <div>Parámetros de rendimiento y adaptabilidad móvil (Web Vitals, viewport, peso).</div>
    <div class="pregunta"><strong>Pregunta auxiliar 1:</strong> ¿Cuál es el nivel de rendimiento técnico
      (tiempos de carga, optimización móvil, peso de página) y las principales barreras de accesibilidad
      que presentan los portales web municipales evaluados?</div>
  </div>
  <div class="grid-2">
    <div class="card"><h3>Distribución del score de rendimiento (0–100)</h3>
      <div class="chart-container"><canvas id="chart-perf-dist"></canvas></div></div>
    <div class="card"><h3>Tiempo de carga total por departamento</h3>
      <div class="chart-container"><canvas id="chart-perf-dep"></canvas></div></div>
  </div>
</section>

<section id="oe2">
  <div class="oe-banner oe2">
    <h2>OE2 — Frecuencia de actualización y transparencia LAIP</h2>
    <div>Cumplimiento de las secciones estructurales del Decreto 57-2008.</div>
    <div class="pregunta"><strong>Pregunta auxiliar 2:</strong> ¿Cuál es la frecuencia de actualización
      histórica de estos portales y la proporción que dispone de los apartados estructurales de
      transparencia y servicios exigidos por el Decreto 57-2008?</div>
  </div>
  <div class="grid-2">
    <div class="card"><h3>% de portales con cada sección LAIP</h3>
      <div class="chart-container"><canvas id="chart-laip"></canvas></div></div>
    <div class="card"><h3>Cumplimiento LAIP promedio por departamento</h3>
      <div class="chart-container"><canvas id="chart-laip-dep"></canvas></div></div>
  </div>
</section>

<section id="oe3">
  <div class="oe-banner oe3">
    <h2>OE3 — Seguridad básica de los servidores</h2>
    <div>Validez SSL/TLS, encabezados HTTP de seguridad (OWASP) y forzado de HTTPS.</div>
    <div class="pregunta"><strong>Pregunta auxiliar 3:</strong> ¿Qué proporción de las plataformas
      analizadas presenta vulnerabilidades en sus protocolos de seguridad básicos (certificados SSL/TLS,
      encabezados HTTP de seguridad y forzado de HTTPS)?</div>
  </div>
  <div class="grid-2">
    <div class="card"><h3>Headers de seguridad HTTP presentes</h3>
      <div class="chart-container"><canvas id="chart-headers"></canvas></div></div>
    <div class="card"><h3>Tiempo de carga vs score de seguridad</h3>
      <div class="chart-container"><canvas id="chart-scatter"></canvas></div></div>
  </div>
</section>

<section id="oe4">
  <div class="oe-banner oe4">
    <h2>OE4 — Análisis de datos categóricos</h2>
    <div>Pruebas no paramétricas (χ², Fisher, V de Cramér) y regresión logística binaria.</div>
    <div class="pregunta"><strong>Pregunta auxiliar 4:</strong> ¿Existen asociaciones estadísticamente
      significativas (α = 0.05) entre el cumplimiento del Decreto 57-2008 y las variables operativas de
      los portales (departamento, condición de cabecera departamental, calidad técnica, tipo de hosting),
      evaluadas mediante pruebas no paramétricas y modelos de regresión logística?</div>
  </div>
  <div id="oe4-content"></div>
</section>

<section id="tabla">
  <h2>Tabla detallada por municipalidad</h2>
  <div class="filter-bar">
    <input type="text" id="filter-text" placeholder="Buscar municipio / URL...">
    <select id="filter-dep"><option value="">Todos los departamentos</option></select>
    <select id="filter-reach">
      <option value="">Todos los estados</option>
      <option value="true">Solo alcanzables</option>
      <option value="false">Solo no alcanzables</option>
    </select>
  </div>
  <div class="table-wrapper">
    <table id="tabla-municipios"><thead><tr id="tabla-head"></tr></thead><tbody id="tabla-body"></tbody></table>
  </div>
  <p style="font-size:0.85rem; color:var(--neutral-700); margin-top:0.5rem;">
    <span id="contador-filtro"></span> · Clic en encabezados para ordenar.</p>
</section>

</main>

<footer>
  Datos generados por <strong>egov-audit</strong> · Python (pandas, scipy, statsmodels) y Chart.js<br>
  Auditoría académica — Respeta robots.txt y solo accede a contenido público.
</footer>

<script>
const DATA = __DATA_JSON__;
const COLOR = { oe1:'#5B9BD5', oe2:'#70AD47', oe3:'#C00000', oe4:'#7030A0',
  good:'#70AD47', warn:'#ED7D31', bad:'#C00000', neutral:'#7F7F7F' };

function fmtNum(v, suf='') {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return 'N/D';
  if (typeof v === 'number' && !Number.isInteger(v)) v = v.toFixed(1);
  return v + suf;
}
function fmtP(p) { if (p===null||p===undefined) return 'N/D'; return p<0.001?'<0.001':p.toFixed(3); }

// ===== KPIs =====
const K = DATA.kpis;
const kpiDefs = [
  { label:'Municipios evaluados', value:K.total_municipios, unit:'', clase:'' },
  { label:'Alcanzables', value:K.reachable_pct, unit:'%', clase:'' },
  { label:'Departamentos', value:K.n_departamentos, unit:'', clase:'' },
];
if (K.uptime_medio !== null && K.uptime_medio !== undefined)
  kpiDefs.push({ label:'Uptime medio', value:K.uptime_medio, unit:'%', clase:'' });
kpiDefs.push(
  { label:'Tiempo carga medio', value:K.tiempo_carga_medio_ms, unit:' ms', clase:'oe1' },
  { label:'% con viewport móvil', value:K.pct_viewport, unit:'%', clase:'oe1' },
  { label:'Score OE1 medio', value:K.score_perf, unit:'/100', clase:'oe1' },
  { label:'Cumplimiento LAIP', value:K.laip_medio, unit:'%', clase:'oe2' },
  { label:'Score OE2 medio', value:K.score_fresh, unit:'/100', clase:'oe2' },
  { label:'% con SSL válido', value:K.pct_ssl_ok, unit:'%', clase:'oe3' },
  { label:'% con HSTS', value:K.pct_hsts, unit:'%', clase:'oe3' },
  { label:'% redirige a HTTPS', value:K.pct_redirige_https, unit:'%', clase:'oe3' },
  { label:'Score OE3 medio', value:K.score_sec, unit:'/100', clase:'oe3' }
);
if (K.pct_laip_mayoria !== null && K.pct_laip_mayoria !== undefined)
  kpiDefs.push({ label:'% LAIP ≥ mayoría', value:K.pct_laip_mayoria, unit:'%', clase:'oe2' });
if (K.pct_laip_pleno !== null && K.pct_laip_pleno !== undefined)
  kpiDefs.push({ label:'% LAIP pleno (7/7)', value:K.pct_laip_pleno, unit:'%', clase:'oe2' });
if (K.pct_vulnerable !== null && K.pct_vulnerable !== undefined)
  kpiDefs.push({ label:'% con vulnerabilidad', value:K.pct_vulnerable, unit:'%', clase:'oe3' });

const kpiGrid = document.getElementById('kpi-grid');
kpiDefs.forEach(k => {
  const div = document.createElement('div');
  div.className = 'kpi-card ' + k.clase;
  div.innerHTML = `<div class="kpi-label">${k.label}</div>
    <div class="kpi-value">${fmtNum(k.value)}<span class="unit">${k.unit}</span></div>`;
  kpiGrid.appendChild(div);
});

// ===== OE1 =====
new Chart(document.getElementById('chart-perf-dist'), {
  type:'bar',
  data:{ labels:DATA.distribucion.labels,
    datasets:[{ label:'OE1 Rendimiento', data:DATA.distribucion.performance, backgroundColor:COLOR.oe1 }] },
  options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
    scales:{ x:{title:{display:true,text:'Score (0–100)'}}, y:{beginAtZero:true,title:{display:true,text:'Municipalidades'}} } }
});
const deps = Object.keys(DATA.por_departamento).sort();
new Chart(document.getElementById('chart-perf-dep'), {
  type:'bar',
  data:{ labels:deps, datasets:[{ label:'Tiempo medio (ms)',
    data:deps.map(d=>DATA.por_departamento[d].tiempo_carga_ms), backgroundColor:COLOR.oe1 }] },
  options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
    scales:{ y:{beginAtZero:true,title:{display:true,text:'ms'}} } }
});

// ===== OE2 =====
const laipCats = Object.keys(DATA.laip);
new Chart(document.getElementById('chart-laip'), {
  type:'bar',
  data:{ labels:laipCats, datasets:[{ label:'% con la sección',
    data:laipCats.map(c=>DATA.laip[c]),
    backgroundColor:laipCats.map(c=>{const v=DATA.laip[c]; return v>=70?COLOR.good:v>=40?COLOR.warn:COLOR.bad;}) }] },
  options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
    scales:{x:{beginAtZero:true,max:100}}, plugins:{legend:{display:false}} }
});
new Chart(document.getElementById('chart-laip-dep'), {
  type:'bar',
  data:{ labels:deps, datasets:[{ label:'% LAIP medio',
    data:deps.map(d=>DATA.por_departamento[d].laip_pct), backgroundColor:COLOR.oe2 }] },
  options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
    scales:{ y:{beginAtZero:true,max:100,title:{display:true,text:'%'}} } }
});

// ===== OE3 =====
const headers = Object.keys(DATA.headers);
new Chart(document.getElementById('chart-headers'), {
  type:'bar',
  data:{ labels:headers, datasets:[{ label:'% con el header',
    data:headers.map(h=>DATA.headers[h]),
    backgroundColor:headers.map(h=>DATA.headers[h]>=50?COLOR.good:COLOR.bad) }] },
  options:{ responsive:true, maintainAspectRatio:false,
    scales:{y:{beginAtZero:true,max:100,title:{display:true,text:'%'}}}, plugins:{legend:{display:false}} }
});
const scatterData = DATA.municipios
  .filter(m=>m.tiempo_total_ms && m.score_local_security!==null)
  .map(m=>({x:m.tiempo_total_ms, y:m.score_local_security, label:m.municipio}));
new Chart(document.getElementById('chart-scatter'), {
  type:'scatter',
  data:{ datasets:[{ label:'Municipalidades', data:scatterData, backgroundColor:COLOR.oe3, pointRadius:5, pointHoverRadius:7 }] },
  options:{ responsive:true, maintainAspectRatio:false,
    plugins:{ tooltip:{callbacks:{label:ctx=>`${ctx.raw.label}: ${ctx.raw.x.toFixed(0)} ms, score ${ctx.raw.y}/100`}}, legend:{display:false} },
    scales:{ x:{title:{display:true,text:'Tiempo de carga (ms)'}}, y:{title:{display:true,text:'Score OE3'},min:0,max:100} } }
});

// ===== OE4 =====
function renderOE4() {
  const cont = document.getElementById('oe4-content');
  const o = DATA.oe4;
  if (!o || !o.disponible) {
    cont.innerHTML = `<div class="card"><p>No fue posible ejecutar OE4: ${o?(o.razon||'sin datos'):'sin datos'}.
      Requiere la tabla consolidada (varias corridas) o un resultados.csv con las columnas necesarias.</p></div>`;
    return;
  }
  const distLaip=o.dist_laip||{}, distVuln=o.dist_vuln||{};
  cont.innerHTML = `
  <div class="leyenda-test"><strong>Cómo leer:</strong> filas amarillas = asociación significativa (p&lt;0.05).
    <em>p_recomendado</em> usa Fisher/Monte Carlo cuando hay frecuencias esperadas &lt;5; si no, χ².
    <em>V de Cramér</em> mide la magnitud (0.10 pequeña · 0.30 mediana · 0.50 grande).
    LAIP en 3 niveles: <strong>Pleno</strong> (los 7 apartados) · <strong>Limitado</strong> (mayoría, ≥4) · <strong>No_cumple</strong> (&lt;4).
    La regresión logística dicotomiza en "alcanza mayoría" (Pleno+Limitado) vs No_cumple.
    Vulnerable = sin SSL válido, sin HTTPS forzado, o sin HSTS+XFO+CSP.</div>
  <div class="grid-2">
    <div class="card"><h3>Distribución del Nivel LAIP (3 categorías)</h3>
      <div class="chart-container" style="height:230px;"><canvas id="chart-dist-laip"></canvas></div></div>
    <div class="card"><h3>Distribución de Vulnerabilidad</h3>
      <div class="chart-container" style="height:230px;"><canvas id="chart-dist-vuln"></canvas></div></div>
  </div>
  <div class="card" style="margin-top:1rem;"><h3>χ²/Fisher — Nivel LAIP vs predictores</h3>${chiTable(o.chi2_laip)}</div>
  <div class="card" style="margin-top:1rem;"><h3>χ²/Fisher — Vulnerabilidad vs predictores</h3>${chiTable(o.chi2_vuln)}</div>
  <div class="card" style="margin-top:1rem;"><h3>Regresión logística — LAIP (positivo = alcanza mayoría)</h3>
    ${modelMetrics(o.logit_laip_metricas)}${logitTable(o.logit_laip_coef)}</div>
  <div class="card" style="margin-top:1rem;"><h3>Regresión logística — Vulnerabilidad (positivo = Vulnerable)</h3>
    ${modelMetrics(o.logit_vuln_metricas)}${logitTable(o.logit_vuln_coef)}</div>`;

  const dl=Object.keys(distLaip);
  const colorLaip = l => (l==='Pleno'||l==='Cumple') ? COLOR.good : (l==='Limitado') ? COLOR.warn : COLOR.bad;
  if (dl.length) new Chart(document.getElementById('chart-dist-laip'), { type:'doughnut',
    data:{ labels:dl, datasets:[{ data:dl.map(l=>distLaip[l]), backgroundColor:dl.map(colorLaip) }] },
    options:{responsive:true,maintainAspectRatio:false} });
  const dv=Object.keys(distVuln);
  if (dv.length) new Chart(document.getElementById('chart-dist-vuln'), { type:'doughnut',
    data:{ labels:dv, datasets:[{ data:dv.map(l=>distVuln[l]), backgroundColor:dv.map(l=>l==='Vulnerable'?COLOR.bad:COLOR.good) }] },
    options:{responsive:true,maintainAspectRatio:false} });
}
function chiTable(rows) {
  if (!rows||!rows.length) return '<p>Datos insuficientes para las pruebas χ².</p>';
  const head = `<thead><tr><th>Predictor</th><th>n</th><th>Prueba</th><th>p</th><th>Sig</th><th>V Cramér</th><th>Magnitud</th></tr></thead>`;
  const body = rows.map(r=>`<tr class="${r.significativo_alfa005?'significativo':''}">
    <td>${r.predictor}</td><td class="num">${r.n}</td><td>${r.prueba_recomendada}</td>
    <td class="num sig">${fmtP(r.p_recomendado)}</td>
    <td>${r.significativo_alfa005?'<span class="badge badge-sig">Sí</span>':'<span class="badge">No</span>'}</td>
    <td class="num">${fmtNum(r.V_cramer)}</td><td>${r.magnitud_asociacion}</td></tr>`).join('');
  return `<table class="stats">${head}<tbody>${body}</tbody></table>`;
}
function logitTable(rows) {
  if (!rows||!rows.length) return '<p>El modelo no pudo ajustarse (ver métricas / reporte Excel).</p>';
  const head = `<thead><tr><th>Término</th><th>Coef (β)</th><th>p</th><th>OR</th><th>IC95% OR</th><th>Sig</th></tr></thead>`;
  const body = rows.map(r=>`<tr class="${r.significativo_alfa005?'significativo':''}">
    <td>${r.termino}</td><td class="num">${fmtNum(r.coef)}</td><td class="num sig">${fmtP(r.p_valor)}</td>
    <td class="num">${fmtNum(r.OR)}</td><td class="num">[${fmtNum(r.IC95_OR_low)} ; ${fmtNum(r.IC95_OR_high)}]</td>
    <td>${r.significativo_alfa005?'<span class="badge badge-sig">Sí</span>':'<span class="badge">No</span>'}</td></tr>`).join('');
  return `<table class="stats">${head}<tbody>${body}</tbody></table>`;
}
function modelMetrics(m) {
  if (!m||Object.keys(m).length===0) return '';
  if (m.error) return `<div class="metricas-modelo"><div><strong>Nota:</strong> ${m.error}</div></div>`;
  const items=[['n',m.n_observaciones],['Pseudo R² McFadden',m.pseudo_R2_McFadden],['AIC',m.aic],
    ['BIC',m.bic],['p LR modelo',fmtP(m.p_LR_modelo)],['Convergió',m.convergio?'Sí':'No']];
  return `<div class="metricas-modelo">${items.map(([k,v])=>`<div><span>${k}</span><strong>${v??'N/D'}</strong></div>`).join('')}</div>`;
}
renderOE4();

// ===== Tabla =====
const ES_CONSOLIDADO = !!K.es_consolidado;
const COLUMNAS = [
  {col:'municipio', lab:'Municipio'}, {col:'departamento', lab:'Departamento'},
  {col:'reachable', lab:'Estado', tipo:'bool'},
];
if (ES_CONSOLIDADO) COLUMNAS.push({col:'uptime_pct', lab:'Uptime %', tipo:'pct'});
COLUMNAS.push(
  {col:'tiempo_total_ms', lab:'Carga (ms)', tipo:'ms'},
  {col:'score_local_performance', lab:'OE1', tipo:'score'},
  {col:'score_local_security', lab:'OE3', tipo:'score'},
  {col:'laip_pct_cumplimiento', lab:'LAIP %', tipo:'pct'},
  {col:'ssl_ok', lab:'SSL', tipo:'bool'}
);
if (ES_CONSOLIDADO) {
  COLUMNAS.push({col:'cumple_LAIP', lab:'Cumple LAIP', tipo:'bin'});
  COLUMNAS.push({col:'tiene_vulnerabilidad', lab:'Vulnerable', tipo:'binbad'});
}

const thead=document.getElementById('tabla-head');
COLUMNAS.forEach(c=>{ const th=document.createElement('th'); th.dataset.col=c.col; th.textContent=c.lab; thead.appendChild(th); });

const tbody=document.getElementById('tabla-body');
const contador=document.getElementById('contador-filtro');
const filterText=document.getElementById('filter-text');
const filterDep=document.getElementById('filter-dep');
const filterReach=document.getElementById('filter-reach');
let sortCol='municipio', sortAsc=true, visibleData=[...DATA.municipios];

[...new Set(DATA.municipios.map(m=>m.departamento).filter(Boolean))].sort().forEach(d=>{
  const o=document.createElement('option'); o.value=d; o.textContent=d; filterDep.appendChild(o); });

function badgeScore(v){ if(v===null||v===undefined)return '<span class="badge">N/D</span>';
  const c=v>=70?'badge-good':v>=40?'badge-warn':'badge-bad'; return `<span class="badge ${c}">${v}</span>`; }
function badgeBool(v){ if(v===null||v===undefined)return '<span class="badge">N/D</span>';
  return v?'<span class="badge badge-good">Sí</span>':'<span class="badge badge-bad">No</span>'; }
function cell(m,c){
  const v=m[c.col];
  if(c.tipo==='bool') return badgeBool(v);
  if(c.tipo==='score') return badgeScore(v);
  if(c.tipo==='ms') return v!=null?Math.round(v):'N/D';
  if(c.tipo==='pct') return v!=null?(+v).toFixed(1)+'%':'N/D';
  if(c.tipo==='bin') return v===null||v===undefined?'<span class="badge">N/D</span>':(v?'<span class="badge badge-good">Sí</span>':'<span class="badge badge-bad">No</span>');
  if(c.tipo==='binbad') return v===null||v===undefined?'<span class="badge">N/D</span>':(v?'<span class="badge badge-bad">Sí</span>':'<span class="badge badge-good">No</span>');
  return v!=null?v:'';
}
function render(){
  tbody.innerHTML='';
  visibleData.forEach(m=>{ const tr=document.createElement('tr');
    tr.innerHTML=COLUMNAS.map(c=>`<td>${cell(m,c)}</td>`).join(''); tbody.appendChild(tr); });
  contador.textContent=`Mostrando ${visibleData.length} de ${DATA.municipios.length} municipalidades`;
}
function applyFilters(){
  const txt=filterText.value.toLowerCase(), dep=filterDep.value, reach=filterReach.value;
  visibleData=DATA.municipios.filter(m=>{
    if(txt && !((m.municipio||'').toLowerCase().includes(txt)||(m.url||'').toLowerCase().includes(txt))) return false;
    if(dep && m.departamento!==dep) return false;
    if(reach==='true' && !m.reachable) return false;
    if(reach==='false' && m.reachable) return false;
    return true; });
  applySort();
}
function applySort(){
  visibleData.sort((a,b)=>{ let va=a[sortCol],vb=b[sortCol];
    if(va==null)va=sortAsc?Infinity:-Infinity; if(vb==null)vb=sortAsc?Infinity:-Infinity;
    if(typeof va==='string')va=va.toLowerCase(); if(typeof vb==='string')vb=vb.toLowerCase();
    if(va<vb)return sortAsc?-1:1; if(va>vb)return sortAsc?1:-1; return 0; });
  render();
}
thead.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{
  const c=th.dataset.col; if(sortCol===c)sortAsc=!sortAsc; else {sortCol=c;sortAsc=true;} applySort(); }));
filterText.addEventListener('input',applyFilters);
filterDep.addEventListener('change',applyFilters);
filterReach.addEventListener('change',applyFilters);
applyFilters();

// ===== nav activo =====
const sectionIds=['resumen','oe1','oe2','oe3','oe4','tabla'];
const navLinks=Array.from(document.querySelectorAll('nav.oe-nav a'));
function syncNav(){ const y=window.scrollY+100; let act=sectionIds[0];
  for(const id of sectionIds){ const el=document.getElementById(id); if(el && el.offsetTop<=y)act=id; }
  navLinks.forEach(a=>a.classList.toggle('active', a.dataset.section===act)); }
window.addEventListener('scroll',syncNav,{passive:true}); syncNav();
</script>
</body>
</html>
"""


def generar_dashboard(df: pd.DataFrame, *, output_path: Path = None) -> Path:
    """Genera el dashboard HTML autocontenido en data/reports/."""
    if df.empty:
        raise ValueError("DataFrame vacío.")

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"dashboard_{timestamp}.html"

    cols_tabla = [
        "municipio", "departamento", "url", "reachable", "uptime_pct",
        "https", "ttfb_ms", "tiempo_total_ms", "tamanio_kb",
        "tiene_viewport", "score_local_performance",
        "laip_pct_cumplimiento", "score_local_freshness",
        "ssl_ok", "ssl_estado_modal", "header_hsts", "redirige_a_https",
        "score_local_security", "cumple_LAIP", "tiene_vulnerabilidad",
    ]
    cols_existentes = [c for c in cols_tabla if c in df.columns]
    df_tabla = df[cols_existentes].copy()

    es_consol = "uptime_pct" in df.columns
    modo = "Estudio longitudinal (consolidado)" if es_consol else "Auditoría puntual"

    payload = {
        "kpis": _calcular_kpis(df),
        "por_departamento": _datos_por_departamento(df),
        "laip": _laip_cumplimiento(df),
        "headers": _headers_seguridad(df),
        "distribucion": _distribucion_scores(df),
        "municipios": _df_to_records(df_tabla),
        "oe4": _payload_oe4(df),
    }

    html = (HTML_TEMPLATE
            .replace("__FECHA__", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            .replace("__MODO__", modo)
            .replace("__TOTAL_MUN__", str(len(df)))
            .replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False)))

    output_path.write_text(html, encoding="utf-8")
    log.info("Dashboard HTML generado: %s", output_path)
    return output_path
