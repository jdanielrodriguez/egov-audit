"""
Planificación aleatoria de la recolección para GitHub Actions.

El cron de Actions es determinista, así que la aleatoriedad se fabrica:
- planner: una vez por semana sortea K días (2–7) y 5 horas aleatorias por día,
  y escribe schedule/plan-semana.json.
- should_run (gate): el runner corre cada hora; este módulo decide si la hora
  actual coincide con una planificada.

Ambos usan SOLO la librería estándar para que el gate horario no necesite
instalar dependencias (se ejecuta 24 veces al día).
"""
