"""
Genera un dashboard HTML autocontenido con los resultados de la auditoría.

- Single-file HTML (sin servidor, sin build): se abre directamente en el navegador.
- Datos embebidos como JSON dentro del HTML.
- Gráficas interactivas con Chart.js (CDN).
- Ideal para presentación de tesis / defensa.

Secciones del dashboard:
1. KPIs principales (cards)
2. Distribución de scores agregados por OE
3. Rendimiento por departamento (boxplot via chart)
4. Cumplimiento LAIP por categoría
5. Seguridad: headers presentes vs ausentes
6. Tabla filtrable con todos los municipios
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import numpy as np

from config.settings import REPORTS_DIR
from src.logger import get_logger

log = get_logger(__name__)


def _safe(v):
    """Convierte valores no serializables a algo que JSON acepte."""
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
    """DataFrame → lista de dicts JSON-safe."""
    out = []
    for _, row in df.iterrows():
        d = {}
        for k, v in row.items():
            d[k] = _safe(v)
        out.append(d)
    return out


def _calcular_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """Calcula KPIs principales para las cards superiores."""
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

    return {
        "total_municipios": total,
        "reachable": reachable,
        "reachable_pct": round(reachable / total * 100, 1) if total else 0,
        "score_perf": media("score_local_performance"),
        "score_fresh": media("score_local_freshness"),
        "score_sec": media("score_local_security"),
        "pct_https": pct("https"),
        "pct_viewport": pct("tiene_viewport"),
        "pct_ssl_ok": pct("ssl_ok"),
        "pct_hsts": pct("header_hsts"),
        "pct_redirige_https": pct("redirige_a_https"),
        "laip_medio": media("laip_pct_cumplimiento"),
        "tiempo_carga_medio_ms": media("tiempo_total_ms"),
        "snapshots_medio": media("snapshots_unicos"),
        "dias_ultima_act": media("dias_desde_ultima_actualizacion"),
        "n_departamentos": df["departamento"].nunique() if "departamento" in df.columns else 0,
    }


def _datos_por_departamento(df: pd.DataFrame) -> Dict[str, Any]:
    """Agrega métricas por departamento para gráficas comparativas."""
    if "departamento" not in df.columns:
        return {}
    out: Dict[str, Any] = {}
    for dep, sub in df.groupby("departamento"):
        out[str(dep)] = {
            "n": len(sub),
            "score_perf": float(pd.to_numeric(sub["score_local_performance"], errors="coerce").mean() or 0)
                if "score_local_performance" in sub.columns else 0,
            "score_fresh": float(pd.to_numeric(sub["score_local_freshness"], errors="coerce").mean() or 0)
                if "score_local_freshness" in sub.columns else 0,
            "score_sec": float(pd.to_numeric(sub["score_local_security"], errors="coerce").mean() or 0)
                if "score_local_security" in sub.columns else 0,
            "tiempo_carga_ms": float(pd.to_numeric(sub["tiempo_total_ms"], errors="coerce").mean() or 0)
                if "tiempo_total_ms" in sub.columns else 0,
            "laip_pct": float(pd.to_numeric(sub["laip_pct_cumplimiento"], errors="coerce").mean() or 0)
                if "laip_pct_cumplimiento" in sub.columns else 0,
        }
    return out


def _laip_cumplimiento(df: pd.DataFrame) -> Dict[str, float]:
    cats = ["transparencia", "presupuesto", "compras", "personal", "servicios", "estructura", "contacto"]
    out = {}
    for c in cats:
        col = f"laip_{c}"
        if col in df.columns:
            out[c] = round(df[col].fillna(False).astype(bool).mean() * 100, 1)
        else:
            out[c] = 0.0
    return out


def _headers_seguridad(df: pd.DataFrame) -> Dict[str, float]:
    headers = {
        "HSTS": "header_hsts",
        "CSP": "header_csp",
        "X-Frame-Options": "header_x_frame_options",
        "X-Content-Type-Options": "header_x_content_type_options",
        "Referrer-Policy": "header_referrer_policy",
        "Permissions-Policy": "header_permissions_policy",
    }
    out = {}
    for label, col in headers.items():
        if col in df.columns:
            out[label] = round(df[col].fillna(False).astype(bool).mean() * 100, 1)
        else:
            out[label] = 0.0
    return out


def _distribucion_scores(df: pd.DataFrame) -> Dict[str, List[int]]:
    """Histograma binned para los 3 scores."""
    bins = [0, 20, 40, 60, 80, 100]
    labels = ["0-20", "21-40", "41-60", "61-80", "81-100"]
    out = {"labels": labels}
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
    --primary: #1F4E78;
    --primary-light: #5B9BD5;
    --success: #70AD47;
    --warning: #ED7D31;
    --danger: #C00000;
    --neutral-50: #F8F9FA;
    --neutral-100: #E9ECEF;
    --neutral-200: #DEE2E6;
    --neutral-700: #495057;
    --neutral-900: #212529;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    margin: 0;
    background: var(--neutral-50);
    color: var(--neutral-900);
    line-height: 1.5;
  }
  header {
    background: linear-gradient(135deg, var(--primary), var(--primary-light));
    color: white;
    padding: 2rem 2rem 1.5rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }
  header h1 { margin: 0 0 0.25rem; font-size: 1.5rem; }
  header p { margin: 0; opacity: 0.9; font-size: 0.9rem; }
  main { max-width: 1400px; margin: 0 auto; padding: 1.5rem; }
  section { margin-bottom: 2rem; }
  h2 {
    color: var(--primary);
    border-bottom: 3px solid var(--primary-light);
    padding-bottom: 0.4rem;
    margin-top: 0;
    font-size: 1.2rem;
  }
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
  }
  .kpi-card {
    background: white;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    border-left: 4px solid var(--primary);
  }
  .kpi-card.oe1 { border-left-color: var(--primary-light); }
  .kpi-card.oe2 { border-left-color: var(--success); }
  .kpi-card.oe3 { border-left-color: var(--danger); }
  .kpi-label {
    font-size: 0.78rem;
    color: var(--neutral-700);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.4rem;
  }
  .kpi-value {
    font-size: 1.7rem;
    font-weight: 700;
    color: var(--neutral-900);
  }
  .kpi-value .unit {
    font-size: 0.85rem;
    color: var(--neutral-700);
    font-weight: 500;
  }
  .grid-2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
    gap: 1.5rem;
  }
  .card {
    background: white;
    border-radius: 8px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  .card h3 { margin-top: 0; color: var(--primary); font-size: 1rem; }
  .chart-container { position: relative; height: 320px; }
  table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    font-size: 0.85rem;
  }
  th, td { padding: 0.5rem 0.6rem; text-align: left; border-bottom: 1px solid var(--neutral-100); }
  th { background: var(--primary); color: white; cursor: pointer; user-select: none; position: sticky; top: 0; }
  th:hover { background: var(--primary-light); }
  tr:hover { background: var(--neutral-50); }
  .badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
  }
  .badge-good { background: #D4EDDA; color: #155724; }
  .badge-warn { background: #FFF3CD; color: #856404; }
  .badge-bad  { background: #F8D7DA; color: #721C24; }
  .filter-bar {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }
  .filter-bar input, .filter-bar select {
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--neutral-200);
    border-radius: 4px;
    font-size: 0.9rem;
  }
  .filter-bar input { flex: 1; min-width: 200px; }
  .table-wrapper { max-height: 600px; overflow-y: auto; border: 1px solid var(--neutral-200); border-radius: 6px; }
  footer {
    text-align: center;
    padding: 1.5rem;
    color: var(--neutral-700);
    font-size: 0.85rem;
  }
  .legend-oe { display: flex; gap: 0.6rem; font-size: 0.8rem; margin-top: 0.75rem; flex-wrap: wrap; }
  .legend-oe span {
    padding: 0.25rem 0.7rem;
    border-radius: 4px;
    background: rgba(255,255,255,0.18);
    color: white;
    border: 1px solid rgba(255,255,255,0.3);
  }
</style>
</head>
<body>

<header>
  <h1>Auditoría Técnica de Portales E-Gov — Suroccidente de Guatemala</h1>
  <p>Generado el __FECHA__ · Investigación Seminario I · Ingeniería en Sistemas</p>
  <div class="legend-oe">
    <span><strong>OE1</strong>: Rendimiento y Accesibilidad</span>
    <span><strong>OE2</strong>: Frescura y Transparencia LAIP</span>
    <span><strong>OE3</strong>: Seguridad Básica</span>
  </div>
</header>

<main>

<section>
  <h2>Indicadores clave</h2>
  <div class="kpi-grid" id="kpi-grid"></div>
</section>

<section>
  <h2>Scores agregados por Objetivo Específico</h2>
  <div class="grid-2">
    <div class="card">
      <h3>Distribución de scores (0–100)</h3>
      <div class="chart-container"><canvas id="chart-scores"></canvas></div>
    </div>
    <div class="card">
      <h3>Promedio por departamento</h3>
      <div class="chart-container"><canvas id="chart-departamentos"></canvas></div>
    </div>
  </div>
</section>

<section>
  <h2>OE2 — Cumplimiento LAIP (Decreto 57-2008)</h2>
  <div class="grid-2">
    <div class="card">
      <h3>% de portales con cada sección de transparencia</h3>
      <div class="chart-container"><canvas id="chart-laip"></canvas></div>
    </div>
    <div class="card">
      <h3>Tiempo de carga vs Score de seguridad</h3>
      <div class="chart-container"><canvas id="chart-scatter"></canvas></div>
    </div>
  </div>
</section>

<section>
  <h2>OE3 — Headers de seguridad HTTP presentes</h2>
  <div class="card">
    <div class="chart-container" style="height: 280px;"><canvas id="chart-headers"></canvas></div>
  </div>
</section>

<section>
  <h2>Tabla detallada por municipalidad</h2>
  <div class="filter-bar">
    <input type="text" id="filter-text" placeholder="Buscar municipio / URL...">
    <select id="filter-dep">
      <option value="">Todos los departamentos</option>
    </select>
    <select id="filter-reach">
      <option value="">Todos los estados</option>
      <option value="true">Solo alcanzables</option>
      <option value="false">Solo no alcanzables</option>
    </select>
  </div>
  <div class="table-wrapper">
    <table id="tabla-municipios">
      <thead>
        <tr>
          <th data-col="municipio">Municipio</th>
          <th data-col="departamento">Departamento</th>
          <th data-col="reachable">Estado</th>
          <th data-col="https">HTTPS</th>
          <th data-col="tiempo_total_ms">Carga (ms)</th>
          <th data-col="score_local_performance">OE1</th>
          <th data-col="score_local_freshness">OE2</th>
          <th data-col="score_local_security">OE3</th>
          <th data-col="laip_pct_cumplimiento">LAIP %</th>
          <th data-col="ssl_ok">SSL</th>
        </tr>
      </thead>
      <tbody id="tabla-body"></tbody>
    </table>
  </div>
  <p style="font-size:0.85rem; color: var(--neutral-700); margin-top: 0.5rem;">
    <span id="contador-filtro"></span> · Clic en encabezados para ordenar.
  </p>
</section>

</main>

<footer>
  Datos generados por <strong>egov-audit</strong> · Análisis con Python (pandas, scipy) y Chart.js<br>
  Auditoría académica — Respeta robots.txt y solo accede a contenido público.
</footer>

<script>
const DATA = __DATA_JSON__;
const COLOR = {
  oe1: '#5B9BD5', oe2: '#70AD47', oe3: '#C00000',
  good: '#70AD47', warn: '#ED7D31', bad: '#C00000',
  neutral: '#7F7F7F'
};

// ===== KPIs =====
function fmtNum(v, suf='') {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return 'N/D';
  if (typeof v === 'number' && !Number.isInteger(v)) v = v.toFixed(1);
  return v + suf;
}

const kpiDefs = [
  { label: 'Municipios evaluados', value: DATA.kpis.total_municipios, unit: '', clase: '' },
  { label: 'Alcanzables', value: DATA.kpis.reachable_pct, unit: '%', clase: '' },
  { label: 'Departamentos', value: DATA.kpis.n_departamentos, unit: '', clase: '' },
  { label: 'Tiempo carga medio', value: DATA.kpis.tiempo_carga_medio_ms, unit: ' ms', clase: 'oe1' },
  { label: '% con HTTPS', value: DATA.kpis.pct_https, unit: '%', clase: 'oe1' },
  { label: '% con viewport móvil', value: DATA.kpis.pct_viewport, unit: '%', clase: 'oe1' },
  { label: 'Score OE1 medio', value: DATA.kpis.score_perf, unit: '/100', clase: 'oe1' },
  { label: 'Snapshots medios', value: DATA.kpis.snapshots_medio, unit: '', clase: 'oe2' },
  { label: 'Días desde última act.', value: DATA.kpis.dias_ultima_act, unit: '', clase: 'oe2' },
  { label: 'Cumplimiento LAIP', value: DATA.kpis.laip_medio, unit: '%', clase: 'oe2' },
  { label: 'Score OE2 medio', value: DATA.kpis.score_fresh, unit: '/100', clase: 'oe2' },
  { label: '% con SSL válido', value: DATA.kpis.pct_ssl_ok, unit: '%', clase: 'oe3' },
  { label: '% con HSTS', value: DATA.kpis.pct_hsts, unit: '%', clase: 'oe3' },
  { label: '% redirige a HTTPS', value: DATA.kpis.pct_redirige_https, unit: '%', clase: 'oe3' },
  { label: 'Score OE3 medio', value: DATA.kpis.score_sec, unit: '/100', clase: 'oe3' },
];

const kpiGrid = document.getElementById('kpi-grid');
kpiDefs.forEach(k => {
  const div = document.createElement('div');
  div.className = 'kpi-card ' + k.clase;
  div.innerHTML = `<div class="kpi-label">${k.label}</div>
    <div class="kpi-value">${fmtNum(k.value)}<span class="unit">${k.unit}</span></div>`;
  kpiGrid.appendChild(div);
});

// ===== Chart 1: Distribución de scores =====
new Chart(document.getElementById('chart-scores'), {
  type: 'bar',
  data: {
    labels: DATA.distribucion.labels,
    datasets: [
      { label: 'OE1 Rendimiento', data: DATA.distribucion.performance, backgroundColor: COLOR.oe1 },
      { label: 'OE2 Frescura/LAIP', data: DATA.distribucion.freshness, backgroundColor: COLOR.oe2 },
      { label: 'OE3 Seguridad', data: DATA.distribucion.security, backgroundColor: COLOR.oe3 },
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    scales: {
      x: { title: { display: true, text: 'Score (0–100)' } },
      y: { beginAtZero: true, title: { display: true, text: 'Municipalidades' } }
    }
  }
});

// ===== Chart 2: Por departamento =====
const deps = Object.keys(DATA.por_departamento).sort();
new Chart(document.getElementById('chart-departamentos'), {
  type: 'bar',
  data: {
    labels: deps,
    datasets: [
      { label: 'OE1', data: deps.map(d => DATA.por_departamento[d].score_perf), backgroundColor: COLOR.oe1 },
      { label: 'OE2', data: deps.map(d => DATA.por_departamento[d].score_fresh), backgroundColor: COLOR.oe2 },
      { label: 'OE3', data: deps.map(d => DATA.por_departamento[d].score_sec), backgroundColor: COLOR.oe3 },
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    scales: { y: { beginAtZero: true, max: 100, title: { display: true, text: 'Score promedio' } } }
  }
});

// ===== Chart 3: LAIP =====
const laipCats = Object.keys(DATA.laip);
new Chart(document.getElementById('chart-laip'), {
  type: 'bar',
  data: {
    labels: laipCats,
    datasets: [{
      label: '% de portales con la sección',
      data: laipCats.map(c => DATA.laip[c]),
      backgroundColor: laipCats.map(c => {
        const v = DATA.laip[c];
        return v >= 70 ? COLOR.good : v >= 40 ? COLOR.warn : COLOR.bad;
      })
    }]
  },
  options: {
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: false,
    scales: { x: { beginAtZero: true, max: 100 } },
    plugins: { legend: { display: false } }
  }
});

// ===== Chart 4: Scatter tiempo vs seguridad =====
const scatterData = DATA.municipios
  .filter(m => m.tiempo_total_ms && m.score_local_security !== null)
  .map(m => ({ x: m.tiempo_total_ms, y: m.score_local_security, label: m.municipio }));

new Chart(document.getElementById('chart-scatter'), {
  type: 'scatter',
  data: {
    datasets: [{
      label: 'Municipalidades',
      data: scatterData,
      backgroundColor: COLOR.oe1,
      pointRadius: 5, pointHoverRadius: 7,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      tooltip: {
        callbacks: {
          label: ctx => `${ctx.raw.label}: ${ctx.raw.x.toFixed(0)} ms, score ${ctx.raw.y}/100`
        }
      },
      legend: { display: false }
    },
    scales: {
      x: { title: { display: true, text: 'Tiempo de carga (ms)' } },
      y: { title: { display: true, text: 'Score OE3 Seguridad' }, min: 0, max: 100 }
    }
  }
});

// ===== Chart 5: Headers seguridad =====
const headers = Object.keys(DATA.headers);
new Chart(document.getElementById('chart-headers'), {
  type: 'bar',
  data: {
    labels: headers,
    datasets: [{
      label: '% portales con el header',
      data: headers.map(h => DATA.headers[h]),
      backgroundColor: headers.map(h => DATA.headers[h] >= 50 ? COLOR.good : COLOR.bad)
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    scales: { y: { beginAtZero: true, max: 100, title: { display: true, text: '%' } } },
    plugins: { legend: { display: false } }
  }
});

// ===== Tabla con filtros y ordenamiento =====
const tbody = document.getElementById('tabla-body');
const contador = document.getElementById('contador-filtro');
const filterText = document.getElementById('filter-text');
const filterDep = document.getElementById('filter-dep');
const filterReach = document.getElementById('filter-reach');

let sortCol = 'municipio';
let sortAsc = true;
let visibleData = [...DATA.municipios];

// Llenar dropdown de departamentos
const depsUnicos = [...new Set(DATA.municipios.map(m => m.departamento).filter(Boolean))].sort();
depsUnicos.forEach(d => {
  const opt = document.createElement('option');
  opt.value = d; opt.textContent = d;
  filterDep.appendChild(opt);
});

function badgeScore(v) {
  if (v === null || v === undefined) return '<span class="badge">N/D</span>';
  const cls = v >= 70 ? 'badge-good' : v >= 40 ? 'badge-warn' : 'badge-bad';
  return `<span class="badge ${cls}">${v}</span>`;
}

function badgeBool(v) {
  if (v === null || v === undefined) return '<span class="badge">N/D</span>';
  return v ? '<span class="badge badge-good">Sí</span>' : '<span class="badge badge-bad">No</span>';
}

function render() {
  tbody.innerHTML = '';
  visibleData.forEach(m => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${m.municipio || ''}</td>
      <td>${m.departamento || ''}</td>
      <td>${badgeBool(m.reachable)}</td>
      <td>${badgeBool(m.https)}</td>
      <td>${m.tiempo_total_ms != null ? Math.round(m.tiempo_total_ms) : 'N/D'}</td>
      <td>${badgeScore(m.score_local_performance)}</td>
      <td>${badgeScore(m.score_local_freshness)}</td>
      <td>${badgeScore(m.score_local_security)}</td>
      <td>${m.laip_pct_cumplimiento != null ? m.laip_pct_cumplimiento.toFixed(1) + '%' : 'N/D'}</td>
      <td>${badgeBool(m.ssl_ok)}</td>
    `;
    tbody.appendChild(tr);
  });
  contador.textContent = `Mostrando ${visibleData.length} de ${DATA.municipios.length} municipalidades`;
}

function applyFilters() {
  const txt = filterText.value.toLowerCase();
  const dep = filterDep.value;
  const reach = filterReach.value;
  visibleData = DATA.municipios.filter(m => {
    if (txt && !((m.municipio||'').toLowerCase().includes(txt) || (m.url||'').toLowerCase().includes(txt))) return false;
    if (dep && m.departamento !== dep) return false;
    if (reach === 'true' && !m.reachable) return false;
    if (reach === 'false' && m.reachable) return false;
    return true;
  });
  applySort();
}

function applySort() {
  visibleData.sort((a, b) => {
    let va = a[sortCol], vb = b[sortCol];
    if (va == null) va = sortAsc ? Infinity : -Infinity;
    if (vb == null) vb = sortAsc ? Infinity : -Infinity;
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  });
  render();
}

document.querySelectorAll('#tabla-municipios th').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = true; }
    applySort();
  });
});

filterText.addEventListener('input', applyFilters);
filterDep.addEventListener('change', applyFilters);
filterReach.addEventListener('change', applyFilters);

applyFilters();
</script>
</body>
</html>
"""


