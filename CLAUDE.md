# CLAUDE.md — Contexto del proyecto `egov-audit`

> **Propósito de este archivo.** Es el contexto vivo del proyecto para que Claude
> (en Claude Code / cowork) lo entienda a fondo antes de trabajar: qué es, cómo
> empezó, cómo se opera, las reglas y permisos, y las decisiones metodológicas.
> **Este documento manda como contexto base.** Si el usuario lo edita, esas nuevas
> directrices reemplazan lo que digan las viejas: átate siempre a la versión actual
> de este archivo. Cuando hagas cambios relevantes al proyecto, actualízalo.
>
> Idioma del proyecto: **español**. Investigador y dueño del repo: **José Daniel
> Rodríguez** (Maestría en Estadística Aplicada).

---

## 1. Qué es el proyecto

Sistema en **Python** que audita los **portales web oficiales de las
municipalidades de la Región VI – Suroccidente de Guatemala**: Quetzaltenango,
Retalhuleu, San Marcos, Suchitepéquez, Totonicapán y Sololá. Es el soporte técnico
de una **tesis de Maestría en Estadística Aplicada**.

Objetivos específicos (OE):

| OE | Tema | Módulo | Métricas |
|----|------|--------|----------|
| **OE1** | Rendimiento y accesibilidad móvil | `src/audits/performance.py` | TTFB, tiempo de carga, peso, viewport móvil, `lang`, `alt` |
| **OE2** | Frecuencia de actualización y transparencia | `src/audits/content_freshness.py` | Wayback, apartados LAIP (Decreto 57-2008) |
| **OE3** | Vulnerabilidades de seguridad básica | `src/audits/security.py` | Estado SSL, versión TLS, headers HSTS/CSP/X-Frame-Options, forzado de HTTPS |
| **OE4** | Asociaciones estadísticas (datos categóricos) | `src/analysis/stats.py` | χ² de independencia, Fisher / Monte Carlo, V de Cramér, regresión logística binaria |

**Unidad de análisis:** un registro **por municipio** (tabla consolidada), NO cada
medición individual (ver §10, anti-pseudoreplicación).

---

## 2. Cómo empezó y cómo evolucionó

1. Nació como **auditoría puntual** (`main.py`): una foto de los portales → Excel + dashboard.
2. Se agregó el **OE4** (categórico) y se hizo el dashboard navegable por OE.
3. Se convirtió en **estudio longitudinal**: recolección repetida a horas y días
   aleatorios, **consolidada a 1 fila por municipio** antes de cualquier inferencia.
4. Se **limitó estrictamente al Suroccidente** (se eliminó por completo la idea de
   "municipios globales" que se exploró y descartó).
5. Se **automatizó en GitHub Actions**, disparado por **cron-job.org** vía
   `workflow_dispatch` (el `schedule` nativo de GitHub resultó poco fiable y se removió).
6. **LAIP pasó a 3 niveles ordinales** porque el "cumple estricto (7/7)" era
   degenerado (todos en 0) y no admitía inferencia.
7. Se gestionó el **anti-bot** de los WAF municipales: cabeceras de navegador real +
   **Playwright** como 2º intento. **Sin proxies.**
8. Se añadió `reachable_navegador` a la recolección para que el *uptime* refleje si
   un humano cargaría el sitio (no un bloqueo anti-bot).
9. Se **corrigió el planificador** para que la ventana sea **domingo→sábado** (antes
   planificaba lunes→domingo siguiente y desperdiciaba slots).
10. Se hizo robusta la **logística del OE4** ante separación cuasi-perfecta.

---

## 3. Reglas y permisos del proyecto (RESPETAR SIEMPRE)

**Git**
- Identidad: `Jose Daniel Rodriguez <dannyjose1112@hotmail.com>`. (Nunca usar la
  identidad heredada `walter.cordero@…`.)
- **NUNCA** agregar trailer de co-autor (`Co-Authored-By`) en los commits.
- **Commits temáticos**: separar los cambios por tema; no un único commit gigante.
- Rama de trabajo y principal: **`develop`**.
- **Antes de pushear**: validar que local y `origin/develop` están alineados
  (`git fetch` + `git rev-list --left-right --count origin/develop...develop`). Si
  `origin` divergió, hacer `rebase` antes. Pushear solo cuando el usuario lo pida.
- Los commits automáticos del bot en CI usan `egov-bot` y `[skip ci]`; no confundir
  con los del investigador.

**Scraping / ética**
- **NO proxies.** Solo simular navegación humana (User-Agent + cabeceras de navegador
  y, en el descubrimiento, Playwright). No resolver captchas, no forzar, no evadir.
- Solo información **pública** vía HTTP estándar. **Una visita por portal por corrida**
  (no DoS). Se respeta `robots.txt`.
