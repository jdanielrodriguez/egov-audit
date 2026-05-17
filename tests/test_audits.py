"""
Tests unitarios mínimos. Ejecutar con: pytest tests/ -v

No requieren conectividad: usan HTML/headers de ejemplo.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.audits.performance import _analizar_html, _clasificar_ttfb, _calcular_score_local
from src.audits.content_freshness import _analizar_indicadores_laip
from src.audits.security import _analizar_security_headers


HTML_EJEMPLO = """
<!DOCTYPE html>
<html lang="es-GT">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Municipalidad de Ejemplo</title>
  <link rel="stylesheet" href="/css/main.css">
  <link rel="icon" href="/favicon.ico">
</head>
<body>
  <h1>Bienvenidos</h1>
  <img src="/logo.png" alt="Logo institucional">
  <img src="/banner.jpg">
  <a href="/transparencia">Transparencia</a>
  <a href="/presupuesto">Presupuesto Municipal</a>
  <a href="https://guatecompras.gt">Compras</a>
  <a href="/contacto">Contáctenos</a>
  <script src="/js/main.js"></script>
</body>
</html>
"""


def test_analizar_html_basico():
    m = _analizar_html(HTML_EJEMPLO)
    assert m["tiene_viewport"] is True
    assert m["tiene_lang"] is True
    assert m["lang_value"] == "es-GT"
    assert m["tiene_charset"] is True
    assert m["imgs_total"] == 2
    assert m["imgs_con_alt"] == 1
    assert m["imgs_pct_con_alt"] == 50.0
    assert m["n_h1"] == 1
    assert m["tiene_favicon"] is True


def test_analizar_html_vacio():
    m = _analizar_html("")
    assert m["tiene_viewport"] is False
    assert m["imgs_total"] == 0


def test_clasificar_ttfb():
    assert _clasificar_ttfb(500) == "Bueno"
    assert _clasificar_ttfb(1200) == "Aceptable"
    assert _clasificar_ttfb(3000) == "Deficiente"
    assert _clasificar_ttfb(None) == "N/A"


def test_score_local_performance():
    m = {
        "reachable": True, "https": True, "tiene_viewport": True,
        "tiene_lang": True, "tiene_charset": True,
        "clasificacion_ttfb": "Bueno", "clasificacion_carga": "Bueno",
        "clasificacion_peso": "Bueno", "imgs_pct_con_alt": 90,
    }
    score = _calcular_score_local(m)
    assert score == 100

    m2 = {"reachable": False}
    assert _calcular_score_local(m2) == 0


def test_laip_indicadores():
    m = _analizar_indicadores_laip(HTML_EJEMPLO)
    assert m["laip_transparencia"] is True
    assert m["laip_presupuesto"] is True
    assert m["laip_compras"] is True
    assert m["laip_contacto"] is True
    assert m["laip_indicadores_encontrados"] >= 4
    assert m["laip_pct_cumplimiento"] > 0


def test_security_headers_completos():
    headers = {
        "Strict-Transport-Security": "max-age=31536000",
        "Content-Security-Policy": "default-src 'self'",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin",
        "Server": "nginx",
    }
    m = _analizar_security_headers(headers)
    assert m["header_hsts"] is True
    assert m["header_csp"] is True
    assert m["header_x_frame_options"] is True
    assert m["headers_seguridad_pct"] == 100.0
    assert m["expone_server_header"] is True
    assert m["server_header_value"] == "nginx"


def test_security_headers_ausentes():
    headers = {"Content-Type": "text/html"}
    m = _analizar_security_headers(headers)
    assert m["header_hsts"] is False
    assert m["headers_seguridad_pct"] == 0.0
    assert m["expone_server_header"] is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