def generar_dashboard(df: pd.DataFrame, *, output_path: Path = None) -> Path:
    """
    Genera dashboard HTML autocontenido.
    Si output_path no se especifica, se guarda en data/reports/.
    """
    if df.empty:
        raise ValueError("DataFrame vacío.")

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"dashboard_{timestamp}.html"

    # Selección de columnas para la tabla (mantener payload bajo)
    cols_tabla = [
        "municipio", "departamento", "url", "reachable", "status_code",
        "https", "ttfb_ms", "tiempo_total_ms", "tamanio_kb",
        "tiene_viewport", "tiene_lang", "imgs_pct_con_alt",
        "score_local_performance",
        "snapshots_unicos", "dias_desde_ultima_actualizacion",
        "laip_pct_cumplimiento", "score_local_freshness",
        "ssl_ok", "ssl_tls_version", "ssl_dias_restantes",
        "header_hsts", "header_csp", "redirige_a_https",
        "score_local_security",
    ]
    cols_existentes = [c for c in cols_tabla if c in df.columns]
    df_tabla = df[cols_existentes].copy()

    payload = {
        "kpis": _calcular_kpis(df),
        "por_departamento": _datos_por_departamento(df),
        "laip": _laip_cumplimiento(df),
        "headers": _headers_seguridad(df),
        "distribucion": _distribucion_scores(df),
        "municipios": _df_to_records(df_tabla),
    }

    html = HTML_TEMPLATE.replace(
        "__FECHA__", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ).replace(
        "__DATA_JSON__", json.dumps(payload, ensure_ascii=False)
    )

    output_path.write_text(html, encoding="utf-8")
    log.info("Dashboard HTML generado: %s", output_path)
    return output_path
