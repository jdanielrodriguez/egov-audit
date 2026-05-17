"""
OE3 — Vulnerabilidades de seguridad de capa básica.

Responde a la pregunta auxiliar 3:
"¿Qué proporción de las plataformas analizadas presenta vulnerabilidades
en sus protocolos de seguridad básicos (certificados SSL y encabezados de
servidor)?"

Métricas:
- Certificado SSL: válido, emisor, sujeto, vigencia, días restantes
- Versión TLS negociada
- Headers de seguridad (OWASP Secure Headers Project):
    * Strict-Transport-Security (HSTS)
    * Content-Security-Policy (CSP)
    * X-Frame-Options
    * X-Content-Type-Options
    * Referrer-Policy
    * Permissions-Policy
- Exposición de información del servidor (header Server, X-Powered-By)
- Soporte de HTTPS (redirige http→https)
"""
from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from config.settings import UMBRALES_SECURITY, HTTP_TIMEOUT
from src.scraper.fetcher import FetchResult, fetch
from src.logger import get_logger

log = get_logger(__name__)


# ---------- Inspección SSL/TLS ----------

def _inspeccionar_ssl(hostname: str, port: int = 443) -> Dict[str, Any]:
    """
    Inicia un handshake TLS y extrae metadatos del certificado.
    """
    out: Dict[str, Any] = {
        "ssl_ok": False,
        "ssl_error": None,
        "ssl_tls_version": None,
        "ssl_cipher": None,
        "ssl_subject": None,
        "ssl_issuer": None,
        "ssl_valid_from": None,
        "ssl_valid_to": None,
        "ssl_dias_restantes": None,
        "ssl_subject_alt_names": [],
        "ssl_self_signed": None,
    }

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

        with socket.create_connection((hostname, port), timeout=HTTP_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                out["ssl_tls_version"] = ssock.version()
                cipher = ssock.cipher()
                if cipher:
                    out["ssl_cipher"] = cipher[0]

                subject = dict(x[0] for x in cert.get("subject", []))
                issuer = dict(x[0] for x in cert.get("issuer", []))
                out["ssl_subject"] = subject.get("commonName")
                out["ssl_issuer"] = issuer.get("commonName") or issuer.get("organizationName")
                out["ssl_self_signed"] = (subject == issuer)

                not_before = cert.get("notBefore")
                not_after = cert.get("notAfter")
                if not_before:
                    nb = datetime.strptime(not_before, "%b %d %H:%M:%S %Y %Z")
                    out["ssl_valid_from"] = nb.isoformat()
                if not_after:
                    na = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    out["ssl_valid_to"] = na.isoformat()
                    out["ssl_dias_restantes"] = (na - datetime.utcnow()).days

                sans = []
                for typ, val in cert.get("subjectAltName", []) or []:
                    sans.append(val)
                out["ssl_subject_alt_names"] = sans

                out["ssl_ok"] = True
    except ssl.SSLCertVerificationError as ex:
        out["ssl_error"] = f"CertVerificationError: {ex.reason}"
        # Reintento ignorando verificación para extraer cert
        try:
            ctx2 = ssl.create_default_context()
            ctx2.check_hostname = False
            ctx2.verify_mode = ssl.CERT_NONE
            with socket.create_connection((hostname, port), timeout=HTTP_TIMEOUT) as sock:
                with ctx2.wrap_socket(sock, server_hostname=hostname) as ssock:
                    out["ssl_tls_version"] = ssock.version()
                    cert = ssock.getpeercert(binary_form=False) or {}
                    if cert:
                        subject = dict(x[0] for x in cert.get("subject", []))
                        out["ssl_subject"] = subject.get("commonName")
        except Exception:
            pass
    except ssl.SSLError as ex:
        out["ssl_error"] = f"SSLError: {ex}"
    except socket.timeout:
        out["ssl_error"] = f"Timeout TLS (> {HTTP_TIMEOUT}s)"
    except (socket.gaierror, ConnectionRefusedError, OSError) as ex:
        out["ssl_error"] = f"NetworkError: {ex.__class__.__name__}"
    except Exception as ex:
        out["ssl_error"] = f"{ex.__class__.__name__}: {ex}"

    return out


# ---------- Headers de seguridad ----------

def _analizar_security_headers(headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Inspecciona los headers HTTP devueltos en busca de directivas de seguridad.
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}

    chequeos = {
        "header_hsts": "strict-transport-security",
        "header_csp": "content-security-policy",
        "header_x_frame_options": "x-frame-options",
        "header_x_content_type_options": "x-content-type-options",
        "header_referrer_policy": "referrer-policy",
        "header_permissions_policy": "permissions-policy",
    }
    out: Dict[str, Any] = {}
    n_presentes = 0
    presentes_min = []
    minimos = [h.lower() for h in UMBRALES_SECURITY["headers_seguridad_minimos"]]

    for clave, header in chequeos.items():
        val = headers_lower.get(header)
        out[clave] = val is not None
        out[f"{clave}_value"] = val[:300] if val else None
        if val and header in minimos:
            n_presentes += 1
            presentes_min.append(header)

    out["headers_seguridad_presentes"] = n_presentes
    out["headers_seguridad_minimos_total"] = len(minimos)
    out["headers_seguridad_pct"] = round(n_presentes / len(minimos) * 100, 2) if minimos else 0.0

    # Exposición de información del servidor (es un anti-patrón)
    out["expone_server_header"] = "server" in headers_lower
    out["server_header_value"] = headers_lower.get("server")
    out["expone_x_powered_by"] = "x-powered-by" in headers_lower
    out["x_powered_by_value"] = headers_lower.get("x-powered-by")
    out["expone_asp_net_version"] = "x-aspnet-version" in headers_lower

    return out


# ---------- Redirección HTTP → HTTPS ----------

def _verificar_redireccion_https(url: str) -> Dict[str, Any]:
    """Verifica si el portal fuerza redirección de http a https."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return {"redirige_a_https": None, "redirige_a_https_error": "URL inválida"}

    url_http = f"http://{parsed.netloc}{parsed.path or '/'}"
    res = fetch(url_http)
    if not res.reachable:
        return {"redirige_a_https": None, "redirige_a_https_error": res.error}
    if res.url_final and res.url_final.startswith("https://"):
        return {"redirige_a_https": True, "redirige_a_https_error": None}
    return {"redirige_a_https": False, "redirige_a_https_error": None}


# ---------- API pública ----------

def auditar_security(fetch_result: FetchResult) -> Dict[str, Any]:
    """
    Devuelve dict con métricas de seguridad básica.
    """
    url = fetch_result.url_final or fetch_result.url_original
    parsed = urlparse(url)
    hostname = parsed.hostname

    out: Dict[str, Any] = {
        "url_audit_security": url,
        "hostname": hostname,
        "puerto": parsed.port or (443 if parsed.scheme == "https" else 80),
    }

    # SSL/TLS
    if hostname:
        out.update(_inspeccionar_ssl(hostname))
    else:
        out["ssl_ok"] = False
        out["ssl_error"] = "Sin hostname"

    # Headers de seguridad
    out.update(_analizar_security_headers(fetch_result.headers or {}))

    # Redirección HTTP→HTTPS
    if hostname:
        out.update(_verificar_redireccion_https(url))

    # TLS suficientemente moderno?
    tls = out.get("ssl_tls_version") or ""
    out["tls_aceptable"] = tls in {"TLSv1.2", "TLSv1.3"}

    # Cert con vigencia suficiente?
    dias = out.get("ssl_dias_restantes")
    out["cert_vigencia_suficiente"] = (
        dias is not None and dias >= UMBRALES_SECURITY["dias_minimos_cert_validez"]
    )

    # Score de seguridad (0-100)
    out["score_local_security"] = _calcular_score(out)

    # Clasificación cualitativa
    s = out["score_local_security"]
    out["clasificacion_seguridad"] = (
        "Bueno" if s >= 75 else "Aceptable" if s >= 50 else "Deficiente"
    )

    return out


def _calcular_score(m: Dict[str, Any]) -> int:
    """
    Pesos:
      - SSL válido: 25
      - TLS moderno: 15
      - Cert vigencia suficiente: 10
      - Redirige a HTTPS: 10
      - Headers seguridad mínimos (5 headers, 4 puntos cada uno): 20
      - No expone Server: 5
      - No expone X-Powered-By: 5
      - HSTS presente: 5
      - No es certificado self-signed: 5
    """
    s = 0
    if m.get("ssl_ok"):
        s += 25
    if m.get("tls_aceptable"):
        s += 15
    if m.get("cert_vigencia_suficiente"):
        s += 10
    if m.get("redirige_a_https") is True:
        s += 10

    pct = m.get("headers_seguridad_pct", 0.0) or 0.0
    s += int(pct * 0.20)  # 0-20 puntos

    if not m.get("expone_server_header"):
        s += 5
    if not m.get("expone_x_powered_by"):
        s += 5
    if m.get("header_hsts"):
        s += 5
    if m.get("ssl_self_signed") is False:
        s += 5

    return min(s, 100)
