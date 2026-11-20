"""Tope de gasto diario de las preguntas sin clave del modo demo (ADR 0015).

La suma vive en la memoria del proceso: al reiniciar (o al dormirse el servicio en
Render) empieza en cero. El día se calcula en UTC con el reloj inyectado, nunca con
``datetime.now()``.
"""

import threading
from datetime import timezone


class DailyBudget:
    """Suma el costo de las preguntas públicas del día y dice si se alcanzó el tope.

    :param limit_usd: Tope de gasto diario en USD.
    :type limit_usd: float
    :param clock: Reloj con ``now()`` que devuelve un ``datetime`` con zona horaria.
    :type clock: app.observability.Clock
    """

    def __init__(self, limit_usd, clock):
        self._limit = float(limit_usd)
        self._clock = clock
        self._lock = threading.Lock()
        self._day = None
        self._spent = 0.0
        self._notified = False

    def _roll_day(self):
        """Vuelve a cero la suma y el aviso si cambió el día UTC.

        Debe llamarse con el candado tomado.
        """
        today = self._clock.now().astimezone(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._spent = 0.0
            self._notified = False

    def is_exhausted(self):
        """Indica si lo gastado hoy llega o pasa el tope.

        :return: ``True`` si ya no se deben atender preguntas públicas hoy.
        :rtype: bool
        """
        with self._lock:
            self._roll_day()
            return self._spent >= self._limit

    def record(self, cost_usd):
        """Suma el costo de una respuesta pública al gasto de hoy.

        :param cost_usd: Costo de la respuesta en USD.
        :type cost_usd: float
        """
        with self._lock:
            self._roll_day()
            self._spent += float(cost_usd)

    def claim_exhaustion_notice(self):
        """Reclama el aviso de tope alcanzado; solo se concede una vez por día UTC.

        :return: ``True`` la primera vez que se llama en el día; después ``False``.
        :rtype: bool
        """
        with self._lock:
            self._roll_day()
            if self._notified:
                return False
            self._notified = True
            return True

    def snapshot(self):
        """Gasto público de hoy y tope, para ``GET /metrics``.

        :return: ``public_cost_today_usd`` y ``daily_budget_usd``.
        :rtype: dict[str, float]
        """
        with self._lock:
            self._roll_day()
            return {
                "public_cost_today_usd": self._spent,
                "daily_budget_usd": self._limit,
            }
