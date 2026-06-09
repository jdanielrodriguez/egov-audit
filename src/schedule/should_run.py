"""
Gate del runner: decide si la corrida actual coincide con un slot planificado.

El workflow `runner` se dispara cada hora; este script lee
schedule/plan-semana.json y escribe `run=true|false` en $GITHUB_OUTPUT para que
el workflow ejecute (o no) la recolección. Solo usa la librería estándar:
se ejecuta 24 veces al día y debe ser instantáneo, sin instalar dependencias.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

TZ_GUATEMALA = timezone(timedelta(hours=-6))
PLAN_PATH = Path(__file__).resolve().parents[2] / "schedule" / "plan-semana.json"


def decidir(ahora: datetime, plan: Optional[Dict[str, Any]]) -> bool:
    """
    True si existe un slot planificado para la fecha y la HORA local actuales.

    La comparación es por hora e IGNORA los minutos: basta con que coincidan
    `slot["hour"]` y `ahora.hour`. Por eso tolera el retraso habitual del cron de
    GitHub Actions: un slot de las 15:00 se ejecuta aunque el disparo llegue a
    las 15:27 o 15:59 (sigue siendo la hora 15). Solo se omitiría si el retraso
    cruzara por completo a la hora siguiente (>60 min), algo muy infrecuente.
    """
    if not plan:
        return False
    hoy = ahora.strftime("%Y-%m-%d")
    for slot in plan.get("slots", []):
        if slot.get("date") == hoy and int(slot.get("hour", -1)) == ahora.hour:
            return True
    return False


def _cargar_plan() -> Optional[Dict[str, Any]]:
    if not PLAN_PATH.exists():
        return None
    try:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    ahora = datetime.now(TZ_GUATEMALA)
    run = decidir(ahora, _cargar_plan())

    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")

    print(f"[gate] {ahora.isoformat(timespec='seconds')} (hora local {ahora.hour:02d}) "
          f"→ {'RUN' if run else 'SKIP'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
