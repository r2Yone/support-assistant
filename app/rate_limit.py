"""Límite de peticiones por cliente en memoria del proceso (ADR 0011 y 0014).

Ventana deslizante de 60 segundos con el reloj inyectado: solo cuentan las
peticiones aceptadas. Como las métricas (ADR 0005), el contador es de este proceso.
Las llaves sin peticiones en la ventana se purgan, para que las direcciones IP del
límite público no hagan crecer la memoria ni se guarden más de lo necesario.
"""

import math
import threading
from collections import deque
from datetime import timedelta

WINDOW = timedelta(seconds=60)
MIN_RETRY_AFTER_SECONDS = 1


class RateLimiter:
    """Permite como mucho ``limit_per_minute`` peticiones por cliente en 60 s.

    :param limit_per_minute: Peticiones permitidas por cliente en la ventana.
    :type limit_per_minute: int
    :param clock: Reloj con ``now()`` que devuelve un ``datetime``.
    :type clock: app.observability.Clock
    :raises ValueError: Si el límite es menor que 1.
    """

    def __init__(self, limit_per_minute, clock):
        if limit_per_minute < 1:
            raise ValueError("limit_per_minute debe ser 1 o más")
        self._limit = limit_per_minute
        self._clock = clock
        self._accepted = {}
        self._last_purge = None
        self._lock = threading.Lock()

    def __repr__(self):
        """Representación sin las llaves (pueden ser direcciones IP).

        :return: El nombre de la clase y el límite.
        :rtype: str
        """
        return f"RateLimiter(limit_per_minute={self._limit})"

    def _purge(self, now):
        """Quita las llaves sin peticiones en la ventana, una vez por ventana.

        Debe llamarse con el candado tomado. No cambia lo que devuelve ``check``: una
        llave sin peticiones en la ventana se comporta igual que una nueva.

        :param now: Hora actual del reloj.
        :type now: datetime.datetime
        """
        if self._last_purge is not None and now - self._last_purge < WINDOW:
            return
        self._last_purge = now
        inactive = [
            key
            for key, accepted in self._accepted.items()
            if not accepted or now - accepted[-1] >= WINDOW
        ]
        for key in inactive:
            del self._accepted[key]

    def tracked_keys(self):
        """Cuántas llaves guarda el limitador.

        :return: El número de llaves en memoria.
        :rtype: int
        """
        with self._lock:
            return len(self._accepted)

    def check(self, client):
        """Registra una petición del cliente si cabe en la ventana.

        Una petición rechazada no cuenta.

        :param client: Nombre del cliente (o la dirección IP, en el límite público).
        :type client: str
        :return: ``None`` si se acepta; si no, los segundos enteros que faltan para
            que se libere la ventana (redondeados hacia arriba, al menos 1).
        :rtype: int or None
        """
        now = self._clock.now()
        with self._lock:
            self._purge(now)
            accepted = self._accepted.setdefault(client, deque())
            while accepted and now - accepted[0] >= WINDOW:
                accepted.popleft()
            if len(accepted) >= self._limit:
                waiting = (accepted[0] + WINDOW - now).total_seconds()
                return max(MIN_RETRY_AFTER_SECONDS, math.ceil(waiting))
            accepted.append(now)
            return None
