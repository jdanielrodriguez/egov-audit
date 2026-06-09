# Auditoría Técnica de Portales E-Gov del Suroccidente de Guatemala

Sistema automatizado de auditoría para evaluar el estado técnico, rendimiento, actualización y seguridad de los portales web oficiales de las municipalidades de la Región VI Suroccidente de Guatemala (Quetzaltenango, Retalhuleu, San Marcos, Suchitepéquez, Totonicapán y Sololá).

Proyecto de investigación — Maestría en Estadística Aplicada — Seminario de Investigación I.

El software opera en **dos modalidades**:

1. **Auditoría puntual** (`main.py`): una foto de los portales en un momento dado → Excel + dashboard. Útil para exploración rápida.
2. **Estudio longitudinal** (`run_daily.py` + GitHub Actions → `analizar.py`): recolección repetida a horas y días aleatorios durante el período de investigación, que se **consolida a un registro por portal** (la unidad de análisis de la tesis) antes de cualquier inferencia. Esta es la modalidad central del estudio.

> El estudio se limita a la Región VI Suroccidente (`config/municipios.yaml`).

## Correspondencia con los objetivos de la investigación

| Objetivo Específico | Módulo responsable | Métricas principales |
|---|---|---|
| **OE1** — Rendimiento y accesibilidad móvil | `src/audits/performance.py` | TTFB, tiempo de carga, peso de página, viewport móvil, lang, alt en imágenes |
| **OE2** — Frecuencia de actualización y transparencia | `src/audits/content_freshness.py` | Snapshots Wayback 2021–2026, intervalo entre actualizaciones, secciones LAIP |
| **OE3** — Vulnerabilidades de seguridad básica | `src/audits/security.py` | Estado SSL (válido/autofirmado/hostname_mismatch/inválido), TLS, headers HSTS/CSP/X-Frame-Options, forzado de HTTPS |
| **OE4** — Asociaciones estadísticas (datos categóricos) | `src/analysis/stats.py` (`analisis_oe4_completo`) | χ² de independencia, prueba exacta de Fisher / Monte Carlo, V de Cramér, regresión logística binaria de `cumple_LAIP` y `tiene_vulnerabilidad` |

## Instalación

```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
```

Variables de entorno opcionales (archivo `.env`):

```
PAGESPEED_API_KEY=tu_api_key_de_google_pagespeed_insights
USER_AGENT=EgovAuditBot/1.0 (investigacion-academica)
```

La API key de PageSpeed es **opcional** y gratuita: https://developers.google.com/speed/docs/insights/v5/get-started

## Uso

### Modalidad A — Auditoría puntual

```bash
python main.py --all                  # todos los portales del Suroccidente
python main.py --url https://...      # una sola URL ad-hoc
python main.py --departamento Sololá  # un departamento
python main.py --all --solo security  # solo una dimensión
python main.py --reporte              # regenerar Excel + dashboard desde resultados.csv
```

Descubrimiento de URLs faltantes:

```bash
python main.py --descubrir                 # Suroccidente → descubrimiento_urls.csv
```

### Modalidad B — Estudio longitudinal (la de la tesis)

**1) Una corrida de recolección** (la que repite GitHub Actions a horas aleatorias):

```bash
python run_daily.py                  # audita los 39 portales → data/daily/YYYY-MM.jsonl
python run_daily.py --rebuild-db     # además reconstruye el índice SQLite local
python run_daily.py --max 3          # solo 3 portales (debug)
```

**2) Consolidar y analizar** cuando hay datos acumulados:

```bash
python analizar.py                   # snapshots → consolidado + Excel (OE1–OE4) + dashboard HTML
python analizar.py --wayback         # además frescura histórica (consulta Wayback, hace red)
```

**3) Dashboard interactivo** (opcional, complementa al HTML estático):

```bash
streamlit run src/reports/streamlit_app.py
```

**4) Recolección automática en la nube:** ver [`DEPLOY_ACTIONS.md`](DEPLOY_ACTIONS.md) (guía local, no versionada) para configurar los dos workflows de GitHub Actions que dejan corriendo la recolección a días/horas aleatorios.

## Salidas

En `data/reports/`:
- **`auditoria_egov_suroccidente_*.xlsx`** — Excel con 16 hojas: resumen, descriptivas por OE, proporciones con IC95 Wilson, Kruskal-Wallis, correlaciones, disponibilidad (uptime), y 5 hojas de OE4 (χ²/Fisher para LAIP y vulnerabilidad, tablas de contingencia, regresiones logísticas con OR e IC95).
- **`dashboard_*.html`** — dashboard autocontenido: navegación por OE, banners con cada pregunta de investigación, KPIs (incluido uptime), gráficas Chart.js, sección OE4, tabla filtrable.
- **`graficas_*/`** — PNGs estáticos para la tesis.

## Esquema de datos

