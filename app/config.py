"""Configuración del Support Assistant a partir de variables de entorno.

Un valor inválido impide arrancar con un mensaje que nombra la variable (nunca su
valor, si es un secreto). Al arrancar desde el entorno real se lee además el archivo
de ``ENV_FILE`` sin sobrescribir el entorno (ADR 0009).
"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from app.compliance import check_production
from app.errors import ConfigError
from app.security import PUBLIC_CLIENT, ApiKeysError, parse_api_keys

__all__ = ["ConfigError", "Settings", "load_env_file", "load_settings"]

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
FAKE_PROVIDER = "fake"
GATEWAY_PROVIDER = "gateway"
SUPPORTED_PROVIDERS = (FAKE_PROVIDER, GATEWAY_PROVIDER)
GATEWAY_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")
ENV_FILE_VARIABLE = "ENV_FILE"
DEFAULT_ENV_FILE = ".env"
NO_ENV_FILE = "none"
DEFAULTS = {
    "MODEL_PROVIDER": "fake",
    "AGENT_MAX_STEPS": "4",
    "MAX_QUESTION_CHARS": "2000",
    "KB_PATH": "data/knowledge_base.json",
    "KB_MIN_SCORE": "2",
    "KB_MAX_RESULTS": "2",
    "SERVICE_NAME": "support-assistant",
    "SLO_P95_MS": "4000",
    "LOG_CONVERSATION_TEXT": "true",
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_PROJECT": "support-assistant",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
    "CF_ACCOUNT_ID": "",
    "CF_GATEWAY_ID": "default",
    "CF_API_TOKEN": "",
    "MODEL_SMALL": "@cf/meta/llama-3.1-8b-instruct-fast",
    "MODEL_LARGE": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "ROUTING": "true",
    "ROUTER_MAX_CHARS": "80",
    "HISTORY_WINDOW": "6",
    "MODEL_MAX_TOKENS": "300",
    "MODEL_TEMPERATURE": "0",
    "CACHE_TTL_SECONDS": "0",
    "PRICES_PATH": "data/model_prices.json",
    "ENVIRONMENT": "development",
    "API_KEYS": "",
    "RATE_LIMIT_PER_MINUTE": "30",
    "PUBLIC_PAGE": "false",
    "TRUST_PROXY": "false",
    "PUBLIC_RATE_LIMIT_PER_MINUTE": "5",
    "DAILY_BUDGET_USD": "0.50",
}
BOOLEANS = {"true": True, "false": False}
LANGSMITH_KEY_VARIABLE = "LANGSMITH_API_KEY"
SUPPORTED_ENVIRONMENTS = ("development", "production")

# Una configuración plana tiene un atributo por variable de entorno.
@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuración validada e inmutable.

    La clave de LangSmith no se guarda aquí (no aparece en ``repr``): solo se
    registra si existe, en ``tracing_enabled``. La cuenta y el token de Cloudflare
    se guardan, pero nunca aparecen en ``repr``.

    :param model_provider: Qué modelo usar: ``fake`` o ``gateway``.
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente.
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta.
    :type max_question_chars: int
    :param kb_path: Ruta absoluta de la base de conocimiento.
    :type kb_path: pathlib.Path
    :param kb_min_score: Palabras clave que deben coincidir para ofrecer un artículo.
    :type kb_min_score: int
    :param kb_max_results: Artículos que devuelve la búsqueda como máximo.
    :type kb_max_results: int
    :param service_name: Campo ``service`` de cada línea del log.
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :type slo_p95_ms: int
    :param log_conversation_text: Registrar pregunta y respuesta en ``agent_run``.
    :type log_conversation_text: bool
    :param langsmith_tracing: Si se pidieron las trazas en LangSmith.
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar a LangSmith las entradas.
    :type hide_inputs: bool
    :param hide_outputs: No mandar a LangSmith las salidas.
    :type hide_outputs: bool
    :param tracing_enabled: Trazas pedidas y con clave presente.
    :type tracing_enabled: bool
    :param cf_account_id: Cuenta de Cloudflare (no aparece en ``repr``).
    :type cf_account_id: str
    :param cf_gateway_id: Nombre del AI Gateway.
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto; no aparece en ``repr``).
    :type cf_api_token: str
    :param model_small: Nombre del modelo barato.
    :type model_small: str
    :param model_large: Nombre del modelo capaz.
    :type model_large: str
    :param routing: Si el enrutador elige el modelo por pregunta.
    :type routing: bool
    :param router_max_chars: Preguntas más largas van al modelo capaz.
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo (0: ninguno).
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada.
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo.
    :type model_temperature: float
    :param cache_ttl_seconds: Segundos de caché del gateway (0: apagada).
    :type cache_ttl_seconds: int
    :param prices_path: Ruta absoluta de la tabla de precios.
    :type prices_path: pathlib.Path
    :param environment: ``development`` o ``production`` (aplica compliance).
    :type environment: str
    :param api_keys: Clientes y sus claves (secreto; no aparece en ``repr``).
    :type api_keys: tuple[app.security.ApiClient, ...]
    :param rate_limit_per_minute: Peticiones por cliente por minuto.
    :type rate_limit_per_minute: int
    :param public_page: Modo demo: ``POST /ask`` sin clave, como el cliente
        ``public``.
    :type public_page: bool
    :param trust_proxy: Leer la IP de la última entrada de ``X-Forwarded-For``.
    :type trust_proxy: bool
    :param public_rate_limit_per_minute: Preguntas sin clave por IP por minuto.
    :type public_rate_limit_per_minute: int
    :param daily_budget_usd: Tope de gasto diario de las preguntas sin clave.
    :type daily_budget_usd: float
    :param langsmith_project: Proyecto de LangSmith donde caen las trazas.
    :type langsmith_project: str
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    kb_path: Path
    kb_min_score: int
    kb_max_results: int
    service_name: str
    slo_p95_ms: int
    log_conversation_text: bool
    langsmith_tracing: bool
    hide_inputs: bool
    hide_outputs: bool
    tracing_enabled: bool
    cf_account_id: str = field(default="", repr=False)
    cf_gateway_id: str = DEFAULTS["CF_GATEWAY_ID"]
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULTS["MODEL_SMALL"]
    model_large: str = DEFAULTS["MODEL_LARGE"]
    routing: bool = True
    router_max_chars: int = int(DEFAULTS["ROUTER_MAX_CHARS"])
    history_window: int = int(DEFAULTS["HISTORY_WINDOW"])
    model_max_tokens: int = int(DEFAULTS["MODEL_MAX_TOKENS"])
    model_temperature: float = float(DEFAULTS["MODEL_TEMPERATURE"])
    cache_ttl_seconds: int = int(DEFAULTS["CACHE_TTL_SECONDS"])
    prices_path: Path = PRODUCT_ROOT / DEFAULTS["PRICES_PATH"]
    environment: str = DEFAULTS["ENVIRONMENT"]
    api_keys: tuple = field(default=(), repr=False)
    rate_limit_per_minute: int = int(DEFAULTS["RATE_LIMIT_PER_MINUTE"])
    public_page: bool = False
    trust_proxy: bool = False
    public_rate_limit_per_minute: int = int(
        DEFAULTS["PUBLIC_RATE_LIMIT_PER_MINUTE"]
    )
    daily_budget_usd: float = float(DEFAULTS["DAILY_BUDGET_USD"])
    langsmith_project: str = DEFAULTS["LANGSMITH_PROJECT"]


def _read(environ, name):
    """Lee una variable o su valor por omisión, sin espacios a los lados.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El valor como texto.
    :rtype: str
    """
    return str(environ.get(name, DEFAULTS[name])).strip()


def _int_at_least(environ, name, minimum):
    """Lee una variable que debe ser un entero mayor o igual que ``minimum``.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :param minimum: Valor mínimo permitido.
    :type minimum: int
    :return: El entero leído.
    :rtype: int
    :raises ConfigError: Si no es un entero o es menor que ``minimum``.
    """
    raw = _read(environ, name)
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} debe ser un entero; se recibió {raw!r}") from error
    if value < minimum:
        raise ConfigError(f"{name} debe ser {minimum} o más; se recibió {value}")
    return value


def _positive_int(environ, name):
    """Lee una variable que debe ser un entero mayor que cero.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El entero leído.
    :rtype: int
    :raises ConfigError: Si no es un entero o es menor que 1.
    """
    return _int_at_least(environ, name, 1)


def _non_negative_int(environ, name):
    """Lee una variable que debe ser un entero de 0 o más.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El entero leído.
    :rtype: int
    :raises ConfigError: Si no es un entero o es negativo.
    """
    return _int_at_least(environ, name, 0)


def _non_negative_float(environ, name):
    """Lee una variable que debe ser un número finito de 0 o más.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El número leído.
    :rtype: float
    :raises ConfigError: Si no es un número finito o es negativo.
    """
    raw = _read(environ, name)
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{name} debe ser un número; se recibió {raw!r}") from error
    if not math.isfinite(value) or value < 0:
        raise ConfigError(f"{name} debe ser un número de 0 o más; se recibió {raw!r}")
    return value


def _boolean(environ, name):
    """Lee una variable que debe valer ``true`` o ``false``.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El valor booleano.
    :rtype: bool
    :raises ConfigError: Si el valor no es ``true`` ni ``false``.
    """
    raw = _read(environ, name).lower()
    if raw not in BOOLEANS:
        raise ConfigError(f"{name} debe ser true o false; se recibió {raw!r}")
    return BOOLEANS[raw]


def _text(environ, name):
    """Lee una variable que debe ser texto no vacío.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable.
    :type name: str
    :return: El texto sin espacios a los lados.
    :rtype: str
    :raises ConfigError: Si está vacía.
    """
    value = _read(environ, name)
    if not value:
        raise ConfigError(f"{name} no puede estar vacía")
    return value


def _has_langsmith_key(environ):
    """Indica si hay clave de LangSmith, sin devolverla ni guardarla.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :return: ``True`` si ``LANGSMITH_API_KEY`` tiene un valor.
    :rtype: bool
    """
    return bool(str(environ.get(LANGSMITH_KEY_VARIABLE, "")).strip())


def _provider(environ):
    """Lee y valida ``MODEL_PROVIDER``.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :return: El proveedor en minúsculas.
    :rtype: str
    :raises ConfigError: Si el proveedor no existe.
    """
    provider = _read(environ, "MODEL_PROVIDER").lower()
    if provider not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(
            f"MODEL_PROVIDER debe ser uno de: {allowed}; se recibió {provider!r}"
        )
    return provider


def _environment(environ):
    """Lee y valida ``ENVIRONMENT``.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :return: El entorno en minúsculas.
    :rtype: str
    :raises ConfigError: Si el entorno no es ``development`` ni ``production``.
    """
    environment = _read(environ, "ENVIRONMENT").lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        allowed = ", ".join(SUPPORTED_ENVIRONMENTS)
        raise ConfigError(
            f"ENVIRONMENT debe ser uno de: {allowed}; se recibió {environment!r}"
        )
    return environment


def _api_keys(environ):
    """Lee e interpreta ``API_KEYS``.

    El error dice qué entrada falla y su largo, nunca su valor, y se lanza sin la
    excepción original (``from None``).

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :return: Los clientes configurados (vacía si no hay ninguno).
    :rtype: tuple[app.security.ApiClient, ...]
    :raises ConfigError: Si ``API_KEYS`` está mal formada.
    """
    try:
        return parse_api_keys(_read(environ, "API_KEYS"))
    except ApiKeysError as error:
        raise ConfigError(f"API_KEYS inválida: {error}") from None


def _product_path(raw):
    """Convierte una ruta en absoluta; una relativa se resuelve contra ``product/``.

    :param raw: La ruta como texto.
    :type raw: str
    :return: La ruta absoluta.
    :rtype: pathlib.Path
    """
    path = Path(raw)
    return path if path.is_absolute() else PRODUCT_ROOT / path


def _file_path(environ, name):
    """Lee una variable con la ruta de un archivo que debe existir.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param name: Nombre de la variable (``KB_PATH`` o ``PRICES_PATH``).
    :type name: str
    :return: La ruta absoluta del archivo.
    :rtype: pathlib.Path
    :raises ConfigError: Si el archivo no existe.
    """
    path = _product_path(_read(environ, name))
    if not path.is_file():
        raise ConfigError(f"{name} no apunta a un archivo existente: {path}")
    return path


def _gateway_values(environ, provider):
    """Lee las tres variables ``CF_*``; con ``gateway`` ninguna puede estar vacía.

    El mensaje de error nombra la variable, nunca su valor.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping
    :param provider: El proveedor ya validado.
    :type provider: str
    :return: Los valores por nombre de variable.
    :rtype: dict[str, str]
    :raises ConfigError: Si falta una variable con ``MODEL_PROVIDER=gateway``.
    """
    values = {name: _read(environ, name) for name in GATEWAY_VARIABLES}
    if provider == GATEWAY_PROVIDER:
        for name in GATEWAY_VARIABLES:
            if not values[name]:
                raise ConfigError(
                    f"{name} es obligatoria con MODEL_PROVIDER={GATEWAY_PROVIDER}"
                )
    return values


def _check_demo(settings):
    """Reglas del modo demo: con ``PUBLIC_PAGE=true`` hay tope, límite y nombre libre.

    Sin modo demo no hace nada (por ejemplo, ``DAILY_BUDGET_USD=0`` se acepta). El
    error nombra la variable, nunca una clave.

    :param settings: Configuración ya leída.
    :type settings: Settings
    :raises ConfigError: Si el tope o el límite por IP no son mayores que 0, o si
        ``API_KEYS`` tiene un cliente con el nombre reservado ``public``.
    """
    if not settings.public_page:
        return
    if settings.daily_budget_usd <= 0:
        raise ConfigError(
            "DAILY_BUDGET_USD debe ser mayor que 0 con PUBLIC_PAGE=true; "
            f"se recibió {settings.daily_budget_usd}"
        )
    if settings.public_rate_limit_per_minute <= 0:
        raise ConfigError(
            "PUBLIC_RATE_LIMIT_PER_MINUTE debe ser mayor que 0 con "
            f"PUBLIC_PAGE=true; se recibió {settings.public_rate_limit_per_minute}"
        )
    for number, client in enumerate(settings.api_keys, start=1):
        if client.name == PUBLIC_CLIENT:
            raise ConfigError(
                f"API_KEYS no puede tener un cliente llamado {PUBLIC_CLIENT} con "
                f"PUBLIC_PAGE=true (nombre reservado); la entrada {number} lo usa"
            )


def load_env_file():
    """Lee el archivo de ``ENV_FILE`` sin sobrescribir el entorno del proceso.

    Por omisión es ``.env``; una ruta relativa se resuelve contra ``product/``. Si
    el archivo no existe no pasa nada, y con ``ENV_FILE=none`` no se lee ninguno.
    """
    raw = os.environ.get(ENV_FILE_VARIABLE, DEFAULT_ENV_FILE).strip()
    if not raw or raw.lower() == NO_ENV_FILE:
        return
    path = _product_path(raw)
    if path.is_file():
        load_dotenv(path, override=False)


def load_settings(environ=None):
    """Construye la configuración desde las variables de entorno.

    Solo sin argumentos (el arranque real) se lee antes el archivo de ``ENV_FILE``;
    con un ``environ`` propio nunca se lee ni se cambia ``os.environ``.

    :param environ: Variables a usar; por omisión, las del proceso.
    :type environ: collections.abc.Mapping or None
    :return: La configuración validada.
    :rtype: Settings
    :raises ConfigError: Si alguna variable tiene un valor inválido o, con
        ``ENVIRONMENT=production``, si falla una regla de compliance.
    """
    if environ is None:
        load_env_file()
        environ = os.environ
    provider = _provider(environ)
    cloudflare = _gateway_values(environ, provider)
    langsmith_tracing = _boolean(environ, "LANGSMITH_TRACING")
    settings = Settings(
        model_provider=provider,
        agent_max_steps=_positive_int(environ, "AGENT_MAX_STEPS"),
        max_question_chars=_positive_int(environ, "MAX_QUESTION_CHARS"),
        kb_path=_file_path(environ, "KB_PATH"),
        kb_min_score=_positive_int(environ, "KB_MIN_SCORE"),
        kb_max_results=_positive_int(environ, "KB_MAX_RESULTS"),
        service_name=_text(environ, "SERVICE_NAME"),
        slo_p95_ms=_positive_int(environ, "SLO_P95_MS"),
        log_conversation_text=_boolean(environ, "LOG_CONVERSATION_TEXT"),
        langsmith_tracing=langsmith_tracing,
        hide_inputs=_boolean(environ, "HIDE_INPUTS"),
        hide_outputs=_boolean(environ, "HIDE_OUTPUTS"),
        tracing_enabled=langsmith_tracing and _has_langsmith_key(environ),
        cf_account_id=cloudflare["CF_ACCOUNT_ID"],
        cf_gateway_id=cloudflare["CF_GATEWAY_ID"],
        cf_api_token=cloudflare["CF_API_TOKEN"],
        model_small=_text(environ, "MODEL_SMALL"),
        model_large=_text(environ, "MODEL_LARGE"),
        routing=_boolean(environ, "ROUTING"),
        router_max_chars=_positive_int(environ, "ROUTER_MAX_CHARS"),
        history_window=_non_negative_int(environ, "HISTORY_WINDOW"),
        model_max_tokens=_positive_int(environ, "MODEL_MAX_TOKENS"),
        model_temperature=_non_negative_float(environ, "MODEL_TEMPERATURE"),
        cache_ttl_seconds=_non_negative_int(environ, "CACHE_TTL_SECONDS"),
        prices_path=_file_path(environ, "PRICES_PATH"),
        environment=_environment(environ),
        api_keys=_api_keys(environ),
        rate_limit_per_minute=_positive_int(environ, "RATE_LIMIT_PER_MINUTE"),
        public_page=_boolean(environ, "PUBLIC_PAGE"),
        trust_proxy=_boolean(environ, "TRUST_PROXY"),
        public_rate_limit_per_minute=_non_negative_int(
            environ, "PUBLIC_RATE_LIMIT_PER_MINUTE"
        ),
        daily_budget_usd=_non_negative_float(environ, "DAILY_BUDGET_USD"),
        langsmith_project=_text(environ, "LANGSMITH_PROJECT"),
    )
    _check_demo(settings)
    check_production(settings)
    return settings
