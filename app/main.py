"""API web del Support Assistant (FastAPI, sin estado).

``create_app()`` recibe sus dependencias para que las pruebas inyecten las suyas;
``app`` se construye desde el entorno y falla al importar si la configuración es
inválida.
"""

import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app import tracing
from app.agent import Agent
from app.budget import DailyBudget
from app.config import GATEWAY_PROVIDER, ConfigError, load_settings
from app.costs import PriceError, PriceTable
from app.gateway import DEFAULT_TIMEOUT_SECONDS, GatewayModel, ModelUnavailable
from app.knowledge_base import KnowledgeBase, KnowledgeBaseError
from app.llm import FakeModel
from app.metrics import Metrics
from app.observability import (
    JsonLogger,
    SystemClock,
    install_request_middleware,
    new_request_id,
    silence_access_log,
)
from app.rate_limit import RateLimiter
from app.routing import Router
from app.security import (
    ApiKeyAuthenticator,
    PublicAccess,
    install_security_middleware,
)

PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"
Outcome = Literal["solved", "escalated", "needs_detail", "incomplete"]
MODEL_UNAVAILABLE = "model unavailable"
BAD_GATEWAY = 502
BUDGET_EXHAUSTED = "daily budget exhausted"
SERVICE_UNAVAILABLE = 503


class HistoryMessage(BaseModel):
    """Un mensaje anterior de la conversación que guarda el navegador.

    :param role: ``user`` o ``assistant``.
    :type role: str
    :param content: Texto del mensaje.
    :type content: str
    """

    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    """Cuerpo de ``POST /ask``.

    :param question: Pregunta de la persona.
    :type question: str
    :param history: Mensajes anteriores (opcional).
    :type history: list[HistoryMessage]
    """

    question: str
    history: list[HistoryMessage] = Field(default_factory=list)


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta para la persona.
    :type answer: str
    :param steps: Vueltas del bucle del agente.
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden.
    :type tools_used: list[str]
    :param escalated: Si hubo transferencia con el equipo humano.
    :type escalated: bool
    :param team: Equipo al que se transfirió, o ``None``.
    :type team: str or None
    :param input_tokens: Tokens de entrada del modelo.
    :type input_tokens: int
    :param output_tokens: Tokens de salida del modelo.
    :type output_tokens: int
    :param request_id: Folio de la petición.
    :type request_id: str
    :param outcome: Cómo terminó la pregunta.
    :type outcome: str
    :param model: Modelo que respondió.
    :type model: str
    :param route: Motivo del enrutador.
    :type route: str
    :param cached_calls: Llamadas que vinieron de la caché del gateway.
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD.
    :type cost_usd: float
    """

    answer: str
    steps: int
    tools_used: list[str]
    escalated: bool
    team: str | None
    input_tokens: int
    output_tokens: int
    request_id: str
    outcome: Outcome
    model: str
    route: str
    cached_calls: int
    cost_usd: float


def load_knowledge_base(settings):
    """Carga la base de conocimiento que indica la configuración.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :return: La base de conocimiento.
    :rtype: KnowledgeBase
    :raises ConfigError: Si el archivo de ``KB_PATH`` no tiene la forma descrita.
    """
    try:
        return KnowledgeBase.from_file(
            settings.kb_path,
            min_score=settings.kb_min_score,
            max_results=settings.kb_max_results,
        )
    except KnowledgeBaseError as error:
        raise ConfigError(f"KB_PATH inválido: {error}") from error


def load_prices(settings):
    """Carga la tabla de precios y exige que los dos modelos estén en ella.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :return: La tabla de precios.
    :rtype: app.costs.PriceTable
    :raises ConfigError: Si el archivo de ``PRICES_PATH`` es inválido o a un modelo
        configurado le falta precio (el mensaje lo nombra).
    """
    try:
        prices = PriceTable.from_file(settings.prices_path)
    except PriceError as error:
        raise ConfigError(f"PRICES_PATH inválido: {error}") from error
    try:
        prices.require([settings.model_small, settings.model_large])
    except PriceError as error:
        raise ConfigError(f"MODEL_SMALL o MODEL_LARGE inválido: {error}") from error
    return prices


def create_models(settings, http_client=None):
    """Crea los dos modelos configurados, por nombre.

    Con ``fake`` son modelos simulados con el nombre de ``MODEL_SMALL`` y
    ``MODEL_LARGE``; con ``gateway``, modelos de Workers AI que comparten el
    cliente HTTP.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :param http_client: Cliente HTTP del gateway; por omisión, uno nuevo con
        tiempo de espera fijo.
    :type http_client: httpx.Client or None
    :return: Los modelos por nombre.
    :rtype: dict[str, app.llm.ChatModel]
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider != GATEWAY_PROVIDER:
        return {name: FakeModel(name) for name in names}
    if http_client is None:
        http_client = httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
    return {
        name: GatewayModel(
            name=name,
            account_id=settings.cf_account_id,
            gateway_id=settings.cf_gateway_id,
            api_token=settings.cf_api_token,
            max_tokens=settings.model_max_tokens,
            temperature=settings.model_temperature,
            cache_ttl_seconds=settings.cache_ttl_seconds,
            http_client=http_client,
        )
        for name in names
    }


