"""
Genera el plan de recolección de la semana EN CURSO (aleatorio).

Reglas (acordadas con el investigador):
- La ventana es domingo→sábado: el planner corre el domingo a primera hora y
  ese mismo domingo es el día 1; el sábado siguiente es el día 7. NUNCA planifica
  para el domingo siguiente (ese día el planner vuelve a correr y regenera el plan).
- Se eligen K días al azar, con 3 ≤ K ≤ 7.
- En cada día elegido se programan 7 corridas a horas aleatorias distintas (0–23).
  En el primer día (el domingo que corre el planner) solo se eligen horas futuras,
  para no programar slots que ya pasaron.
- Total semanal: entre 21 y 49 corridas, con aleatoriedad en día y hora.

Escribe schedule/plan-semana.json. Lo ejecuta el workflow `planner` una vez por
semana (domingo) y luego commitea el archivo. Solo usa la librería estándar.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

TZ_GUATEMALA = timezone(timedelta(hours=-6))
SCHEDULE_DIR = Path(__file__).resolve().parents[2] / "schedule"
PLAN_PATH = SCHEDULE_DIR / "plan-semana.json"

CORRIDAS_POR_DIA = 7
MIN_DIAS_SEMANA = 3
MAX_DIAS_SEMANA = 7


def generar_plan(
    base: Optional[datetime] = None,
    *,
    semilla: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Construye el plan para la ventana domingo→sábado que ARRANCA HOY (respecto a
    `base`): el día en que corre el planner es el día 1, y el sábado siguiente el
    día 7. `semilla` solo se usa en tests para reproducibilidad.
    """
    if semilla is not None:
        random.seed(semilla)
    ahora = base or datetime.now(TZ_GUATEMALA)
    inicio = ahora.date()  # hoy (domingo que corre el planner) = día 1

    k = random.randint(MIN_DIAS_SEMANA, MAX_DIAS_SEMANA)
    offsets = sorted(random.sample(range(7), k))

    slots = []
    for off in offsets:
        fecha = (inicio + timedelta(days=off)).isoformat()
        # El primer día es HOY: solo horas que aún no pasaron (el planner corre a
        # primera hora, así que normalmente quedan casi todas disponibles).
        horas_disponibles = [h for h in range(24) if h > ahora.hour] if off == 0 else list(range(24))
        n = min(CORRIDAS_POR_DIA, len(horas_disponibles))
        horas = sorted(random.sample(horas_disponibles, n))
        for h in horas:
            slots.append({"date": fecha, "hour": h})

    return {
        "ventana_inicio": inicio.isoformat(),
        "ventana_fin": (inicio + timedelta(days=6)).isoformat(),
        "generado": ahora.isoformat(timespec="seconds"),
        "k_dias": k,
        "corridas_por_dia": CORRIDAS_POR_DIA,
        "total_corridas": len(slots),
        "slots": slots,
    }


def main() -> int:
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    plan = generar_plan()
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Plan generado: {plan['k_dias']} días, {plan['total_corridas']} corridas "
          f"({plan['ventana_inicio']} -> {plan['ventana_fin']})")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