### Snapshot diario — `data/daily/YYYY-MM.jsonl` (1 línea por portal por corrida)
`run_id`, `run_ts` (hora de Guatemala), `run_date`, `run_hour`, identidad del portal, `reachable`, `ttfb_ms`, `tiempo_total_ms`, `tamanio_kb`, `tiene_viewport`, `https`, `redirige_a_https`, `ssl_estado`, headers de seguridad, `laip_*` (7 apartados). Append-only: es la **fuente de verdad versionada** en git.

### Tabla consolidada — `data/consolidated/` (1 fila por portal — **unidad de análisis**)
- `uptime_pct` = % de corridas exitosas sobre el total.
- Continuas (mediana + desviación, solo corridas exitosas): `ttfb_mediana`, `tiempo_total_mediana`, `tamanio_kb_mediana`.
- Modales (solo exitosas): `ssl_estado_modal`, `header_*_modal`, `viewport_modal`, `laip_*_modal`.
- **Variables dependientes:**
  - `cumple_LAIP` = 1 si están presentes **todos** los apartados obligatorios del Decreto 57-2008; 0 si falta al menos uno.
  - `tiene_vulnerabilidad` = 1 si: SSL inválido/autofirmado/hostname_mismatch, **o** sin redirección HTTPS, **o** ausencia simultánea de HSTS + X-Frame-Options + CSP.
- **Predictores:** `departamento`, `cabecera`, `tipo_hosting` (heurístico por dominio), `calidad_tecnica`.

> El índice SQLite `data/egov.db` y el CSV consolidado son **derivados regenerables** (no se versionan); se reconstruyen desde los JSONL con `analizar.py` o `store.rebuild_sqlite()`.

## Estructura del proyecto

```
egov-audit/
├── config/
│   ├── municipios.yaml          # Suroccidente curado (111 munis, 39 con portal)
│   └── settings.py
├── src/
│   ├── portales.py              # Carga/expansión de portales (compartido)
│   ├── scraper/                 # fetcher, discoverer
│   ├── audits/                  # performance (OE1), content_freshness (OE2), security (OE3)
│   ├── collect/                 # RECOLECCIÓN: store (JSONL+SQLite) + daily_run
│   ├── consolidate/             # CONSOLIDACIÓN: snapshots → 1 fila/portal + dependientes
│   ├── schedule/                # planner aleatorio + gate (GitHub Actions)
│   ├── analysis/                # stats: descriptiva, inferencial y OE4 categórico
│   └── reports/                 # generator (Excel), dashboard (HTML), streamlit_app
├── data/
│   ├── daily/                   # snapshots JSONL (versionado)
│   ├── consolidated/            # tabla final (derivado)
│   └── reports/                 # Excel / HTML / PNG
├── .github/workflows/           # planner.yml + runner.yml
├── main.py                      # auditoría puntual / descubrimiento / reportes
├── run_daily.py                 # una corrida de recolección (lo llama Actions)
└── analizar.py                  # consolida + reportes del estudio longitudinal
```

## Metodología

1. **Recolección:** cada portal se visita una vez por corrida, con User-Agent identificado y timeouts. La modalidad longitudinal repite la corrida a horas y días aleatorios para descorrelacionar el sesgo por hora del día y por día de la semana.
2. **Rendimiento (OE1):** TTFB, tiempo total, peso, viewport móvil, `lang`, `alt`.
3. **Frescura y transparencia (OE2):** snapshots de Wayback (2021–2026) y presencia de los apartados de los artículos 10–11 del Decreto 57-2008.
4. **Seguridad (OE3):** validación de la cadena SSL con clasificación única (`ssl_estado`), versión TLS, headers OWASP y forzado de HTTPS.
5. **Consolidación (anti-pseudoreplicación):** las mediciones repetidas se reducen a **un registro por portal** (mediana/moda + uptime) **antes** de cualquier inferencia. Tratar las corridas repetidas como observaciones independientes sería pseudoreplicación; el análisis siempre consume la tabla consolidada.
6. **Análisis descriptivo e inferencial:** medias, medianas, IQR, IC95 (Wilson para proporciones, t-Student para medias), Kruskal-Wallis entre departamentos, correlaciones Spearman.
7. **Análisis de datos categóricos (OE4):** χ² de independencia; prueba exacta de Fisher (2×2) o χ² Monte Carlo (R×C) cuando hay frecuencias esperadas <5; V de Cramér para la magnitud; y regresión logística binaria (`statsmodels`) de `cumple_LAIP` y `tiene_vulnerabilidad` con coeficientes, odds ratios, IC95, AIC, BIC y pseudo-R² de McFadden.

## Consideraciones éticas

- Solo se accede a información pública mediante peticiones HTTP estándar (sin bypass de autenticación ni envío de formularios).
- Se respeta `robots.txt` cuando está presente y se usa un User-Agent identificado.
- Una sola visita por portal por corrida (no DoS); la recolección se distribuye en el tiempo.
- Los datos recogidos son técnicos y públicos; no se procesan datos personales.

## Autor

José Daniel Rodríguez Rodríguez — Maestría en Estadística Aplicada — 2026.
