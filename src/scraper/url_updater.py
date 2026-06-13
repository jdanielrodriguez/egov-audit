"""
Actualización del catálogo de URLs (lo usa el workflow semanal, antes del planner).

Qué hace en modo ESCRITURA (`escribir=True`):
- Prueba la URL oficial vigente de cada municipio (la del YAML + overrides).
    · Si responde  → la sigue usando (registra verificada_ok / reactivada).
    · Si NO responde → busca reemplazo con el descubridor.
        - Si encuentra una alternativa válida y distinta → la fija como override
          (reemplaza) sin tocar municipios.yaml.
        - Si no encuentra → la MANTIENE (la caída es dato de uptime) y registra
          el fallo; se re-prueba el próximo domingo (si revive → reactivada).
- Para municipios SIN URL → corre el descubridor; si encuentra una válida, la
  agrega como override (descubierta) → una municipalidad que activó su sitio.
- Persiste `config/urls_overrides.json` (catálogo fusionable) y
  `config/url_registro.json` (historial con fechas). NO genera el CSV de informe
  y NO modifica `municipios.yaml`.

En modo informe (`escribir=False`) NO persiste nada: solo devuelve el resumen
(lo usa `main.py --descubrir` para el comportamiento clásico de solo-reporte).

Diseño acordado con el investigador: overrides en JSON (el YAML curado queda
intacto) y las URLs caídas se mantienen + registran, nunca se borran.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from config.settings import URLS_OVERRIDES_JSON, URL_REGISTRO_JSON, TZ_GUATEMALA
from src.portales import cargar_municipios, expandir_urls, _clave_municipio
from src.scraper.fetcher import fetch
from src.scraper.discoverer import descubrir
from src.logger import get_logger

log = get_logger(__name__)


def _ahora_iso() -> str:
    return datetime.now(TZ_GUATEMALA).isoformat(timespec="seconds")


def _hoy() -> str:
    return datetime.now(TZ_GUATEMALA).strftime("%Y-%m-%d")


def _cargar_json(path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError) as ex:
        log.warning("No se pudo leer %s: %s", path.name, ex)
        return {}


def _guardar_json(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def _url_oficial(municipio: Dict[str, Any]) -> Optional[str]:
    """URL oficial vigente del municipio (tras aplicar overrides en la carga)."""
    expandidas = expandir_urls(municipio)
    for e in expandidas:
        if e.get("tipo_portal", "oficial") == "oficial" and e.get("url"):
            return e["url"]
    for e in expandidas:  # fallback: cualquiera con URL
        if e.get("url"):
            return e["url"]
    return None


def _registrar(registro, clave, m, evento, url, detalle="") -> Dict[str, Any]:
    r = registro.setdefault(clave, {
        "municipio": m.get("nombre"),
        "departamento": m.get("departamento"),
        "fallos_consecutivos": 0,
        "eventos": [],
    })
    r["municipio"] = m.get("nombre")
    r["departamento"] = m.get("departamento")
    r["url_vigente"] = url
    r["ultima_verificacion"] = _ahora_iso()
    r["eventos"].append({"fecha": _hoy(), "ts": _ahora_iso(),
                         "evento": evento, "url": url, "detalle": detalle})
    return r


# Un reemplazo solo se hace tras esta cantidad de fallos (muerte real) seguidos,
# para no reemplazar por una baja temporal de un solo sábado.
UMBRAL_FALLOS_REEMPLAZO = 2

# Códigos en que el servidor RESPONDE pero deniega al bot (WAF / anti-bot /
# rate-limit). El sitio existe → NO es una caída ni motivo de reemplazo.
ESTADOS_RESTRINGIDO = (401, 403, 429)


def _estado_url(url: str) -> str:
    """
    Clasifica una URL:
      'vivo'        → 2xx/3xx (en línea).
      'restringido' → 401/403/429: existe pero bloquea al bot. NO es caída.
      'muerto'      → 404, 5xx, timeout, DNS o error de conexión (caída real).
    """
    res = fetch(url)
    sc = res.status_code
    if sc in ESTADOS_RESTRINGIDO:
        return "restringido"
    if res.reachable and sc and 200 <= sc < 400:
        return "vivo"
    return "muerto"


def actualizar_catalogo(*, escribir: bool = False) -> Dict[str, Any]:
    """
    Verifica/actualiza el catálogo de URLs. Devuelve un resumen con conteos y la
    lista de cambios. Solo persiste overrides+registro si `escribir=True`.
    """
    municipios = cargar_municipios(aplicar_overrides=True)
    overrides = _cargar_json(URLS_OVERRIDES_JSON)
    registro = _cargar_json(URL_REGISTRO_JSON)
    resumen: Dict[str, Any] = {
        "verificadas_ok": 0, "reactivadas": 0, "restringidas": 0, "reemplazadas": 0,
        "descubiertas": 0, "caidas": 0, "sin_url": 0, "cambios": [],
    }

    for m in municipios:
        clave = _clave_municipio(m)
        url = _url_oficial(m)

        if url:
            estado = _estado_url(url)
            eventos = registro.get(clave, {}).get("eventos", [])
            ultimo = eventos[-1].get("evento") if eventos else None

            if estado == "vivo":
                era_caida = ultimo in ("caida", "restringido")
                _registrar(registro, clave, m, "reactivada" if era_caida else "verificada_ok", url)
                registro[clave]["fallos_consecutivos"] = 0
                if era_caida:
                    resumen["reactivadas"] += 1
                    resumen["cambios"].append({"municipio": m.get("nombre"), "evento": "reactivada", "url": url})
                else:
                    resumen["verificadas_ok"] += 1

            elif estado == "restringido":
                # El sitio EXISTE pero bloquea al bot (403/401/429). No es caída:
                # se mantiene, no se reemplaza y no cuenta como fallo.
                _registrar(registro, clave, m, "restringido", url,
                           "acceso restringido (403/401/429); el sitio existe, se mantiene")
                registro[clave]["fallos_consecutivos"] = 0
                resumen["restringidas"] += 1

            else:  # muerto (404, 5xx, timeout, DNS, conexión)
                fallos = registro.get(clave, {}).get("fallos_consecutivos", 0) + 1
                # Solo se busca reemplazo tras UMBRAL fallos seguidos (evita baja temporal).
                if fallos >= UMBRAL_FALLOS_REEMPLAZO:
                    hallazgo = descubrir(m["nombre"], m.get("departamento"))
                    nueva = hallazgo.get("url_funcional") if hallazgo else None
                    if nueva and nueva.rstrip("/") != url.rstrip("/"):
                        overrides[clave] = {"url": nueva, "tipo_portal": "oficial",
                                            "fuente": "reemplazo", "fecha": _hoy(),
                                            "url_anterior": url}
                        _registrar(registro, clave, m, "reemplazada", nueva,
                                   f"reemplaza {url} tras {fallos} fallos seguidos")
                        registro[clave]["fallos_consecutivos"] = 0
                        resumen["reemplazadas"] += 1
                        resumen["cambios"].append({"municipio": m.get("nombre"), "evento": "reemplazada", "de": url, "a": nueva})
                    else:
                        r = _registrar(registro, clave, m, "caida", url,
                                       f"muerta {fallos}x, sin reemplazo; se mantiene")
                        r["fallos_consecutivos"] = fallos
                        resumen["caidas"] += 1
                        resumen["cambios"].append({"municipio": m.get("nombre"), "evento": "caida", "url": url})
                else:
                    # 1er fallo: puede ser baja temporal. Se registra y se re-prueba
                    # el próximo sábado; aún NO se busca reemplazo.
                    r = _registrar(registro, clave, m, "caida", url,
                                   f"muerta {fallos}x; se re-prueba (umbral reemplazo={UMBRAL_FALLOS_REEMPLAZO})")
                    r["fallos_consecutivos"] = fallos
                    resumen["caidas"] += 1
        else:
            hallazgo = descubrir(m["nombre"], m.get("departamento"))
            nueva = hallazgo.get("url_funcional") if hallazgo else None
            if nueva:
                overrides[clave] = {"url": nueva, "tipo_portal": "oficial",
                                    "fuente": "descubrimiento", "fecha": _hoy()}
                _registrar(registro, clave, m, "descubierta", nueva)
                resumen["descubiertas"] += 1
                resumen["cambios"].append({"municipio": m.get("nombre"), "evento": "descubierta", "a": nueva})
            else:
                resumen["sin_url"] += 1

    if escribir:
        _guardar_json(URLS_OVERRIDES_JSON, overrides)
        _guardar_json(URL_REGISTRO_JSON, registro)
        log.info("Catálogo ESCRITO. ok=%d reactiv=%d restring=%d reempl=%d nuevas=%d caidas=%d",
                 resumen["verificadas_ok"], resumen["reactivadas"], resumen["restringidas"],
                 resumen["reemplazadas"], resumen["descubiertas"], resumen["caidas"])
    else:
        log.info("Catálogo verificado (sin escribir). ok=%d restring=%d reempl=%d nuevas=%d caidas=%d",
                 resumen["verificadas_ok"], resumen["restringidas"], resumen["reemplazadas"],
                 resumen["descubiertas"], resumen["caidas"])
    return resumen