def build_agent(settings, model, knowledge_base, http_client=None):
    """Arma el agente con el enrutador, los precios y la ventana de historial.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :param model: Modelo inyectado que responde por los dos nombres, o ``None``
        para crear los modelos configurados.
    :type model: app.llm.ChatModel or None
    :param knowledge_base: Base de conocimiento.
    :type knowledge_base: KnowledgeBase
    :param http_client: Cliente HTTP del gateway, si se inyecta.
    :type http_client: httpx.Client or None
    :return: El agente.
    :rtype: app.agent.Agent
    :raises ConfigError: Si la tabla de precios es inválida o le falta un modelo.
    """
    prices = load_prices(settings)
    if model is None:
        models = create_models(settings, http_client)
    else:
        models = {settings.model_small: model, settings.model_large: model}
    router = Router(
        enabled=settings.routing,
        max_chars=settings.router_max_chars,
        small=settings.model_small,
        large=settings.model_large,
    )
    return Agent(
        models[settings.model_small],
        knowledge_base,
        max_steps=settings.agent_max_steps,
        max_question_chars=settings.max_question_chars,
        models=models,
        router=router,
        prices=prices,
        history_window=settings.history_window,
    )


def validate_question(question, max_chars):
    """Rechaza una pregunta vacía, en blanco o demasiado larga.

    :param question: Pregunta recibida.
    :type question: str
    :param max_chars: Largo máximo permitido.
    :type max_chars: int
    :raises HTTPException: Con código 422 si la pregunta es inválida.
    """
    if not question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    if len(question) > max_chars:
        raise HTTPException(
            status_code=422,
            detail=f"question must have at most {max_chars} characters",
        )


def agent_run_fields(question, history, result, log_conversation_text):
    """Campos del evento ``agent_run``.

    La pregunta y la respuesta solo se agregan con ``LOG_CONVERSATION_TEXT=true``;
    del historial solo se registra cuántos mensajes tiene, nunca su texto.

    :param question: Pregunta de la persona.
    :type question: str
    :param history: Mensajes anteriores.
    :type history: list[dict]
    :param result: Resultado del agente.
    :type result: app.agent.AgentResult
    :param log_conversation_text: Si se registra el texto de la conversación.
    :type log_conversation_text: bool
    :return: Los campos del evento.
    :rtype: dict
    """
    fields = {
        "question_chars": len(question),
        "history_messages": len(history),
        "steps": result.steps,
        "tools": list(result.tools_used),
        "outcome": result.outcome,
        "team": result.team,
        "article_id": result.article_id,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "stopped": result.stopped,
        "model": result.model,
        "route": result.route,
        "cached_calls": result.cached_calls,
        "cost_usd": result.cost_usd,
    }
    if log_conversation_text:
        fields["question"] = question
        fields["answer"] = result.answer
    return fields


