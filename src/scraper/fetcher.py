"""
Cliente HTTP robusto.
- Hace una sola visita por URL por ejecución.
- Mide TTFB y tiempo total.
- Maneja redirecciones, errores SSL recoverable, timeouts.
- Devuelve un objeto FetchResult con toda la información cruda necesaria
  para los módulos de auditoría aguas abajo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import USER_AGENT, HTTP_TIMEOUT, MAX_RETRIES
from src.logger import get_logger

log = get_logger(__name__)


@dataclass
class FetchResult:
    url_original: str
    url_final: Optional[str] = None
    status_code: Optional[int] = None
    reachable: bool = False
    ttfb_ms: Optional[float] = None
    tiempo_total_ms: Optional[float] = None
    tamanio_bytes: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    contenido_html: Optional[str] = None
    error: Optional[str] = None
    redirecciones: int = 0
    https: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # No incluir el HTML completo en el dict serializado por defecto
        d.pop("contenido_html", None)
        return d


def _normalizar_url(url: str) -> str:
    """Si la URL no tiene esquema, asume https://"""
    url = url.strip()
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _construir_sesion() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-GT,es;q=0.9,en;q=0.5",
    })
    return s


def fetch(url: str, *, method: str = "GET") -> FetchResult:
    """
    Realiza una petición HTTP a `url`, devuelve un FetchResult.
    Nunca lanza excepción: en caso de fallo, devuelve un FetchResult con
    `reachable=False` y `error` poblado.
    """
    url = _normalizar_url(url)
    res = FetchResult(url_original=url)

    if not url:
        res.error = "URL vacía"
        return res

    parsed = urlparse(url)
    if not parsed.netloc:
        res.error = "URL inválida (sin dominio)"
        return res

    sesion = _construir_sesion()
    t_inicio = time.perf_counter()

    try:
        # stream=True para medir TTFB antes de descargar el body completo
        resp = sesion.request(
            method,
            url,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
            stream=True,
            verify=True,
        )
        t_ttfb = time.perf_counter()
        # Forzar lectura del cuerpo
        contenido = resp.content
        t_fin = time.perf_counter()

        res.status_code = resp.status_code
        res.reachable = resp.ok or (200 <= resp.status_code < 400)
        res.url_final = resp.url
        res.ttfb_ms = round((t_ttfb - t_inicio) * 1000, 2)
        res.tiempo_total_ms = round((t_fin - t_inicio) * 1000, 2)
        res.tamanio_bytes = len(contenido)
        res.headers = {k: v for k, v in resp.headers.items()}
        res.redirecciones = len(resp.history)
        res.https = res.url_final.startswith("https://") if res.url_final else False

        # Decodificar HTML solo si el content-type lo indica
        content_type = resp.headers.get("Content-Type", "").lower()
        if "html" in content_type or "xml" in content_type or content_type == "":
            try:
                res.contenido_html = contenido.decode(
                    resp.encoding or "utf-8", errors="replace"
                )
            except Exception as ex:
                log.warning("No se pudo decodificar HTML de %s: %s", url, ex)

    except requests.exceptions.SSLError as ex:
        # Reintentar sin verificar SSL para registrar el error pero seguir auditando
        log.warning("SSL error en %s: %s. Reintentando sin verificación.", url, ex)
        try:
            resp = sesion.request(
                method, url, timeout=HTTP_TIMEOUT,
                allow_redirects=True, verify=False,
            )
            t_fin = time.perf_counter()
            res.status_code = resp.status_code
            res.reachable = True
            res.url_final = resp.url
            res.tiempo_total_ms = round((t_fin - t_inicio) * 1000, 2)
            res.headers = {k: v for k, v in resp.headers.items()}
            res.tamanio_bytes = len(resp.content)
            res.error = f"SSLError: {ex.__class__.__name__}"
            res.contenido_html = resp.text
        except Exception as ex2:
            res.error = f"SSLError + fallback fallido: {ex2}"
    except requests.exceptions.ConnectionError as ex:
        res.error = f"ConnectionError: {ex.__class__.__name__}"
    except requests.exceptions.Timeout:
        res.error = f"Timeout (> {HTTP_TIMEOUT}s)"
    except requests.exceptions.TooManyRedirects:
        res.error = "TooManyRedirects"
    except Exception as ex:
        res.error = f"{ex.__class__.__name__}: {ex}"
    finally:
        sesion.close()

    return res
