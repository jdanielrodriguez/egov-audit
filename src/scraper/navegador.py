"""
Segundo intento de verificación con un navegador real (Playwright headless).

Se usa SOLO en el descubrimiento/actualización de URLs (no en la recolección
diaria), como segundo intento cuando una URL parece MUERTA con el cliente HTTP
normal. Un navegador real ejecuta JavaScript y supera challenges de Cloudflare
o bloqueos anti-bot que un cliente `requests` no pasa, así distinguimos un sitio
genuinamente caído de uno que solo rechaza al cliente HTTP.

No es evasión: se carga la página como lo haría un humano (sin proxies, sin
resolver captchas, sin forzar nada).

Playwright es OPCIONAL. Si no está instalado (o falta el navegador), la función
devuelve 'no_disponible' y el llamador conserva su decisión previa. Para usarlo:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

from config.settings import USER_AGENT, HTTP_TIMEOUT
from src.logger import get_logger

log = get_logger(__name__)

ESTADOS_RESTRINGIDO = (401, 403, 429)


def verificar_con_navegador(url: str) -> str:
    """
    Carga `url` en Chromium headless y clasifica el resultado:
      'vivo'          → la página respondió 2xx/3xx
      'restringido'   → respondió 401/403/429 (existe pero bloquea)
      'muerto'        → no cargó (timeout, error de red, 404, 5xx)
      'no_disponible' → Playwright no está instalado/operativo (no se intentó)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "no_disponible"

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            try:
                ctx = navegador.new_context(user_agent=USER_AGENT, locale="es-GT")
                page = ctx.new_page()
                resp = page.goto(url, timeout=HTTP_TIMEOUT * 1000, wait_until="domcontentloaded")
                status = resp.status if resp else None
                if status in ESTADOS_RESTRINGIDO:
                    return "restringido"
                if status and 200 <= status < 400:
                    return "vivo"
                return "muerto"
            except Exception as ex:
                log.debug("Navegador no pudo cargar %s: %s", url, ex)
                return "muerto"
            finally:
                navegador.close()
    except Exception as ex:
        # Falla de Playwright en sí (navegador no instalado, etc.)
        log.warning("Playwright no operativo (%s): se omite el 2º intento", ex.__class__.__name__)
        return "no_disponible"
