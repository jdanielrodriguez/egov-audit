"""
Consolidación (RESPONSABILIDAD 2: REPORTE DE REPORTES).

Toma todos los snapshots diarios y los reduce a UN registro por portal,
que es la unidad de análisis de la tesis. Reglas de agregación:
- continuas → mediana + desviación estándar (solo corridas exitosas)
- dicotómicas estables → valor modal (solo corridas exitosas)
- disponibilidad → uptime = % de corridas exitosas sobre el total

Deriva las dos variables dependientes del análisis (cumple_LAIP,
tiene_vulnerabilidad) y los predictores (departamento, cabecera,
tipo_hosting, calidad_tecnica).

IMPORTANTE (anti-pseudoreplicación): cualquier análisis estadístico debe
consumir esta tabla consolidada, NUNCA los snapshots crudos repetidos.
"""
