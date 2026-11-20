"""Métricas en memoria de este proceso para ``GET /metrics``.

Solo se guardan las últimas latencias (``MAX_LATENCIES``) y contadores enteros, para
que la memoria no crezca sin límite. Un candado protege todo: FastAPI corre las rutas
síncronas en varios hilos.
"""

import threading
from collections import deque

MAX_LATENCIES = 1000
OUTCOMES = ("solved", "escalated", "needs_detail", "incomplete")
SOLVED = "solved"
SERVER_ERROR_MIN = 500
SERVER_ERROR_MAX = 599


def nearest_rank(sorted_values, percentile):
    """Percentil por rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor.
    :type sorted_values: list[float]
    :param percentile: Percentil de 1 a 100.
    :type percentile: int
    :return: El valor del percentil, o ``0`` si no hay valores.
    :rtype: float
    """
    if not sorted_values:
        return 0
    rank = -(-percentile * len(sorted_values) // 100)
    return sorted_values[max(rank, 1) - 1]


def _rate(part, total):
    """Fracción ``part / total``; ``0`` si no hay total.

    :param part: Numerador.
    :type part: int
    :param total: Denominador.
    :type total: int
    :return: La fracción.
    :rtype: float
    """
    return part / total if total else 0


class Metrics:
    """Contadores de peticiones, latencias, tokens, costo y formas de terminar."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = 0
        self._server_errors = 0
        self._latencies = deque(maxlen=MAX_LATENCIES)
        self._tokens = {"input": 0, "output": 0}
        self._outcomes = dict.fromkeys(OUTCOMES, 0)
        self._cost_usd = 0.0

    def record_request(self, status, latency_ms):
        """Registra una petición terminada.

        :param status: Código HTTP de la respuesta.
        :type status: int
        :param latency_ms: Latencia en milisegundos.
        :type latency_ms: float
        """
        with self._lock:
            self._requests += 1
            if SERVER_ERROR_MIN <= status <= SERVER_ERROR_MAX:
                self._server_errors += 1
            self._latencies.append(latency_ms)

    def record_answer(self, outcome, input_tokens, output_tokens, cost_usd=0.0):
        """Registra una pregunta respondida por ``POST /ask``.

        :param outcome: ``solved``, ``escalated``, ``needs_detail`` o ``incomplete``.
        :type outcome: str
        :param input_tokens: Tokens de entrada del modelo.
        :type input_tokens: int
        :param output_tokens: Tokens de salida del modelo.
        :type output_tokens: int
        :param cost_usd: Costo de la respuesta en USD.
        :type cost_usd: float
        :raises ValueError: Si ``outcome`` no es uno de los cuatro valores.
        """
        if outcome not in self._outcomes:
            raise ValueError(f"outcome desconocido: {outcome!r}")
        with self._lock:
            self._outcomes[outcome] += 1
            self._tokens["input"] += input_tokens
            self._tokens["output"] += output_tokens
            self._cost_usd += cost_usd

    def snapshot(self, slo_p95_ms):
        """Arma el cuerpo de ``GET /metrics`` (sin ``pid``).

        :param slo_p95_ms: Meta de latencia p95 en milisegundos.
        :type slo_p95_ms: int
        :return: ``requests``, ``error_rate``, ``latency_ms``, ``tokens``,
            ``outcomes``, ``self_service_rate``, ``slo``, ``cost_usd`` y
            ``cost_per_solved_usd``.
        :rtype: dict
        """
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            server_errors = self._server_errors
            tokens = dict(self._tokens)
            outcomes = dict(self._outcomes)
            cost_usd = self._cost_usd
        p95 = nearest_rank(latencies, 95)
        return {
            "requests": requests,
            "error_rate": _rate(server_errors, requests),
            "latency_ms": {"p50": nearest_rank(latencies, 50), "p95": p95},
            "tokens": tokens,
            "outcomes": outcomes,
            "self_service_rate": _rate(outcomes[SOLVED], sum(outcomes.values())),
            "slo": {"p95_ms_target": slo_p95_ms, "met": p95 < slo_p95_ms},
            "cost_usd": cost_usd,
            "cost_per_solved_usd": _rate(cost_usd, outcomes[SOLVED]),
        }