- **NO modificar `config/municipios.yaml` automáticamente** — los cambios de URL van
  en `config/urls_overrides.json`.
- **NO borrar URLs caídas** — se registran (son dato de *uptime*) y se re-prueban.
- El estudio se limita al **Suroccidente** (`config/municipios.yaml`).

**Seguridad operativa**
- **Nunca** pegar secretos/tokens en respuestas ni en archivos versionados. En el
  pasado se filtraron una `PAGESPEED_API_KEY` y un PAT en el chat → **deben rotarse**.
- Secretos van en `.env` local o en *secrets* de GitHub Actions.

**Entorno de desarrollo**
- **Windows + PowerShell**; usar el intérprete del venv: `venv\Scripts\python.exe`.
- La consola Windows es **cp1252**: evitar emojis / caracteres Unicode (`✅`, `→`, `χ`)
  en `print`/`log` que van a stdout → usar `[OK]`, `->`, `chi-cuadrado`. (En CI/Linux
  es UTF-8 y no falla, pero el usuario corre en local.)
- Los **archivos temporales de análisis** (`_analisis*.py`, etc.) se **borran** al
  terminar; no se dejan en el árbol ni se commitean. Usar el scratchpad para temporales.
- Validar con el venv antes de commitear (sintaxis, imports, y una corrida de prueba
  si aplica).

---

## 4. Estructura y componentes

Dos modalidades de operación:

- **A — Auditoría puntual** (`main.py`): foto ad-hoc → `data/processed/resultados.csv` + Excel + dashboard.
- **B — Estudio longitudinal** (la de la tesis): `run_daily.py` (recolección) →
  JSONL → `analizar.py` (consolidación + reportes).

```
egov-audit/
├── config/
│   ├── municipios.yaml          # Suroccidente curado (NO editar auto; ~111 munis, 39 portales)
│   ├── urls_overrides.json      # reemplazos/descubrimientos fusionados en la carga
│   ├── url_registro.json        # historial y uptime del catálogo (eventos por municipio)
│   ├── urls_excluidas.json      # lista de veto editable (falsos positivos / fraudulentos)
│   ├── instituciones.yaml       # (opcional) entidades gubernamentales no municipales
│   └── settings.py              # rutas, USER_AGENT, HTTP_TIMEOUT=20, MAX_RETRIES=2, TZ (-6)
├── src/
│   ├── portales.py              # carga/expansión de portales + fusión de overrides
│   ├── scraper/                 # fetcher (headers navegador), discoverer, navegador (Playwright), url_updater
│   ├── audits/                  # performance (OE1), content_freshness (OE2), security (OE3)
│   ├── collect/                 # store (JSONL+SQLite), daily_run (una corrida)
│   ├── consolidate/             # consolidator: snapshots → 1 fila/municipio + variables OE4
│   ├── schedule/                # planner (plan aleatorio) + should_run (gate horario)
│   ├── analysis/                # stats: descriptiva, inferencial y OE4 categórico
│   └── reports/                 # generator (Excel), dashboard (HTML), streamlit_app
├── data/
│   ├── daily/                   # snapshots JSONL — FUENTE DE VERDAD (versionada)
│   ├── consolidated/            # tabla consolidada (derivado)
│   ├── processed/               # resultados.csv de la auditoría puntual
│   ├── reports/                 # Excel / HTML / PNG
│   └── egov.db                  # índice SQLite (derivado, gitignored)
├── .github/workflows/           # planner.yml + runner.yml + actualizar-urls.yml
├── main.py                      # auditoría puntual / descubrimiento / reportes
├── run_daily.py                 # una corrida de recolección (lo llama Actions)
├── analizar.py                  # consolida + reportes del estudio longitudinal
└── README.md                    # documentación pública
```

---

## 5. Cómo se GENERA la data (recolección)

Una corrida de recolección:

```bash
python run_daily.py                  # audita los 39 portales → data/daily/YYYY-MM.jsonl
python run_daily.py --rebuild-db     # además reconstruye el índice SQLite local
python run_daily.py --max 3          # solo 3 portales (debug)
```

Por cada portal, en una corrida:
1. `fetch(url)` HTTP con cabeceras de navegador real.
2. Si el cliente HTTP **no** lo alcanza → **un** 2º intento con navegador real
   (Playwright): `reachable_navegador` = True si el humano lo cargaría. No reintenta
   en bucle. Si Playwright no está instalado, se omite (sigue funcionando).
3. Métricas OE1/OE2/OE3 se extraen del **HTML del cliente HTTP** (no del navegador).
4. Se escribe un snapshot (1 línea) por portal en el JSONL del mes.

> El 2º intento con navegador es **opcional** localmente:
> `pip install playwright && playwright install chromium`. En la nube el workflow
> `runner.yml` instala Chromium siempre.

---

## 6. Cómo se GUARDA la data

