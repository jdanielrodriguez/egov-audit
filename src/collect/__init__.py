"""
Capa de recolección longitudinal (RESPONSABILIDAD 1: CONSULTA).

Ejecuta corridas diarias a horas aleatorias (vía GitHub Actions) y persiste
un snapshot por portal por corrida en archivos JSONL append-only.

Submódulos:
- store: esquema canónico del snapshot + persistencia (JSONL + SQLite derivado)
- daily_run: orquesta una corrida completa sobre los portales con URL
"""
