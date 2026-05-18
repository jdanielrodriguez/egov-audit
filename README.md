# Auditoría Técnica de Portales E-Gov del Suroccidente de Guatemala

Sistema automatizado de auditoría para evaluar el estado técnico, rendimiento, actualización y seguridad de los portales web oficiales de las municipalidades de la región Suroccidente de Guatemala (Quetzaltenango, Retalhuleu, San Marcos, Suchitepéquez, Totonicapán y Sololá).

Proyecto de investigación — Seminario I — Ingeniería en Sistemas.

## Correspondencia con los objetivos de la investigación

| Objetivo Específico | Módulo responsable | Métricas principales |
|---|---|---|
| **OE1** — Rendimiento y accesibilidad móvil | `src/audits/performance.py` | TTFB, tiempo de carga total, peso de página, recursos, viewport móvil, lang, alt en imágenes |
| **OE2** — Frecuencia de actualización y transparencia | `src/audits/content_freshness.py` | Snapshots Wayback Machine 2021–2026, intervalo entre actualizaciones, presencia de secciones LAIP |
| **OE3** — Vulnerabilidades de seguridad básica | `src/audits/security.py` | Validez SSL, días para expiración, versión TLS, headers HSTS/CSP/X-Frame-Options, exposición de servidor |

## Instalación

```bash
python -m venv venv
source venv/bin/activate         # Linux/Mac
# venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Variables de entorno opcionales (crear archivo `.env`):

```
PAGESPEED_API_KEY=tu_api_key_de_google_pagespeed_insights
USER_AGENT=EgovAuditBot/1.0 (investigacion-academica)
```

La API key de PageSpeed es **opcional** y gratuita: https://developers.google.com/speed/docs/insights/v5/get-started

## Uso

### 1. Auditoría completa de todas las municipalidades

```bash
python main.py --all
```

### 2. Auditar una sola URL

```bash
python main.py --url https://www.muniquetzaltenango.gob.gt
```

### 3. Auditar solo un departamento

```bash
python main.py --departamento Quetzaltenango
```

### 4. Ejecutar solo un tipo de auditoría

```bash
python main.py --all --solo performance
python main.py --all --solo freshness
python main.py --all --solo security
```

### 5. Generar reporte final con análisis estadístico

```bash
python main.py --reporte
```

Los reportes se generan en `data/reports/`:
- **`auditoria_egov_suroccidente_YYYYMMDD.xlsx`** — Excel con 10 hojas (resumen ejecutivo, descriptiva por OE, proporciones con IC95, Kruskal-Wallis entre departamentos, correlaciones Spearman).
- **`auditoria_egov_suroccidente_YYYYMMDD.csv`** — CSV plano con todas las métricas.
- **`dashboard_YYYYMMDD.html`** — Dashboard HTML interactivo autocontenido (se abre en el navegador, no requiere servidor): KPIs, gráficas Chart.js, tabla filtrable y ordenable.
- **`graficas_YYYYMMDD/`** — PNGs estáticos para incluir en la tesis.

### 6. Descubrir URLs faltantes

```bash
python main.py --descubrir
```

Prueba patrones comunes de dominio (`muniNOMBRE.gob.gt`, etc.) y valida que el contenido recuperado mencione el nombre del municipio para evitar falsos positivos. El resultado se guarda en `data/processed/descubrimiento_urls.csv` para revisión manual.

## Estructura del proyecto

```
egov-audit/
├── config/
│   ├── municipios.yaml          # Lista de municipalidades y URLs
│   └── settings.py              # Parámetros configurables
├── src/
│   ├── scraper/                 # Recolección de datos
│   │   ├── fetcher.py           # Cliente HTTP con manejo de errores
│   │   └── discoverer.py        # Descubrimiento de URLs faltantes
│   ├── audits/                  # Módulos de auditoría (uno por OE)
│   │   ├── performance.py       # OE1
│   │   ├── content_freshness.py # OE2
│   │   └── security.py          # OE3
│   ├── analysis/
│   │   └── stats.py             # Estadística descriptiva e inferencial
│   └── reports/
│       ├── generator.py         # Exportación a Excel/CSV + gráficas PNG
│       └── dashboard.py         # Dashboard HTML interactivo (Chart.js)
├── data/
│   ├── raw/                     # JSON crudo por municipalidad
│   ├── processed/               # CSVs consolidados
│   └── reports/                 # Reportes Excel finales
├── notebooks/
│   └── analisis_estadistico.ipynb
├── main.py                      # Orquestador
└── requirements.txt
```

## Metodología

1. **Recolección (scraping):** Cada portal se visita una sola vez por ejecución, respetando un User-Agent identificado y timeouts. Se descargan los headers HTTP, el HTML completo y un inventario de recursos referenciados.
2. **Medición de rendimiento:** Se mide TTFB, tiempo total de descarga, peso bruto, número de peticiones y se inspecciona el HTML para detectar metadatos de viewport móvil, atributo `lang` y atributos `alt` en imágenes.
3. **Frecuencia de actualización:** Se consulta la CDX API de Internet Archive (Wayback Machine) para obtener todos los snapshots del dominio entre 2021 y 2026, computando intervalo medio entre snapshots y último snapshot.
4. **Transparencia LAIP:** Se busca en el HTML y enlaces internos la presencia de secciones que cumplan los artículos 10 y 11 de la Ley de Acceso a la Información Pública de Guatemala (Decreto 57-2008).
5. **Seguridad:** Se valida la cadena SSL del dominio (validez, vencimiento, versión TLS) y se inspeccionan los headers de seguridad estándar (OWASP Secure Headers Project).
6. **Análisis estadístico:** Estadística descriptiva (media, mediana, desviación, IQR), distribuciones por departamento, intervalos de confianza al 95% y prueba de bondad de ajuste según corresponda.

## Consideraciones éticas

- Solo se accede a información pública mediante peticiones HTTP estándar (sin bypass de autenticación, sin envío de formularios).
- Se respeta `robots.txt` cuando está presente.
- Se usa un User-Agent claramente identificado.
- Se hace una sola visita por portal por ejecución (no DDoS).
- Los datos recogidos son técnicos y públicos; no se procesan datos personales.

## Autor

Investigación de Seminario I — Ingeniería en Sistemas — 2026.
