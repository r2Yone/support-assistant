"""Modelo real: Workers AI de Cloudflare a través de AI Gateway (ADR 0007).

``GatewayModel`` es otra implementación de ``complete(messages)``: antepone el prompt
de sistema, hace un solo ``POST`` (sin reintentos) con el cliente ``httpx`` inyectado
y lee el texto, los tokens y si la respuesta vino de la caché. El token va en
``Authorization`` y en el encabezado del gateway autenticado de Cloudflare. Cualquier
falla se convierte en ``ModelUnavailable``, que nunca lleva la URL (con la cuenta),
el token, los encabezados ni el cuerpo de la respuesta del proveedor.
"""

import json
import logging

import httpx

from app.llm import (
    ESCALATE_TOOL,
    GENERAL_CATEGORY,
    SEARCH_TOOL,
    TOOL_RESULT_PREFIX,
    Completion,
)

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
    "/workers-ai/v1/chat/completions"
)
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
GATEWAY_AUTH_HEADER = "cf-aig-authorization"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
DEFAULT_TIMEOUT_SECONDS = 30.0
GATEWAY_PROVIDER_NAME = "cloudflare"
INVALID_JSON = "invalid_json"
INVALID_RESPONSE = "invalid_response"
SYSTEM_PROMPT = (
    "Eres el primer nivel de la mesa de ayuda de la empresa: atiendes a empleados "
    "que describen con sus palabras un problema de tecnología.\n"
    "Protocolo: responde siempre con un solo objeto JSON, sin texto antes ni "
    "después, con una de estas dos formas:\n"
    '- {"tool": "<herramienta>", "args": {...}} para pedir una herramienta.\n'
    '- {"answer": "<texto>"} para responder a la persona.\n'
    "Herramientas:\n"
    f'- {SEARCH_TOOL} con args {{"problem": "<el problema con las palabras de la '
    'persona>"}: busca artículos vigentes en la base de conocimiento.\n'
    f'- {ESCALATE_TOOL} con args {{"category": "<categoría>"}}: transfiere con el '
    f"equipo humano de esa categoría (usa {GENERAL_CATEGORY} si no sabes cuál).\n"
    "El resultado de cada herramienta llega en un mensaje que empieza con "
    f'"{TOOL_RESULT_PREFIX}".\n'
    "Reglas:\n"
    f"1. Antes de responder sobre un problema, busca con {SEARCH_TOOL}.\n"
    "2. Responde solo con soluciones que vengan de la base de conocimiento y cita "
    "el id del artículo (por ejemplo, KB-0001).\n"
    f"3. Usa {ESCALATE_TOOL} cuando la búsqueda no da artículos o cuando la persona "
    "pide hablar con alguien.\n"
    "4. Si el mensaje no describe un problema, pide más detalle.\n"
    "5. Responde siempre en español."
)

# La biblioteca httpx registra la URL de cada petición (con la cuenta) en INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)


class ModelUnavailable(RuntimeError):
    """El modelo real no respondió como se esperaba.

    El mensaje es fijo y solo nombra el tipo de error: nunca la cuenta, el token ni
    el cuerpo de la respuesta del proveedor.

    :param error_type: Tipo de error (por ejemplo ``ConnectError`` o ``http_500``).
    :type error_type: str
    """

    def __init__(self, error_type):
        super().__init__(f"model unavailable: {error_type}")
        self.error_type = error_type