- **`data/daily/YYYY-MM.jsonl`** — append-only, **fuente de verdad versionada en git**.
  Una línea = un portal en una corrida. Nunca se reescribe (sin conflictos de merge).
- **`data/egov.db`** (SQLite) — índice **derivado**, gitignored; se reconstruye con
  `run_daily.py --rebuild-db` o `store.rebuild_sqlite()`.
- **`data/consolidated/`** — tabla consolidada **derivada** (1 fila/municipio); la
  produce `analizar.py`.
- Esquema del snapshot: ver `SNAPSHOT_FIELDS` en `src/collect/store.py`. Campos clave:
  `run_id/run_ts/run_date/run_hour`, identidad del portal, `reachable`,
  `reachable_navegador`, `ttfb_ms`, `tiempo_total_ms`, `tamanio_kb`, `https`,
  `ssl_estado`, headers de seguridad, `laip_*` (7 apartados).

---

## 7. Plan de recolección (planificación aleatoria)

- **`src/schedule/planner.py`** corre el **domingo a primera hora** y sortea la semana:
  - **Ventana domingo→sábado**: el propio domingo que corre = día 1; el sábado = día 7.
    **Nunca** planifica para el domingo siguiente (ese día el planner regenera el plan).
  - `MIN_DIAS_SEMANA = 3`, `MAX_DIAS_SEMANA = 7` (la semana completa está permitida).
  - `CORRIDAS_POR_DIA = 7` a horas aleatorias. El primer día solo sortea horas futuras.
  - Escribe `schedule/plan-semana.json`.
- **`src/schedule/should_run.py`** es el *gate*: el runner se dispara cada hora y este
  script compara fecha+hora local (GT) con los slots; solo corre si coincide (ignora
  minutos → tolera retrasos del cron).
- **Zona horaria:** Guatemala fija **UTC-6**.
- **Automatización:** 3 workflows disparados por **cron-job.org** (`workflow_dispatch`),
  no por `schedule` nativo:
  - `planner.yml` — sortea la semana (domingos).
  - `runner.yml` — recolecta (cada hora + gate); instala Chromium.
  - `actualizar-urls.yml` — mantiene el catálogo (semanal, antes del planner); instala Chromium.
  - Ver `DEPLOY_ACTIONS.md` (guía local, no versionada) para el detalle de despliegue.

---

## 8. Cómo se ACTUALIZA la data / el catálogo de URLs

```bash
python main.py --descubrir                 # informe: busca URLs de municipios sin URL
python main.py --descubrir --escribir      # mantenimiento: verifica/reemplaza/descubre y escribe el catálogo
python main.py --descubrir-iap             # además busca portales de transparencia IAP
```

Lógica de `--escribir` (o del workflow `actualizar-urls`), por municipio:
- `vivo` (2xx/3xx) → se conserva.
- `restringido` (**401/403/429**) → el sitio **existe** pero bloquea al bot; **no** es
  caída ni motivo de reemplazo; no cuenta como fallo.
- `muerto` → **2º intento con navegador** (Playwright); solo si también falla cuenta
  como fallo. Solo tras **2 fallos confirmados seguidos** (`UMBRAL_FALLOS_REEMPLAZO=2`)
  se busca reemplazo con el descubridor.
- Resultados → `config/urls_overrides.json` (reemplazos/descubrimientos) y
  `config/url_registro.json` (historial). **Nunca** toca `municipios.yaml` ni borra caídas.

Catálogo:
- **`urls_overrides.json`**: `url`, `tipo_portal`, `fuente` (reemplazo|descubrimiento), `fecha`, `url_anterior`.
- **`url_registro.json`**: `fallos_consecutivos`, `ultima_verificacion`, lista de `eventos`
  (verificada_ok, reactivada, restringido, reemplazada, descubierta, caida).
- **`urls_excluidas.json`**: lista de veto editable (sitios fraudulentos / falsos
  positivos que el descubridor **omite siempre**). Además se descartan por origen los
  dominios no oficiales conocidos (`laip.gt`, `iap.gob.gt`: son de transparencia, no la web institucional).

---

## 9. Cómo se ANALIZA la data

Flujo longitudinal (la tesis):

```bash
python analizar.py                   # consolida → Excel (OE1–OE4) + dashboard HTML
python analizar.py --wayback         # además frescura histórica (consulta Wayback, red)
streamlit run src/reports/streamlit_app.py   # dashboard interactivo (opcional)
```

Flujo puntual (desde `data/processed/resultados.csv`):

```bash
python main.py --reporte             # solo Excel
python main.py --dashboard           # solo dashboard HTML
```

- **Siempre se analiza la tabla consolidada** (1 fila/municipio), nunca los snapshots
  crudos (anti-pseudoreplicación, §10).
