"""
Genera el plan de recolección de la próxima semana (aleatorio).

Reglas (acordadas con el investigador):
- Se eligen K días al azar, con 2 ≤ K ≤ 7.
- En cada día elegido se programan 5 corridas a horas aleatorias distintas (0–23).
- Total semanal: entre 10 y 35 corridas, con aleatoriedad en día y hora.

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

CORRIDAS_POR_DIA = 5
MIN_DIAS_SEMANA = 2
MAX_DIAS_SEMANA = 7


def generar_plan(
    base: Optional[datetime] = None,
    *,
    semilla: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Construye el plan para los 7 días que empiezan MAÑANA (respecto a `base`).
    `semilla` solo se usa en tests para reproducibilidad.
    """
    if semilla is not None:
        random.seed(semilla)
    ahora = base or datetime.now(TZ_GUATEMALA)
    inicio = (ahora + timedelta(days=1)).date()

    k = random.randint(MIN_DIAS_SEMANA, MAX_DIAS_SEMANA)
    offsets = sorted(random.sample(range(7), k))

    slots = []
    for off in offsets:
        fecha = (inicio + timedelta(days=off)).isoformat()
        horas = sorted(random.sample(range(24), min(CORRIDAS_POR_DIA, 24)))
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
          f"({plan['ventana_inicio']} → {plan['ventana_fin']})")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
