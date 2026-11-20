"""Pruebas unitarias del folio por petición y del log JSON."""

import io
import json
from datetime import datetime, timedelta, timezone

from app.observability import JsonLogger, resolve_request_id

GENERATED = "generated-id"
EVERY_ALLOWED_CHARACTER = "ABCXYZabcxyz0189._:-"


class FlushCountingSink(io.StringIO):
    """Destino del log en memoria que cuenta cuántas veces se vació."""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        """Cuenta el vaciado y delega en ``StringIO``."""
        self.flushes += 1
        super().flush()


class StoppedClock:
    """Reloj falso que siempre devuelve la misma hora.

    :param moment: La hora que devuelve.
    :type moment: datetime.datetime
    """

    def __init__(self, moment):
        self.moment = moment

    def now(self):
        """Devuelve la hora fija.

        :return: La hora en UTC.
        :rtype: datetime.datetime
        """
        return self.moment


def _generate():
    """Generador de ids fijo para las pruebas."""
    return GENERATED


def test_client_request_id_is_kept_only_when_it_is_safe():
    for safe in ("a", "a" * 128, EVERY_ALLOWED_CHARACTER, "folio-123"):
        assert resolve_request_id(safe, _generate) == safe
    unsafe_values = (None, "", "a" * 129, "folio 123", "folio/123", "cañón", "id\n")
    for unsafe in unsafe_values:
        assert resolve_request_id(unsafe, _generate) == GENERATED


def test_logger_writes_one_flushed_ascii_json_line_per_event_with_the_clock_time():
    moment = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    sink = FlushCountingSink()
    logger = JsonLogger(sink=sink, clock=StoppedClock(moment), service="help-desk")
    logger.log("audit", "folio-1", tool="search_knowledge_base", category="Conexión")
    flushes_after_first = sink.flushes
    assert flushes_after_first >= 1
    logger.log("request", "folio-2", status=200)
    assert sink.flushes > flushes_after_first
    lines = sink.getvalue().splitlines()
    assert len(lines) == 2
    assert all(line.isascii() for line in lines)
    first = json.loads(lines[0])
    assert first["service"] == "help-desk"
    assert (first["event"], first["request_id"]) == ("audit", "folio-1")
    assert first["category"] == "Conexión"
    timestamp = datetime.fromisoformat(first["ts"])
    assert timestamp == moment
    assert timestamp.utcoffset() == timedelta(0)
    assert json.loads(lines[1])["status"] == 200
