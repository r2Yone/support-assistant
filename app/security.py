"""Claves por cliente y middleware que protege la API (ADR 0010, 0013 y 0014).

``API_KEYS`` tiene la forma ``cliente:clave,cliente2:clave2``. Una clave nunca se
escribe en el log, en la traza ni en un mensaje de error: los errores solo dicen el
número de la entrada (desde 1) y su largo.

En modo demo (``PUBLIC_PAGE=true``) ``POST /ask`` sin ``X-API-Key`` se atiende como
el cliente ``public``, con un límite por dirección IP. La IP es un dato personal:
solo vive en una variable local y como llave del limitador; nunca va a
``request.state``, al log, a la traza ni a un error.
"""

import hmac
from dataclasses import dataclass, field

from fastapi.responses import JSONResponse

API_KEY_HEADER = "X-API-Key"
FORWARDED_FOR_HEADER = "X-Forwarded-For"
RETRY_AFTER_HEADER = "Retry-After"
ASK_PATH = "/ask"
PROTECTED_PATHS = frozenset({ASK_PATH, "/metrics"})
PUBLIC_CLIENT = "public"
UNKNOWN_ADDRESS = "unknown"
INVALID_KEY = "invalid or missing API key"
RATE_LIMITED = "rate limit exceeded"
UNAUTHORIZED = 401
TOO_MANY_REQUESTS = 429
ENTRY_SEPARATOR = ","
KEY_SEPARATOR = ":"


class ApiKeysError(ValueError):
    """``API_KEYS`` está mal formada; el mensaje nunca lleva una clave."""


@dataclass(frozen=True)
class ApiClient:
    """Un cliente de la API con su clave.

    :param name: Nombre del cliente (va en el log y en la traza).
    :type name: str
    :param key: Clave del cliente (secreto; no aparece en ``repr``).
    :type key: str
    """

    name: str
    key: str = field(repr=False)


def _entry_error(number, entry, problem):
    """Arma el error de una entrada sin incluir su valor.

    :param number: Número de la entrada, desde 1.
    :type number: int
    :param entry: La entrada completa (solo se usa su largo).
    :type entry: str
    :param problem: Qué le falta o qué repite la entrada.
    :type problem: str
    :return: El error listo para lanzar.
    :rtype: ApiKeysError
    """
    return ApiKeysError(f"la entrada {number} {problem} (largo {len(entry)})")


def _parse_entry(number, entry):
    """Interpreta una entrada ``cliente:clave``.

    :param number: Número de la entrada, desde 1.
    :type number: int
    :param entry: La entrada sin espacios a los lados.
    :type entry: str
    :return: El cliente.
    :rtype: ApiClient
    :raises ApiKeysError: Si no tiene ``:`` o el cliente o la clave están vacíos.
    """
    if KEY_SEPARATOR not in entry:
        raise _entry_error(number, entry, "no tiene la forma cliente:clave")
    name, key = (part.strip() for part in entry.split(KEY_SEPARATOR, 1))
    if not name:
        raise _entry_error(number, entry, "no tiene nombre de cliente")
    if not key:
        raise _entry_error(number, entry, "no tiene clave")
    return ApiClient(name=name, key=key)


def parse_api_keys(raw):
    """Interpreta el valor de ``API_KEYS``.

    Se quitan los espacios alrededor de cada entrada, del cliente y de la clave; la
    clave puede llevar ``:`` (se separa en el primero). Vacía o solo espacios da una
    secuencia vacía.

    :param raw: Valor de ``API_KEYS``.
    :type raw: str
    :return: Los clientes en el orden en que aparecen.
    :rtype: tuple[ApiClient, ...]
    :raises ApiKeysError: Si una entrada no tiene ``:``, tiene el cliente o la clave
        vacíos, o repite un cliente o una clave. El mensaje dice el número de la
        entrada y su largo, nunca su valor.
    """
    if not raw.strip():
        return ()
    clients = []
    names = set()
    keys = set()
    for number, item in enumerate(raw.split(ENTRY_SEPARATOR), start=1):
        entry = item.strip()
        client = _parse_entry(number, entry)
        if client.name in names:
            raise _entry_error(number, entry, "repite un cliente")
        if client.key in keys:
            raise _entry_error(number, entry, "repite una clave")
        names.add(client.name)
        keys.add(client.key)
        clients.append(client)
    return tuple(clients)


class ApiKeyAuthenticator:
    """Identifica al cliente por su clave, en tiempo constante.

    :param clients: Clientes configurados; sin clientes nadie entra.
    :type clients: collections.abc.Iterable[ApiClient]
    """

    def __init__(self, clients):
        self._clients = tuple(
            (client.name, client.key.encode("utf-8")) for client in clients
        )

    def __repr__(self):
        """Representación sin las claves.

        :return: El nombre de la clase y cuántos clientes tiene.
        :rtype: str
        """
        return f"ApiKeyAuthenticator(clients={len(self._clients)})"

    def identify(self, header):
        """Devuelve el nombre del cliente dueño de la clave, o ``None``.

        Compara bytes UTF-8 con ``hmac.compare_digest`` contra todas las claves, sin
        cortar en la primera que coincide.

        :param header: Valor de ``X-API-Key``, o ``None``.
        :type header: str or None
        :return: El nombre del cliente, o ``None`` si la clave falta o no es válida.
        :rtype: str or None
        """
        if not header:
            return None
        candidate = header.encode("utf-8")
        found = None
        for name, key in self._clients:
            if hmac.compare_digest(candidate, key) and found is None:
                found = name
        return found


