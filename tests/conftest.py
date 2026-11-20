"""Fixtures compartidas por las pruebas del Support Assistant.

Las pruebas solo leen archivos dentro de ``product/``: la base de conocimiento real
es ``data/knowledge_base.json`` y la API se arma con ``create_app()`` y dependencias
inyectadas (reloj falso, métricas nuevas, log en memoria e id fijo).

Desde ``spec/04-production.md`` la API exige ``X-API-Key``: las fábricas de clientes
agregan ``API_KEYS`` con una clave de ejemplo (solo si la prueba no la define) y
mandan esa clave por omisión, para que las pruebas anteriores conserven su intención.

Desde ``spec/05-demo.md`` existe ``make_public_client``: el modo demo
(``PUBLIC_PAGE=true``) con un cliente que no manda clave y sale de una IP fija.

Desde ``spec/06-traces.md`` existe ``langsmith_stub``: un módulo ``langsmith``
sustituto en ``sys.modules`` que registra clientes, ``traceable``, contextos y la
corrida actual, y nunca usa la red. ``tracing_environ`` enciende las trazas con una
clave de ejemplo.
"""

import contextlib
import functools
import io
import json
import logging
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tracing
from app.config import load_settings
from app.knowledge_base import KnowledgeBase
from app.llm import Completion, FakeModel
from app.main import create_app
from app.metrics import Metrics

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
KB_FILE = PRODUCT_ROOT / "data" / "knowledge_base.json"
GENERATED_ID = "generated-id"
CLOCK_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLOCK_STEP_MS = 5
API_KEY_HEADER = "X-API-Key"
TEST_CLIENT = "qa-tests"
# Texto de ejemplo de más de 16 caracteres: nunca una clave real.
TEST_API_KEY = "example-test-key-0123456789"
# Direcciones de documentación (RFC 5737): nunca de una persona real.
PUBLIC_PEER = "203.0.113.10"
PEER_PORT = 50000
# Clave de LangSmith de ejemplo: nunca una real (las trazas van al sustituto).
LANGSMITH_TEST_KEY = "lsv2-example-tracing-key-0000"


class FakeClock:
    """Reloj falso: empieza en una hora fija y avanza lo mismo en cada lectura.

    :param start: Primera hora que devuelve (en UTC).
    :type start: datetime.datetime
    :param step_ms: Milisegundos que avanza en cada lectura.
    :type step_ms: int
    """

    def __init__(self, start=CLOCK_START, step_ms=CLOCK_STEP_MS):
        self.current = start
        self.step = timedelta(milliseconds=step_ms)

    def now(self):
        """Devuelve la hora actual del reloj falso y lo avanza.

        :return: La hora en UTC.
        :rtype: datetime.datetime
        """
        value = self.current
        self.current += self.step
        return value


class FailingModel:
    """Modelo que siempre truena, con un mensaje que nunca debe llegar al log."""

    message = "secreto del modelo: la pregunta completa de la persona"

    def complete(self, _messages):
        """Lanza ``RuntimeError`` con un mensaje sensible.

        :raises RuntimeError: Siempre.
        """
        raise RuntimeError(self.message)


@dataclass
class ObservedApi:
    """Cliente de prueba junto con el log en memoria que escribe la API.

    :param client: Cliente de prueba de FastAPI.
    :type client: fastapi.testclient.TestClient
    :param log: Destino del log JSON.
    :type log: io.StringIO
    :param clock: Reloj falso inyectado (las pruebas lo adelantan).
    :type clock: FakeClock or None
    """

    client: TestClient
    log: io.StringIO
    clock: FakeClock | None = None

    def events(self, request_id=None):
        """Lee el log: cada línea debe ser un objeto JSON.

        :param request_id: Si se da, solo los eventos de ese folio.
        :type request_id: str or None
        :return: Los eventos en el orden en que se escribieron.
        :rtype: list[dict]
        """
        lines = [line for line in self.log.getvalue().splitlines() if line.strip()]
        events = [json.loads(line) for line in lines]
        if request_id is None:
            return events
        return [event for event in events if event["request_id"] == request_id]