def extract_json_object(text):
    """Devuelve el primer objeto JSON que aparece en el texto del modelo.

    Un modelo real a veces agrega texto o bloques de código alrededor del JSON. Si no
    hay ningún objeto, se devuelve el texto tal cual (el agente lo trata como error).

    :param text: Texto que devolvió el modelo.
    :type text: str
    :return: El objeto JSON en texto, o el texto original.
    :rtype: str
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            value, end = None, start
        if isinstance(value, dict):
            return text[start:end]
        start = text.find("{", start + 1)
    return text


def _read_body(data):
    """Lee el texto y los tokens de una respuesta de chat completions.

    :param data: Cuerpo de la respuesta ya interpretado.
    :type data: object
    :return: El texto del modelo, los tokens de entrada y los de salida.
    :rtype: tuple[str, int, int]
    :raises ModelUnavailable: Si el cuerpo no tiene la forma esperada.
    """
    try:
        content = data["choices"][0]["message"]["content"]
        usage = data["usage"]
        tokens = (int(usage["prompt_tokens"]), int(usage["completion_tokens"]))
    except (KeyError, IndexError, TypeError, ValueError):
        raise ModelUnavailable(INVALID_RESPONSE) from None
    if not isinstance(content, str):
        raise ModelUnavailable(INVALID_RESPONSE)
    return content, tokens[0], tokens[1]


class GatewayModel:
    """Modelo de Workers AI a través de AI Gateway.

    :param name: Nombre del modelo de Workers AI.
    :type name: str
    :param account_id: Cuenta de Cloudflare (``CF_ACCOUNT_ID``).
    :type account_id: str
    :param gateway_id: Nombre del gateway (``CF_GATEWAY_ID``).
    :type gateway_id: str
    :param api_token: Token de Cloudflare (``CF_API_TOKEN``).
    :type api_token: str
    :param max_tokens: Tope de tokens de salida (``MODEL_MAX_TOKENS``).
    :type max_tokens: int
    :param temperature: Temperatura (``MODEL_TEMPERATURE``).
    :type temperature: float
    :param cache_ttl_seconds: Segundos de caché del gateway; 0 la apaga.
    :type cache_ttl_seconds: int
    :param http_client: Cliente HTTP (las pruebas inyectan uno sin red).
    :type http_client: httpx.Client
    """

    # Proveedor que ven las trazas en ``ls_provider`` (ADR 0016).
    provider = GATEWAY_PROVIDER_NAME

    # Cada argumento es una variable de configuración; se pasan por nombre.
    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        name,
        account_id,
        gateway_id,
        api_token,
        max_tokens,
        temperature,
        cache_ttl_seconds,
        http_client,
    ):
        self.name = name
        self._url = GATEWAY_URL.format(account_id=account_id, gateway_id=gateway_id)
        # El mismo token sirve para Workers AI y para el gateway autenticado.
        bearer = f"Bearer {api_token}"
        self._headers = {"Authorization": bearer, GATEWAY_AUTH_HEADER: bearer}
        if cache_ttl_seconds > 0:
            self._headers[CACHE_TTL_HEADER] = str(cache_ttl_seconds)
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = http_client

    def __repr__(self):
        """Representación sin la cuenta ni el token.

        :return: El nombre de la clase y del modelo.
        :rtype: str
        """
        return f"GatewayModel(name={self.name!r})"

    def complete(self, messages):
        """Manda la conversación al modelo en una sola petición.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: list[dict]
        :return: El texto del modelo, sus tokens y si vino de la caché.
        :rtype: app.llm.Completion
        :raises ModelUnavailable: Ante un error de red, un código no 2xx o una
            respuesta sin la forma esperada.
        """
        response = self._post(messages)
        data = self._json(response)
        text, input_tokens, output_tokens = _read_body(data)
        cache_status = response.headers.get(CACHE_STATUS_HEADER, "")
        return Completion(
            text=extract_json_object(text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=cache_status.strip().upper() == CACHE_HIT,
        )

    def _post(self, messages):
        """Hace el único ``POST`` al gateway.

        :param messages: Mensajes de la conversación (sin el de sistema).
        :type messages: list[dict]
        :return: La respuesta HTTP exitosa.
        :rtype: httpx.Response
        :raises ModelUnavailable: Ante un error de red o un código no 2xx.
        """
        body = {
            "model": self.name,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}]
            + [dict(message) for message in messages],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        try:
            response = self._client.post(self._url, headers=self._headers, json=body)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # ``from None``: la excepción original lleva la URL con la cuenta.
            raise ModelUnavailable(type(error).__name__) from None
        if not response.is_success:
            raise ModelUnavailable(f"http_{response.status_code}")
        return response

    @staticmethod
    def _json(response):
        """Interpreta el cuerpo de la respuesta como JSON.

        :param response: Respuesta HTTP exitosa.
        :type response: httpx.Response
        :return: El cuerpo interpretado.
        :rtype: object
        :raises ModelUnavailable: Si el cuerpo no es JSON.
        """
        try:
            return response.json()
        except ValueError:
            raise ModelUnavailable(INVALID_JSON) from None