- **OE4** (`analisis_oe4_completo`): χ²/Fisher/V de Cramér **son la inferencia válida**.
  La **regresión logística** puede **no converger** por separación cuasi-perfecta
  (muestra pequeña / categorías desbalanceadas): en ese caso `convergio=False`, los
  OR/IC no finitos se reportan como `NaN` (no `inf`) y hay una `nota`. No confiar en la
  logística mientras no converja; apoyarse en χ²/Fisher/Cramér.

---

## 10. Decisiones metodológicas clave

- **Anti-pseudoreplicación:** las corridas repetidas se reducen a **1 fila por
  municipio** (agrupando por `codigo_ine`, mediana/moda + uptime) **antes** de inferir.
  Un municipio que cambió de URL se trata como uno solo.
- **LAIP en 3 niveles ordinales:** `Pleno` (7/7 apartados), `Limitado` (≥4,
  `UMBRAL_MAYORIA_LAIP=4`), `No_cumple` (<4). Existe `cumple_mayoria_LAIP` (binaria)
  para la logística. El "cumple estricto 7/7" era degenerado (todos en 0).
- **Uptime = HTTP _o_ navegador** (`n_alcanzables`), pero las **métricas de contenido
  (TTFB/SSL/LAIP) salen SOLO del HTTP** (`n_exitosas`) para que sean comparables en
  toda la serie. Consecuencia: un sitio que da **403 siempre** tiene *uptime* (por
  navegador) pero **sin métricas** → su `nivel_laip` queda **`None`** (NO se marca
  falsamente como `No_cumple`).
- **403/401/429 = restringido, no caída.** Evita falsos positivos de sitios con WAF.
- **OE4 logística:** manejo explícito de la no-convergencia (ver §9).

---

## 11. Hallazgos actuales (instantánea — regenerar con `analizar.py`)

> Al **2026-06-27**: 2808 snapshots, 72 corridas, 39 portales, 11 días.

- **Disponibilidad** alta (uptime medio ~95%, mediana 100%). Caídas reales:
  **Cajolá** (TLS roto), **El Asintal** (404 + SSL), **Pajapita** (500). Tres sitios
  bloquean al bot el 100% del tiempo (**Quetzaltenango/Xela, Salcajá, San José
  Ojetenam**): vivos por navegador pero **no auditables por HTTP**.
- **OE1:** sitios livianos y rápidos, pero **solo ~37% tiene viewport móvil** → la
  brecha es de **accesibilidad móvil**, no de velocidad.
- **OE2:** **ningún municipio cumple los 7 apartados LAIP**; mediana de cumplimiento
  0%. Lo más sensible (compras/contrataciones 3%, presupuesto 9%, personal 9%) es lo
  más ausente. **Es el hallazgo central.**
- **OE3:** cifrado moderno y correcto (SSL válido, TLS 1.2/1.3), pero **~77%
  vulnerables** por **headers de configuración** (X-Frame-Options 0%, HSTS 9%, CSP
  20%, solo 65% fuerza HTTPS).
- **OE4:** **ninguna asociación significativa** (α=0.05) entre departamento/cabecera/
  hosting/calidad y LAIP o vulnerabilidad. Conclusión: las deficiencias son
  **sistémicas y transversales**, no de un subgrupo. La logística no converge (n chico).

---

## 12. Pendientes / a tener presente

- **3 sitios siempre-403** (incluida la cabecera Quetzaltenango): reportarlos como
  "no auditables por HTTP", no como caídos ni incumplidores. Posible mejora futura:
  extraer el HTML por navegador para medirles LAIP/SSL (cambiaría el alcance).
- **OE4 con n pequeño**: sin asociaciones significativas y logística sin converger;
  reevaluar al acumular más datos (o usar logística penalizada/Firth).
- **Rotar** los secretos que se filtraron en el chat (`PAGESPEED_API_KEY`, PAT).
- Caídas reales a vigilar: **Cajolá, El Asintal, Pajapita**.

---

## 13. Checklist para trabajar en este repo (agente)

1. Correr todo con **`venv\Scripts\python.exe`**; validar sintaxis/imports.
2. Temporales de análisis → **borrarlos** al terminar; no dejarlos en el árbol.
3. Evitar Unicode en salidas de consola (cp1252 en Windows).
4. Commits **temáticos**, **sin co-autor**, identidad `Jose Daniel Rodriguez
   <dannyjose1112@hotmail.com>`.
5. **Antes de pushear**: `git fetch` + verificar sync con `origin/develop`; rebase si divergió.
6. **Push solo cuando el usuario lo pida.**
7. Al cambiar comportamiento, actualizar `README.md` **y este `CLAUDE.md`**.
8. Respetar todas las reglas de §3 (sin proxies, no tocar `municipios.yaml`, solo
   Suroccidente, no borrar caídas, no exponer secretos).