@dataclass
class PublicApi(ObservedApi):
    """API observada en modo demo: el cliente no manda ``X-API-Key``.

    :param app: La aplicación, para abrir clientes desde otra dirección IP.
    :type app: fastapi.FastAPI or None
    """

    app: FastAPI | None = None

    def client_from(self, peer):
        """Un cliente sin clave que se conecta desde otra dirección IP.

        :param peer: Dirección IP de la conexión.
        :type peer: str
        :return: El cliente de prueba.
        :rtype: fastapi.testclient.TestClient
        """
        return TestClient(
            self.app, raise_server_exceptions=False, client=(peer, PEER_PORT)
        )


def _knowledge_for(settings):
    """La base de conocimiento que indica la configuración."""
    return KnowledgeBase.from_file(
        settings.kb_path,
        min_score=settings.kb_min_score,
        max_results=settings.kb_max_results,
    )


def _keyed_settings(environ):
    """Configuración con la clave de prueba, salvo que la prueba defina ``API_KEYS``.

    :param environ: Variables de la prueba, o ``None``.
    :type environ: dict or None
    :return: La configuración validada.
    :rtype: app.config.Settings
    """
    variables = {"API_KEYS": f"{TEST_CLIENT}:{TEST_API_KEY}", **(environ or {})}
    return load_settings(variables)


