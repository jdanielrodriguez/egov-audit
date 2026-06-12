"""
Configuración general del proyecto.
Carga variables de entorno y define rutas, timeouts y constantes.
"""
import os
from datetime import timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ===== Rutas =====
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"

# Recolección longitudinal (módulos collect/ y consolidate/)
DAILY_DIR = DATA_DIR / "daily"                 # snapshots crudos append-only (JSONL/mes)
CONSOLIDATED_DIR = DATA_DIR / "consolidated"   # tabla final 1 fila/portal
SCHEDULE_DIR = BASE_DIR / "schedule"           # plan semanal aleatorio (GitHub Actions)
SQLITE_DB = DATA_DIR / "egov.db"               # índice derivado de los JSONL (no se versiona)

for d in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR, LOG_DIR, DAILY_DIR, CONSOLIDATED_DIR, SCHEDULE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ===== Zona horaria de Guatemala (UTC-6 fijo, sin horario de verano) =====
# Se usa para sellar cada corrida en hora local, de modo que el análisis
# "¿es más rápido de noche?" agrupe por la hora real de Guatemala.
TZ_GUATEMALA = timezone(timedelta(hours=-6))

MUNICIPIOS_YAML = CONFIG_DIR / "municipios.yaml"
# Actualización automática de URLs (workflow semanal). NO se toca municipios.yaml:
#   - urls_overrides.json: URLs descubiertas/reemplazadas que se fusionan en la carga
#   - url_registro.json:   historial (descubierta/reemplazada/caída/reactivada) con fechas
URLS_OVERRIDES_JSON = CONFIG_DIR / "urls_overrides.json"
URL_REGISTRO_JSON = CONFIG_DIR / "url_registro.json"

# ===== HTTP =====
USER_AGENT = os.getenv(
    "USER_AGENT",
    "EgovAuditBot/1.0 (investigacion-academica; +contacto@universidad.edu.gt)"
)
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))  # segundos
MAX_RETRIES = 2
REQUEST_DELAY = 1.0  # segundos entre peticiones al mismo dominio

# ===== APIs externas =====
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()
PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
WAYBACK_CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"

# ===== Ventana temporal de análisis histórico =====
ANALISIS_DESDE = "20210101"
ANALISIS_HASTA = "20261231"

# ===== Umbrales de evaluación =====
# Basados en Web Vitals (Google) y recomendaciones OWASP
UMBRALES_PERFORMANCE = {
    "ttfb_bueno_ms": 800,
    "ttfb_aceptable_ms": 1800,
    "carga_total_buena_s": 3.0,
    "carga_total_aceptable_s": 6.0,
    "peso_pagina_bueno_kb": 1500,
    "peso_pagina_aceptable_kb": 4000,
}

UMBRALES_SECURITY = {
    "dias_minimos_cert_validez": 30,
    "tls_minimo_aceptable": "TLSv1.2",
    "headers_seguridad_minimos": [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
    ],
}

# ===== Indicadores LAIP (Ley 57-2008 de Guatemala) =====
# Palabras clave a buscar en HTML/enlaces para evidenciar cumplimiento de transparencia
INDICADORES_LAIP = {
    "transparencia": [
        "transparencia", "acceso a la informacion", "informacion publica",
        "art 10", "articulo 10", "laip", "rendicion de cuentas",
    ],
    "presupuesto": [
        "presupuesto", "ejecucion presupuestaria", "ingresos", "egresos",
    ],
    "compras": [
        "guatecompras", "compras y contrataciones", "adquisiciones",
        "licitaciones", "cotizaciones",
    ],
    "personal": [
        "nomina", "salarios", "personal", "remuneraciones", "viaticos",
    ],
    "servicios": [
        "servicios al ciudadano", "tramites", "servicios municipales",
        "iusi", "boleto de ornato",
    ],
    "estructura": [
        "organigrama", "estructura", "directorio", "autoridades",
        "concejo municipal",
    ],
    "contacto": [
        "contacto", "telefono", "direccion", "correo",
    ],
}
