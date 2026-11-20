"""Folio por petición, log JSON y middleware que mide cada petición.

El log escribe una línea JSON por evento en cuanto ocurre, con la hora de un reloj
inyectado. Solo se registran campos con nombre fijo: nunca el cuerpo de la
petición ni el mensaje de una excepción.
"""

import json
import logging
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Protocol

from fastapi.responses import JSONResponse

REQUEST_ID_HEADER = "X-Request-ID"
DEFAULT_SERVICE = "support-assistant"
INTERNAL_ERROR = "internal error"
ACCESS_LOGGER = "uvicorn.access"
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def silence_access_log():
    """Apaga el access log de uvicorn, que escribe la dirección IP de cada petición.

    La IP es un dato personal (``spec/05-demo.md``) y el evento ``request`` del log
    JSON ya registra el método, la ruta, el código y la latencia, sin la IP. Uvicorn
    configura su log antes de importar la aplicación, así que apagarlo aquí basta.
    """
    logging.getLogger(ACCESS_LOGGER).disabled = True


class Clock(Protocol):
    """Lo que el producto necesita de un reloj."""

    def now(self):
        """Devuelve la hora actual.

        :return: La hora en UTC, con zona horaria.
        :rtype: datetime.datetime
        """


class SystemClock:
    """Reloj real del sistema, en UTC (el que se usa fuera de las pruebas)."""

    def now(self):
        """Devuelve la hora actual del sistema.

        :return: La hora en UTC, con zona horaria.
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)


def new_request_id():
    """Genera un folio nuevo.

    :return: Un UUID aleatorio en texto.
    :rtype: str
    """
    return str(uuid.uuid4())


def resolve_request_id(header, id_factory):
    """Elige el folio de una petición.

    Se respeta el del cliente solo si tiene de 1 a 128 caracteres
    ``A-Z a-z 0-9 . _ : -`` (coincidencia completa); si no, se genera uno.

    :param header: Valor del encabezado ``X-Request-ID``, o ``None``.
    :type header: str or None
    :param id_factory: Función sin argumentos que genera un folio nuevo.
    :type id_factory: collections.abc.Callable
    :return: El folio de la petición.
    :rtype: str
    """
    if header is not None and _SAFE_REQUEST_ID.fullmatch(header):
        return header
    return id_factory()


def elapsed_ms(start, end):
    """Milisegundos entre dos horas del reloj.

    :param start: Hora de inicio.
    :type start: datetime.datetime
    :param end: Hora de fin.
    :type end: datetime.datetime
    :return: La diferencia en milisegundos, con un decimal.
    :rtype: float
    """
    return round((end - start).total_seconds() * 1000, 1)


class JsonLogger:
    """Log de eventos: una línea JSON solo ASCII por evento, vaciada al instante.

    :param sink: Destino con ``write`` y ``flush``; por omisión, la salida estándar
        vigente al escribir.
    :type sink: typing.TextIO or None
    :param clock: Reloj del que sale ``ts``.
    :type clock: Clock
    :param service: Valor del campo ``service``.
    :type service: str
    """

    def __init__(self, sink=None, clock=None, service=DEFAULT_SERVICE):
        self._sink = sink
        self._clock = clock if clock is not None else SystemClock()
        self._service = service
        self._lock = threading.Lock()

    def log(self, event, request_id, **fields):
        """Escribe un evento con ``ts``, ``service``, ``event`` y ``request_id``.

        :param event: Nombre del evento (``request``, ``agent_run``, ``audit``...).
        :type event: str
        :param request_id: Folio de la petición.
        :type request_id: str
        :param fields: Campos propios del evento; no reemplazan a los comunes.
        :type fields: object
        """
        record = {
            "ts": self._clock.now().astimezone(timezone.utc).isoformat(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        for name, value in fields.items():
            record.setdefault(name, value)
        line = json.dumps(record, ensure_ascii=True) + "\n"
        sink = self._sink if self._sink is not None else sys.stdout
        with self._lock:
            sink.write(line)
            sink.flush()


def install_request_middleware(application, logger, metrics, clock, id_factory):
    """Instala el middleware que da folio, mide y registra cada petición.

    Pone el folio en ``request.state.request_id`` y en el encabezado
    ``X-Request-ID``; escribe ``request`` con ``client`` (el nombre que deja el
    middleware de seguridad en ``request.state.api_client``, o ``None``; nunca la
    clave) y ``error`` si algo truena, y registra
    la latencia y el código en las métricas. Una excepción se responde con ``500``
    y ``{"detail": "internal error", "request_id": ...}``.

    :param application: La aplicación FastAPI.
    :type application: fastapi.FastAPI
    :param logger: Log de eventos.
    :type logger: JsonLogger
    :param metrics: Métricas del proceso.
    :type metrics: app.metrics.Metrics
    :param clock: Reloj para medir la latencia.
    :type clock: Clock
    :param id_factory: Función sin argumentos que genera un folio nuevo.
    :type id_factory: collections.abc.Callable
    """

    @application.middleware("http")
    async def observe(request, call_next):
        """Envuelve una petición con su folio, su latencia y sus eventos."""
        start = clock.now()
        request_id = resolve_request_id(
            request.headers.get(REQUEST_ID_HEADER), id_factory
        )
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        # Cualquier error se convierte en un 500 con folio; el mensaje no se registra.
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.log("error", request_id, error_type=type(error).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": INTERNAL_ERROR, "request_id": request_id},
            )
        latency_ms = elapsed_ms(start, clock.now())
        metrics.record_request(status=response.status_code, latency_ms=latency_ms)
        logger.log(
            "request",
            request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
            client=getattr(request.state, "api_client", None),
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