def _keyed_client(app, **options):
    """Cliente de prueba que manda la clave de prueba en cada petición.

    :param app: La aplicación FastAPI.
    :type app: fastapi.FastAPI
    :return: El cliente con ``X-API-Key`` por omisión.
    :rtype: fastapi.testclient.TestClient
    """
    return TestClient(app, headers={API_KEY_HEADER: TEST_API_KEY}, **options)


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas fijas en orden.

    Guarda una copia de los mensajes de cada llamada para revisarlos después.

    :param replies: Textos que devuelve, uno por llamada.
    :type replies: str
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta guionada.

        :param messages: Conversación que manda el agente.
        :type messages: list
        :return: La respuesta con 10 tokens de entrada y 3 de salida.
        :rtype: Completion
        """
        self.calls.append([dict(message) for message in messages])
        text = self.replies.pop(0) if self.replies else '{"answer": "fin"}'
        return Completion(text=text, input_tokens=10, output_tokens=3)


class SpyModel:
    """Envuelve al modelo simulado y guarda los mensajes que recibe."""

    def __init__(self):
        self.inner = FakeModel()
        self.calls = []

    def complete(self, messages):
        """Guarda los mensajes y delega en ``FakeModel``.

        :param messages: Conversación que manda el agente.
        :type messages: list
        :return: La respuesta del modelo simulado.
        :rtype: Completion
        """
        self.calls.append([dict(message) for message in messages])
        return self.inner.complete(messages)


class GatewayStub:
    """AI Gateway de Cloudflare simulado con ``httpx.MockTransport`` (nunca red).

    Devuelve las respuestas en orden y repite la última; una excepción se lanza
    como si fallara la red. Guarda cada petición para revisarla después.

    :param replies: ``httpx.Response`` o excepciones de ``httpx``.
    :type replies: object
    """

    account = "account-0123456789"
    token = "token-secret-abcdef"
    gateway = "help-desk-gateway"
    secret_body = "provider-internal-detail-xyz"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    @classmethod
    def environ(cls, **extra):
        """Variables de entorno para ``MODEL_PROVIDER=gateway`` con esta cuenta.

        :return: Las variables, más las que se pasen en ``extra``.
        :rtype: dict
        """
        return {
            "MODEL_PROVIDER": "gateway",
            "CF_ACCOUNT_ID": cls.account,
            "CF_GATEWAY_ID": cls.gateway,
            "CF_API_TOKEN": cls.token,
            **extra,
        }

    @staticmethod
    def reply(text, prompt_tokens=12, completion_tokens=4, cache_status=None):
        """Una respuesta exitosa del gateway con la forma de chat completions.

        :param text: Contenido del mensaje del modelo.
        :type text: str
        :param prompt_tokens: Valor de ``usage.prompt_tokens``.
        :type prompt_tokens: int
        :param completion_tokens: Valor de ``usage.completion_tokens``.
        :type completion_tokens: int
        :param cache_status: Valor de ``cf-aig-cache-status`` (``None``: sin él).
        :type cache_status: str or None
        :return: La respuesta HTTP.
        :rtype: httpx.Response
        """
        headers = {"cf-aig-cache-status": cache_status} if cache_status else {}
        body = {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }
        return httpx.Response(200, headers=headers, json=body)

    @classmethod
    def failure(cls, status=500):
        """Una respuesta de error del proveedor con un cuerpo que no debe filtrarse.

        :param status: Código HTTP.
        :type status: int
        :return: La respuesta HTTP.
        :rtype: httpx.Response
        """
        return httpx.Response(status, json={"error": cls.secret_body})

    def handle(self, request):
        """Atiende una petición del ``MockTransport``.

        :param request: La petición que mandó el modelo.
        :type request: httpx.Request
        :return: Una copia de la respuesta guionada.
        :rtype: httpx.Response
        :raises httpx.HTTPError: Si la respuesta guionada es una excepción.
        """
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(
            reply.status_code, headers=reply.headers, content=reply.content
        )

    def client(self):
        """Un ``httpx.Client`` que solo habla con este gateway simulado.

        :return: El cliente HTTP para inyectar.
        :rtype: httpx.Client
        """
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def bodies(self):
        """Los cuerpos JSON de las peticiones recibidas, en orden.

        :return: Un diccionario por petición.
        :rtype: list[dict]
        """
        return [json.loads(request.content) for request in self.requests]


@pytest.fixture
def gateway_stub():
    """La clase ``GatewayStub``: ``gateway_stub(gateway_stub.reply("..."))``."""
    return GatewayStub


@pytest.fixture
def scripted_model():
    """Fábrica de modelos guionados: ``scripted_model(reply1, reply2, ...)``."""
    return ScriptedModel


@pytest.fixture
def spy_model():
    """Un modelo simulado que guarda los mensajes de cada llamada."""
    return SpyModel()


@pytest.fixture
def knowledge_base():
    """La base de conocimiento real con los valores por omisión."""
    return KnowledgeBase.from_file(KB_FILE, min_score=2, max_results=2)


@pytest.fixture
def make_client():
    """Fábrica de clientes de prueba con configuración, modelo y clave inyectados."""

    def _make(environ=None, model=None):
        settings = _keyed_settings(environ)
        app = create_app(
            settings=settings,
            model=model or FakeModel(),
            knowledge_base=_knowledge_for(settings),
        )
        return _keyed_client(app)

    return _make


@pytest.fixture
def valid_api_key():
    """La clave de ejemplo que las fábricas de clientes mandan por omisión."""
    return TEST_API_KEY


@pytest.fixture
def api_client_name():
    """El nombre del cliente dueño de la clave de ejemplo."""
    return TEST_CLIENT


@pytest.fixture
def generated_id():
    """El id que genera el ``id_factory`` inyectado."""
    return GENERATED_ID


@pytest.fixture
def failing_model():
    """Un modelo que lanza una excepción en cada llamada."""
    return FailingModel()


@pytest.fixture
def make_observed_client():
    """Fábrica de clientes con reloj falso, métricas nuevas, log en memoria e id fijo.

    Un error del servidor llega como respuesta ``500`` y no como excepción.
    """

    def _make(environ=None, model=None):
        settings = _keyed_settings(environ)
        log = io.StringIO()
        clock = FakeClock()
        app = create_app(
            settings=settings,
            model=model or FakeModel(),
            knowledge_base=_knowledge_for(settings),
            clock=clock,
            metrics=Metrics(),
            log_sink=log,
            id_factory=lambda: GENERATED_ID,
        )
        client = _keyed_client(app, raise_server_exceptions=False)
        return ObservedApi(client, log, clock)

    return _make


@pytest.fixture
def make_costed_client():
    """Fábrica de clientes observados que crean sus propios modelos (spec 03).

    Sin ``model``, ``create_app()`` crea los modelos de ``MODEL_SMALL`` y
    ``MODEL_LARGE`` (simulados o del gateway con el ``http_client`` inyectado) y
    carga la tabla de precios de ``PRICES_PATH``.
    """

    def _make(environ=None, model=None, http_client=None):
        settings = _keyed_settings(environ)
        log = io.StringIO()
        clock = FakeClock()
        app = create_app(
            settings=settings,
            model=model,
            knowledge_base=_knowledge_for(settings),
            clock=clock,
            metrics=Metrics(),
            log_sink=log,
            id_factory=lambda: GENERATED_ID,
            http_client=http_client,
        )
        client = _keyed_client(app, raise_server_exceptions=False)
        return ObservedApi(client, log, clock)

    return _make


@pytest.fixture
def public_peer():
    """La dirección IP de ejemplo desde la que se conecta el cliente público."""
    return PUBLIC_PEER


@pytest.fixture
def make_public_client():
    """Fábrica de clientes en modo demo (``PUBLIC_PAGE=true``), sin clave.

    ``API_KEYS`` sigue teniendo la clave de ejemplo (para ``/metrics`` y para las
    peticiones con clave). El cliente se conecta desde ``PUBLIC_PEER`` y no manda
    ``X-API-Key`` por omisión; el reloj falso queda expuesto para adelantarlo.
    """

    def _make(environ=None, model=None):
        settings = _keyed_settings({"PUBLIC_PAGE": "true", **(environ or {})})
        log = io.StringIO()
        clock = FakeClock()
        app = create_app(
            settings=settings,
            model=model or FakeModel(),
            knowledge_base=_knowledge_for(settings),
            clock=clock,
            metrics=Metrics(),
            log_sink=log,
            id_factory=lambda: GENERATED_ID,
        )
        client = TestClient(
            app, raise_server_exceptions=False, client=(PUBLIC_PEER, PEER_PORT)
        )
        return PublicApi(client, log, clock, app)

    return _make


class StubLangSmithClient:
    """Cliente de LangSmith sustituto: guarda sus opciones y nunca se conecta.

    :param options: Argumentos con los que se creó (``hide_inputs``...).
    :type options: dict
    """

    def __init__(self, **options):
        self.options = options

    def hide(self, option, payload):
        """Aplica ``hide_inputs`` o ``hide_outputs`` como lo hace LangSmith.

        Una función recibe el diccionario y devuelve lo que se manda; ``True``
        no manda nada y ``False`` lo manda todo.

        :param option: ``hide_inputs`` o ``hide_outputs``.
        :type option: str
        :param payload: Entradas o salidas de la corrida.
        :type payload: dict
        :return: Lo que se mandaría a LangSmith.
        :rtype: dict
        """
        rule = self.options.get(option, False)
        if callable(rule):
            return rule(payload)
        return {} if rule else payload


@dataclass
class StubRun:
    """Una corrida registrada por el sustituto y lo que se mandaría de ella.

    :param options: Argumentos de ``traceable`` (``name``, ``run_type``...).
    :type options: dict
    :param failure: Falla que simula al agregar metadatos, o ``None``.
    :type failure: str or None
    """

    options: dict
    failure: str | None = None
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    added_metadata: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)

    @property
    def name(self):
        """Nombre de la traza."""
        return self.options.get("name")

    @property
    def run_type(self):
        """Tipo de corrida (``chain`` por omisión, como en LangSmith)."""
        return self.options.get("run_type", "chain")

    @property
    def metadata(self):
        """Metadatos fijos que se pasaron a ``traceable``."""
        return dict(self.options.get("metadata") or {})

    def add_metadata(self, metadata):
        """Agrega metadatos a la corrida, o falla si así se pidió.

        :param metadata: Metadatos nuevos.
        :type metadata: dict
        :raises RuntimeError: Si el sustituto simula que LangSmith los rechaza.
        """
        if self.failure == LangSmithStub.ADDING_METADATA:
            raise RuntimeError("stub: LangSmith rejected the metadata")
        self.added_metadata.update(metadata)

    def add_tags(self, tags):
        """Agrega etiquetas a la corrida.

        :param tags: Una etiqueta o una lista de etiquetas.
        :type tags: str or list[str]
        """
        self.tags.extend([tags] if isinstance(tags, str) else list(tags))

    def sent(self):
        """Todo lo que se mandaría de esta corrida, como texto.

        :return: Nombre, metadatos, entradas, salidas y etiquetas.
        :rtype: str
        """
        return repr(
            (
                self.name,
                self.metadata,
                self.inputs,
                self.outputs,
                self.added_metadata,
                self.tags,
            )
        )


class LangSmithStub:
    """Módulo ``langsmith`` sustituto: registra todo y nunca usa la red.

    ``failure`` simula una falla de LangSmith: ``READING_RUN`` (no se puede leer
    la corrida actual), ``ADDING_METADATA`` (se rechazan los metadatos) o
    ``SENDING`` (el envío falla en segundo plano y solo avisa en su logger).
    """

    READING_RUN = "reading the current run"
    ADDING_METADATA = "adding metadata"
    SENDING = "sending the trace"

    def __init__(self):
        self.clients = []
        self.decorations = []
        self.contexts = []
        self.runs = []
        self.failure = None
        self._active = []

    def install(self, monkeypatch):
        """Pone el módulo sustituto en ``sys.modules`` (también ``run_helpers``).

        :param monkeypatch: Fixture de pytest que lo quita al terminar.
        :type monkeypatch: pytest.MonkeyPatch
        """
        module = types.ModuleType("langsmith")
        helpers = types.ModuleType("langsmith.run_helpers")
        for target in (module, helpers):
            target.Client = self.client
            target.traceable = self.traceable
            target.tracing_context = self.tracing_context
            target.get_current_run_tree = self.get_current_run_tree
        module.run_helpers = helpers
        monkeypatch.setitem(sys.modules, "langsmith", module)
        monkeypatch.setitem(sys.modules, "langsmith.run_helpers", helpers)

    def client(self, **options):
        """Crea y registra un cliente sustituto.

        :return: El cliente.
        :rtype: StubLangSmithClient
        """
        created = StubLangSmithClient(**options)
        self.clients.append(created)
        return created

    def traceable(self, **options):
        """Decorador que registra cada llamada como una corrida.

        :return: El decorador.
        :rtype: collections.abc.Callable
        """
        self.decorations.append(options)

        def decorate(function):
            @functools.wraps(function)
            def traced(*args, **kwargs):
                client = options.get("client") or StubLangSmithClient()
                run = StubRun(options, failure=self.failure)
                run.inputs = client.hide(
                    "hide_inputs", {"args": list(args), "kwargs": dict(kwargs)}
                )
                self.runs.append(run)
                self._active.append(run)
                try:
                    result = function(*args, **kwargs)
                finally:
                    self._active.pop()
                self._finish(run, client, result)
                return result

            return traced

        return decorate

    def _finish(self, run, client, result):
        """Procesa y oculta las salidas, y simula el envío en segundo plano.

        :param run: La corrida.
        :type run: StubRun
        :param client: Cliente con las reglas de ocultar.
        :type client: StubLangSmithClient
        :param result: Lo que devolvió la función.
        :type result: object
        """
        process = run.options.get("process_outputs")
        outputs = process(result) if process else {"output": result}
        run.outputs = client.hide("hide_outputs", outputs)
        if self.failure == self.SENDING:
            # Como el hilo de envío de LangSmith: el error solo va a su logger.
            logging.getLogger("langsmith.client").warning(
                "stub: failed to send the run %s", run.name
            )

    def tracing_context(self, **options):
        """Registra las opciones del contexto de trazas.

        :return: Un contexto que no hace nada.
        :rtype: contextlib.AbstractContextManager
        """
        self.contexts.append(options)
        return contextlib.nullcontext()

    def get_current_run_tree(self):
        """La corrida que está abierta, o ``None``.

        :return: La corrida actual.
        :rtype: StubRun or None
        :raises RuntimeError: Si el sustituto simula que no puede leerla.
        """
        if self.failure == self.READING_RUN:
            raise RuntimeError("stub: LangSmith cannot read the current run")
        return self._active[-1] if self._active else None

    def runs_named(self, name):
        """Las corridas con ese nombre, en orden.

        :param name: Nombre de la traza (``agent_run``, ``model_complete``...).
        :type name: str
        :return: Las corridas.
        :rtype: list[StubRun]
        """
        return [run for run in self.runs if run.name == name]

    def sent(self):
        """Todo lo que se mandaría a LangSmith, como texto, para buscar fugas.

        :return: Las corridas y los metadatos de los contextos.
        :rtype: str
        """
        parts = [run.sent() for run in self.runs]
        parts.extend(repr(options.get("metadata")) for options in self.contexts)
        return "\n".join(parts)


@pytest.fixture
def langsmith_stub(monkeypatch):
    """Instala el módulo ``langsmith`` sustituto y lo devuelve.

    Al terminar apaga las trazas, para que no afecten a otras pruebas.
    """
    stub = LangSmithStub()
    stub.install(monkeypatch)
    yield stub
    tracing.configure(load_settings({}))


@pytest.fixture
def tracing_environ():
    """Variables que encienden las trazas con una clave de ejemplo."""
    return {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": LANGSMITH_TEST_KEY}