def ask_response(result, request_id):
    """Arma el cuerpo de ``POST /ask`` a partir del resultado del agente.

    :param result: Resultado del agente.
    :type result: app.agent.AgentResult
    :param request_id: Folio de la petición.
    :type request_id: str
    :return: La respuesta validada.
    :rtype: AskResponse
    """
    return AskResponse(
        answer=result.answer,
        steps=result.steps,
        tools_used=list(result.tools_used),
        escalated=result.escalated,
        team=result.team,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        request_id=request_id,
        outcome=result.outcome,
        model=result.model,
        route=result.route,
        cached_calls=result.cached_calls,
        cost_usd=result.cost_usd,
    )


def budget_rejection(budget, logger, request_id):
    """Responde ``503`` porque la demo alcanzó su tope de gasto de hoy.

    El evento ``budget_exhausted`` (con lo gastado y el tope) se escribe solo la
    primera vez del día UTC. El modelo no se llama.

    :param budget: Tope de gasto diario de la demo.
    :type budget: app.budget.DailyBudget
    :param logger: Log de eventos.
    :type logger: app.observability.JsonLogger
    :param request_id: Folio de la petición.
    :type request_id: str
    :return: La respuesta ``503`` con el folio.
    :rtype: fastapi.responses.JSONResponse
    """
    if budget.claim_exhaustion_notice():
        snapshot = budget.snapshot()
        logger.log(
            "budget_exhausted",
            request_id,
            spent_usd=snapshot["public_cost_today_usd"],
            budget_usd=snapshot["daily_budget_usd"],
        )
    return JSONResponse(
        status_code=SERVICE_UNAVAILABLE,
        content={"detail": BUDGET_EXHAUSTED, "request_id": request_id},
    )


