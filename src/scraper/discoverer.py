"""
Descubre URLs candidatas para municipalidades sin URL conocida.

v3 (mayo 2026) — CORRECCIÓN CRÍTICA tras encontrar falsos positivos:
  - "munisanandres.gob.gt" se asignó a 3 municipios distintos (Villa Seca,
    Xecul, Semetabaj) porque la validación de identidad acortada a las
    primeras dos palabras es demasiado laxa para nombres con stopwords.
  - Solución: identidad estricta basada en TODAS las palabras significativas
    (no-stopwords). Además se mantiene un registro de URLs ya asignadas
    en la misma sesión para detectar reutilizaciones sospechosas.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Dict, Any, Set
from urllib.parse import urlparse

from src.scraper.fetcher import fetch
from src.logger import get_logger

log = get_logger(__name__)


# ============================================================================
# Alias culturales / abreviaturas reconocidos en Guatemala
# ============================================================================
ALIAS_MUNICIPIOS: Dict[str, List[str]] = {
    "quetzaltenango": ["xela", "quetzaltenango"],
    "retalhuleu": ["reu", "retalhuleu"],
    "mazatenango": ["mazate", "mazatenango"],
    "huehuetenango": ["hue", "huehuetenango"],
    "chimaltenango": ["chimal", "chimaltenango"],
    "sacatepequez": ["saca", "sacatepequez"],
    "totonicapan": ["toto", "totonicapan"],
    "suchitepequez": ["suchi", "suchitepequez"],
}

# Palabras genéricas que NO sirven para identificar un municipio por sí solas.
# Si una URL solo contiene estas palabras, NO se considera identidad confirmada.
STOPWORDS_IDENTIDAD: Set[str] = {
    "san",
    "santa",
    "santo",
    "la",
    "el",
    "los",
    "las",
    "de",
    "del",
    "y",
    "nueva",
    "nuevo",
    "muni",
    "municipalidad",
    "gob",
    "gt",
    "com",
    "org",
}

# Memoria de URLs ya asignadas en la sesión actual (para detectar duplicados)
_URLS_ASIGNADAS_SESION: Dict[str, str] = {}


def _quitar_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _slug(s: str) -> str:
    """'San Pedro Sacatepéquez' → 'sanpedrosacatepequez'."""
    s = _quitar_acentos(s)
    return re.sub(r"[^a-zA-Z0-9]+", "", s).lower()


def _slug_guion(s: str) -> str:
    """'San Pedro Sacatepéquez' → 'san-pedro-sacatepequez'."""
    s = _quitar_acentos(s)
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()


def _palabras_significativas(nombre_municipio: str) -> List[str]:
    """
    Devuelve solo las palabras NO-stopword del nombre.
    Ej: 'San Andrés Villa Seca' → ['andres', 'villa', 'seca']
        'San Pablo La Laguna'   → ['pablo', 'laguna']
        'Sololá'                → ['solola']
        'Concepción Tutuapa'    → ['concepcion', 'tutuapa']
    """
    palabras = re.split(r"\s+", _quitar_acentos(nombre_municipio).lower().strip())
    return [p for p in palabras if p and p not in STOPWORDS_IDENTIDAD and len(p) >= 3]


def _obtener_variantes_nombre(nombre_municipio: str) -> List[str]:
    """
    Devuelve formas slug-ificadas para generar URLs candidatas.
    SOLO se usan para generar candidatas, NO para validar identidad.
    """
    slug_base = _slug(nombre_municipio)
    variantes = [slug_base]

    # Alias culturales (Xela, Reu, Mazate, etc.)
    for clave, alias_list in ALIAS_MUNICIPIOS.items():
        if clave == slug_base:
            for alias in alias_list:
                if alias not in variantes:
                    variantes.append(alias)
            break

    # Variante con solo palabras significativas concatenadas
    # Ej: "San Andrés Villa Seca" → "andresvillaseca"
    sigs = _palabras_significativas(nombre_municipio)
    if sigs:
        sig_concat = "".join(sigs)
        if sig_concat and sig_concat not in variantes:
            variantes.append(sig_concat)

    return variantes


def candidatas_para(
    nombre_municipio: str,
    departamento: Optional[str] = None,
) -> List[str]:
    """Genera URLs candidatas a probar para un municipio."""
    nombres = _obtener_variantes_nombre(nombre_municipio)
    dep_slug = _slug(departamento or "")

    plantillas: List[str] = []

    for slug in nombres:
        slug_g = slug

        # .gob.gt — TLD oficial gubernamental Guatemala
        plantillas.extend(
            [
                f"https://www.muni{slug}.gob.gt",
                f"https://muni{slug}.gob.gt",
                f"https://www.muni-{slug_g}.gob.gt",
                f"https://muni-{slug_g}.gob.gt",
                f"https://www.municipalidad{slug}.gob.gt",
                f"https://municipalidad{slug}.gob.gt",
                f"https://www.municipalidad-{slug_g}.gob.gt",
                f"https://www.municipalidadde{slug}.gob.gt",
                f"https://municipalidadde{slug}.gob.gt",
                f"https://www.municipalidad-de-{slug_g}.gob.gt",
                f"https://www.{slug}.gob.gt",
                f"https://{slug}.gob.gt",
            ]
        )

        # Subdominios habituales
        plantillas.extend(
            [
                f"https://sitio.muni{slug}.gob.gt",
                f"https://portal.muni{slug}.gob.gt",
                f"https://www2.muni{slug}.gob.gt",
            ]
        )

        # TLDs alternativos
        plantillas.extend(
            [
                f"https://www.muni{slug}.com.gt",
                f"https://muni{slug}.com.gt",
                f"https://www.muni{slug}.com",
                f"https://muni{slug}.com",
                f"https://www.muni{slug}.org",
                f"https://muni{slug}.org",
                f"https://www.muni{slug}.org.gt",
                f"https://muni{slug}.org.gt",
            ]
        )

        # Con sufijo de departamento (homónimos)
        if dep_slug and dep_slug != slug:
            plantillas.extend(
                [
                    f"https://www.muni{slug}{dep_slug}.gob.gt",
                    f"https://www.muni{slug}-{dep_slug}.gob.gt",
                    f"https://muni{slug}{dep_slug}.gob.gt",
                ]
            )

    vistos = set()
    out = []
    for p in plantillas:
        if p not in vistos:
            out.append(p)
            vistos.add(p)
    return out


def _confirma_identidad_estricta(
    html: str,
    nombre_municipio: str,
    departamento: Optional[str],
) -> tuple[bool, str]:
    """
    Validación de identidad ESTRICTA.

    Regla: el HTML debe mencionar TODAS las palabras significativas del
    municipio (no-stopwords). Si tiene menos de 3 caracteres o es stopword,
    no cuenta.

    Adicionalmente, para nombres muy comunes (los que solo tienen palabras
    de tipo "San X" + stopwords) se exige que ADEMÁS el HTML mencione el
    departamento, para distinguir homónimos.

    Returns: (es_identidad_valida, razón)
    """
    if not html:
        return False, "html_vacio"

    html_norm = _slug(html[:120000])  # primeros 120KB

    sigs = _palabras_significativas(nombre_municipio)
    if not sigs:
        # Caso degenerado: el nombre solo tiene stopwords ("La Reforma"
        # convertida a slug significativo da vacío). Caer en match por
        # slug completo.
        slug_completo = _slug(nombre_municipio)
        if len(slug_completo) >= 6 and slug_completo in html_norm:
            return True, "match_slug_completo"
        return False, "sin_palabras_significativas"

    # Cada palabra significativa debe aparecer en el HTML
    faltantes = [p for p in sigs if p not in html_norm]

    if faltantes:
        return False, f"faltan_palabras:{','.join(faltantes)}"

    # Si solo hay 1 palabra significativa, podría ser un nombre genérico
    # (ej: "Concepción" en Sololá; "Concepción" puede aparecer en muchos sitios).
    # En ese caso, requerimos también el departamento para distinguir.
    if len(sigs) == 1 and departamento:
        dep_slug = _slug(departamento)
        if dep_slug and dep_slug not in html_norm:
            return False, f"nombre_muy_generico_sin_dep:{sigs[0]}"

    return True, "ok"


def descubrir(
    nombre_municipio: str,
    departamento: Optional[str] = None,
    *,
    validar_identidad: bool = True,
    rechazar_urls_reutilizadas: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Prueba cada URL candidata. Devuelve dict con la primera que responde
    Y supera la validación estricta de identidad, o None si nada funciona.

    Si rechazar_urls_reutilizadas=True, rechaza candidatas que ya fueron
    asignadas a otro municipio en la sesión actual (esto previene que la
    misma URL genérica se asigne a 3 municipios distintos).
    """
    log.info("Descubriendo URLs para: %s (%s)", nombre_municipio, departamento or "")
    candidatas = candidatas_para(nombre_municipio, departamento)
    log.debug("  → %d candidatas", len(candidatas))

    for cand in candidatas:
        # Normalizar URL para comparar contra registro de sesión
        cand_norm = cand.rstrip("/").lower().replace("https://www.", "https://")

        # ¿Esta URL ya fue asignada a otro municipio en esta sesión?
        if rechazar_urls_reutilizadas and cand_norm in _URLS_ASIGNADAS_SESION:
            otro = _URLS_ASIGNADAS_SESION[cand_norm]
            if otro != nombre_municipio:
                log.debug("  ⊘ %s ya asignada a %s, omito", cand, otro)
                continue

        res = fetch(cand)
        if not (res.reachable and res.status_code and res.status_code < 400):
            continue

        # URL final (después de redirecciones) también debe verificarse
        if res.url_final:
            url_final_norm = (
                res.url_final.rstrip("/").lower().replace("https://www.", "https://")
            )
            if (
                rechazar_urls_reutilizadas
                and url_final_norm in _URLS_ASIGNADAS_SESION
                and _URLS_ASIGNADAS_SESION[url_final_norm] != nombre_municipio
            ):
                log.info(
                    "  ⊘ %s redirige a %s ya usada por %s",
                    cand,
                    res.url_final,
                    _URLS_ASIGNADAS_SESION[url_final_norm],
                )
                continue

        if validar_identidad:
            ok, razon = _confirma_identidad_estricta(
                res.contenido_html or "", nombre_municipio, departamento
            )
        else:
            ok, razon = True, "skip_validation"

        if ok:
            log.info("  ✓ %s → %s (%d) %s", cand, res.url_final, res.status_code, razon)
            # Registrar para evitar reutilización
            final_norm = (
                (res.url_final or cand)
                .rstrip("/")
                .lower()
                .replace("https://www.", "https://")
            )
            _URLS_ASIGNADAS_SESION[final_norm] = nombre_municipio
            _URLS_ASIGNADAS_SESION[cand_norm] = nombre_municipio
            return {
                "candidata_probada": cand,
                "url_funcional": res.url_final,
                "status_code": res.status_code,
                "identidad_confirmada": True,
                "razon_identidad": razon,
            }
        else:
            log.debug("  ✗ %s → %s identidad rechazada: %s", cand, res.url_final, razon)

    log.info(
        "  No se encontró URL funcional con identidad confirmada para %s",
        nombre_municipio,
    )
    return None


def descubrir_iap_transparencia(
    nombre_municipio: str, departamento: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Intenta encontrar portales de transparencia LAIP en iap.gob.gt.
    """
    slug = _slug(nombre_municipio)
    dep_slug = _slug(departamento or "")

    candidatas = [
        f"https://muni{slug}.iap.gob.gt",
        f"https://muni-{slug}.iap.gob.gt",
        f"https://municipalidad{slug}.iap.gob.gt",
        f"https://muni{slug}{dep_slug}.iap.gob.gt" if dep_slug else None,
    ]
    candidatas = [c for c in candidatas if c]

    for cand in candidatas:
        res = fetch(cand)
        if res.reachable and res.status_code and res.status_code < 400:
            log.info("  ✓ IAP %s → %s", cand, res.url_final)
            return {
                "candidata_probada": cand,
                "url_funcional": res.url_final,
                "status_code": res.status_code,
                "tipo_portal": "transparencia_iap",
            }
    return None


def limpiar_registro_sesion() -> None:
    """Resetea la memoria de URLs ya asignadas (para tests)."""
    _URLS_ASIGNADAS_SESION.clear()