def resolve_client_ip(peer, forwarded_for, trust_proxy):
    """Elige la dirección IP con la que se aplica el límite público.

    Sin proxy de confianza es la de la conexión. Con ``trust_proxy`` es la **última**
    entrada de ``X-Forwarded-For`` (la que agrega el proxy), sin espacios; nunca la
    primera, que la puede escribir cualquiera. Si el encabezado falta, está vacío o
    su última entrada está vacía, se usa la conexión.

    :param peer: Dirección de la conexión, o ``None`` si no se conoce.
    :type peer: str or None
    :param forwarded_for: Valor de ``X-Forwarded-For``, o ``None``.
    :type forwarded_for: str or None
    :param trust_proxy: Si hay un proxy de confianza delante (``TRUST_PROXY``).
    :type trust_proxy: bool
    :return: La dirección, o ``unknown`` si no hay ninguna.
    :rtype: str
    """
    if trust_proxy and forwarded_for:
        last = forwarded_for.split(ENTRY_SEPARATOR)[-1].strip()
        if last:
            return last
    return peer or UNKNOWN_ADDRESS


@dataclass(frozen=True)
class PublicAccess:
    """Lo que el middleware necesita para atender preguntas sin clave.

    :param limiter: Límite de peticiones por dirección IP.
    :type limiter: app.rate_limit.RateLimiter
    :param trust_proxy: Leer la IP de ``X-Forwarded-For`` (``TRUST_PROXY``).
    :type trust_proxy: bool
    """

    limiter: object
    trust_proxy: bool = False


def _rate_limited(request_id, retry_after):
    """Respuesta ``429`` con ``Retry-After``.

    :param request_id: Folio de la petición.
    :type request_id: str or None
    :param retry_after: Segundos que faltan para que se libere la ventana.
    :type retry_after: int
    :return: La respuesta JSON.
    :rtype: fastapi.responses.JSONResponse
    """
    return _rejection(
        TOO_MANY_REQUESTS,
        RATE_LIMITED,
        request_id,
        headers={RETRY_AFTER_HEADER: str(retry_after)},
    )


def _public_retry_after(request, public_access):
    """Aplica el límite por IP a una pregunta sin clave.

    La IP solo vive en esta función y como llave del limitador.

    :param request: La petición.
    :type request: starlette.requests.Request
    :param public_access: Límite por IP y si se confía en el proxy.
    :type public_access: PublicAccess
    :return: ``None`` si se acepta; si no, los segundos de ``Retry-After``.
    :rtype: int or None
    """
    peer = request.client.host if request.client is not None else None
    address = resolve_client_ip(
        peer, request.headers.get(FORWARDED_FOR_HEADER), public_access.trust_proxy
    )
    return public_access.limiter.check(address)


def _rejection(status, detail, request_id, headers=None):
    """Respuesta de rechazo con el folio de la petición.

    :param status: Código HTTP.
    :type status: int
    :param detail: Texto fijo del error.
    :type detail: str
    :param request_id: Folio de la petición.
    :type request_id: str or None
    :param headers: Encabezados adicionales.
    :type headers: dict or None
    :return: La respuesta JSON.
    :rtype: fastapi.responses.JSONResponse
    """
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "request_id": request_id},
        headers=headers,
    )


def install_security_middleware(
    application, authenticator, limiter, public_access=None
):
    """Instala el middleware que exige clave y aplica el límite por cliente.

    Protege ``POST /ask`` y ``GET /metrics`` (cualquier método en esas rutas); ``/``,
    ``/health`` y ``/docs`` quedan libres. Debe instalarse antes que el de
    observabilidad para quedar por dentro: así el ``401`` y el ``429`` tienen folio
    y evento ``request``. Decide antes de que FastAPI valide el cuerpo, por eso una
    petición sin clave y con cuerpo inválido da ``401``. El nombre del cliente queda
    en ``request.state.api_client`` (``None`` sin clave válida) y
    ``request.state.is_public`` dice si es una pregunta sin clave del modo demo.

    Si llega ``X-API-Key`` (aunque vacía) siempre se valida: una clave inválida da
    ``401`` y nunca baja a ``public``. Solo sin el encabezado, solo en ``/ask`` y solo
    con ``public_access``, la petición es del cliente ``public`` con el límite por IP.

    :param application: La aplicación FastAPI.
    :type application: fastapi.FastAPI
    :param authenticator: Identifica al cliente por su clave.
    :type authenticator: ApiKeyAuthenticator
    :param limiter: Límite de peticiones por cliente.
    :type limiter: app.rate_limit.RateLimiter
    :param public_access: Límite por IP del modo demo; ``None`` sin modo demo.
    :type public_access: PublicAccess or None
    """

    @application.middleware("http")
    async def protect(request, call_next):
        """Rechaza la petición sin clave válida o por encima del límite."""
        request.state.api_client = None
        request.state.is_public = False
        if request.url.path not in PROTECTED_PATHS:
            return await call_next(request)
        request_id = getattr(request.state, "request_id", None)
        header = request.headers.get(API_KEY_HEADER)
        if (
            header is None
            and public_access is not None
            and request.url.path == ASK_PATH
        ):
            retry_after = _public_retry_after(request, public_access)
            if retry_after is not None:
                return _rate_limited(request_id, retry_after)
            request.state.api_client = PUBLIC_CLIENT
            request.state.is_public = True
            return await call_next(request)
        client = authenticator.identify(header)
        if client is None:
            return _rejection(UNAUTHORIZED, INVALID_KEY, request_id)
        retry_after = limiter.check(client)
        if retry_after is not None:
            return _rate_limited(request_id, retry_after)
        request.state.api_client = client
        return await call_next(request)