# Las rutas necesitan cada dependencia por nombre; agruparlas no aclara nada.
def _add_routes(  # pylint: disable=too-many-arguments
    application, agent, settings, logger, metrics, *, budget
):
    """Registra las rutas de la API.

    :param application: La aplicación FastAPI.
    :type application: fastapi.FastAPI
    :param agent: El agente que responde.
    :type agent: app.agent.Agent
    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :param logger: Log de eventos.
    :type logger: app.observability.JsonLogger
    :param metrics: Métricas del proceso.
    :type metrics: app.metrics.Metrics
    :param budget: Tope de gasto diario de las preguntas sin clave.
    :type budget: app.budget.DailyBudget
    """
    page = PAGE_PATH.read_text(encoding="utf-8")

    @application.get("/", response_class=HTMLResponse)
    def home():
        """La página web para los empleados."""
        return HTMLResponse(page)

    @application.get("/health")
    def health():
        """Estado del proceso."""
        return {"status": "ok", "pid": os.getpid()}

    @application.get("/metrics")
    def process_metrics():
        """Métricas de este proceso y el gasto público de hoy."""
        snapshot = metrics.snapshot(slo_p95_ms=settings.slo_p95_ms)
        return {"pid": os.getpid(), **snapshot, **budget.snapshot()}

    @application.post("/ask", response_model=AskResponse)
    def ask(payload: AskRequest, request: Request):
        """Responde una pregunta; el historial lo manda el cliente."""
        validate_question(payload.question, settings.max_question_chars)
        request_id = request.state.request_id
        # Solo el nombre del cliente; la clave y la IP nunca salen del middleware.
        client = request.state.api_client
        is_public = getattr(request.state, "is_public", False)
        if is_public and budget.is_exhausted():
            return budget_rejection(budget, logger, request_id)
        history = [message.model_dump() for message in payload.history]
        try:
            with tracing.trace_context(request_id, client):
                result = agent.run(
                    payload.question,
                    history,
                    on_tool_call=lambda audit: logger.log(
                        "audit", request_id, client=client, **audit
                    ),
                    client=client,
                )
        except ModelUnavailable as error:
            # Solo el tipo: el mensaje nunca lleva la cuenta, el token ni el cuerpo.
            logger.log(
                "error", request_id, client=client, error_type=error.error_type
            )
            return JSONResponse(
                status_code=BAD_GATEWAY,
                content={"detail": MODEL_UNAVAILABLE, "request_id": request_id},
            )
        if is_public:
            budget.record(result.cost_usd)
        metrics.record_answer(
            outcome=result.outcome,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        logger.log(
            "agent_run",
            request_id,
            client=client,
            **agent_run_fields(
                payload.question, history, result, settings.log_conversation_text
            ),
        )
        return ask_response(result, request_id)


# Las pruebas inyectan cada dependencia por nombre; agruparlas cambiaría la firma.
def create_app(  # pylint: disable=too-many-arguments
    settings=None,
    model=None,
    knowledge_base=None,
    *,
    clock=None,
    metrics=None,
    log_sink=None,
    id_factory=None,
    http_client=None,
):
    """Arma la aplicación con sus dependencias.

    :param settings: Configuración; por omisión, la del entorno.
    :type settings: app.config.Settings or None
    :param model: Modelo con ``complete(messages)`` que responde por
        ``MODEL_SMALL`` y ``MODEL_LARGE`` (se cobra con el precio del elegido); por
        omisión, se crean los dos modelos configurados.
    :type model: app.llm.ChatModel or None
    :param knowledge_base: Base de conocimiento; por omisión, la de ``KB_PATH``.
    :type knowledge_base: KnowledgeBase or None
    :param clock: Reloj con ``now()`` en UTC (latencia y límite de peticiones); por
        omisión, el del sistema.
    :type clock: app.observability.Clock or None
    :param metrics: Métricas del proceso; por omisión, unas nuevas.
    :type metrics: app.metrics.Metrics or None
    :param log_sink: Destino del log JSON; por omisión, la salida estándar.
    :type log_sink: typing.TextIO or None
    :param id_factory: Función que genera folios; por omisión, UUID aleatorios.
    :type id_factory: collections.abc.Callable or None
    :param http_client: Cliente HTTP del modelo real (las pruebas inyectan uno sin
        red); por omisión, uno nuevo con tiempo de espera fijo.
    :type http_client: httpx.Client or None
    :return: La aplicación FastAPI.
    :rtype: fastapi.FastAPI
    :raises ConfigError: Si la configuración, la base de conocimiento o la tabla de
        precios son inválidas, o a un modelo le falta precio.
    """
    if settings is None:
        settings = load_settings()
    if knowledge_base is None:
        knowledge_base = load_knowledge_base(settings)
    clock = clock if clock is not None else SystemClock()
    metrics = metrics if metrics is not None else Metrics()
    tracing.configure(settings)
    agent = build_agent(settings, model, knowledge_base, http_client)
    logger = JsonLogger(sink=log_sink, clock=clock, service=settings.service_name)
    silence_access_log()
    application = FastAPI(title="Support Assistant")
    # En Starlette el último middleware agregado queda por fuera: el de seguridad va
    # primero para que el de observabilidad dé folio y evento a los 401 y 429.
    budget = DailyBudget(settings.daily_budget_usd, clock)
    public_access = None
    if settings.public_page:
        public_access = PublicAccess(
            limiter=RateLimiter(settings.public_rate_limit_per_minute, clock),
            trust_proxy=settings.trust_proxy,
        )
    install_security_middleware(
        application,
        ApiKeyAuthenticator(settings.api_keys),
        RateLimiter(settings.rate_limit_per_minute, clock),
        public_access=public_access,
    )
    install_request_middleware(
        application, logger, metrics, clock, id_factory or new_request_id
    )
    _add_routes(application, agent, settings, logger, metrics, budget=budget)
    return application


app = create_app()
