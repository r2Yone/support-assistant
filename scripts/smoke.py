"""Prueba de humo contra el Support Assistant publicado.

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee de la variable ``SMOKE_API_KEY`` y nunca de un argumento, para que no
quede en el historial de la terminal. Comprueba tres cosas e imprime ``[OK]`` o
``[FAIL]`` en cada una, con el código recibido (401: la clave no coincide; 502: el
modelo no responde). Devuelve 0 si las tres pasan, 1 si alguna falla y 2 si falta la
URL o la clave. Ninguna clave se imprime.

Desde ``spec/05-demo.md`` la segunda comprobación manda una clave equivocada, generada
al azar en cada corrida, y espera ``401``: así sirve con y sin modo demo.
"""

import os
import secrets
import sys

import httpx

API_KEY_VARIABLE = "SMOKE_API_KEY"
API_KEY_HEADER = "X-API-Key"
QUESTION = {"question": "No me puedo conectar a la VPN desde mi casa", "history": []}
# Render despierta un servicio dormido del plan free en hasta un minuto.
TIMEOUT_SECONDS = 90


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Corre las tres comprobaciones e imprime el resultado de cada una.

    :param url: URL base del servicio, sin la diagonal final
    :type url: str
    :param key: Clave de un cliente válido
    :type key: str
    :param client: Cliente HTTP con el tiempo de espera ya fijado
    :type client: httpx.Client
    :return: ``True`` si las tres pasan
    :rtype: bool
    """
    wrong_key = _wrong_key(key)
    checks = [
        ("GET /health", 200, lambda: client.get(f"{url}/health")),
        ("POST /ask con clave equivocada", 401, lambda: client.post(
            f"{url}/ask", json=QUESTION, headers={API_KEY_HEADER: wrong_key}
        )),
        ("POST /ask con clave", 200, lambda: client.post(
            f"{url}/ask", json=QUESTION, headers={API_KEY_HEADER: key}
        )),
    ]
    passed = True
    for name, expected, send in checks:
        status = _status_of(send)
        ok = status == expected
        passed = passed and ok
        label = "OK" if ok else "FAIL"
        print(f"[{label}] {name} -> {status} (esperado {expected})")
    return passed


def _wrong_key(key: str) -> str:
    """Genera una clave al azar, nunca vacía y distinta de la válida.

    :param key: Clave de un cliente válido
    :type key: str
    :return: Una clave nueva en cada llamada que no coincide con ``key``
    :rtype: str
    """
    while True:
        candidate = secrets.token_urlsafe(32)
        if candidate != key:
            return candidate


def _status_of(send) -> str | int:
    """Manda la petición y devuelve su código, o el tipo de error de red.

    :param send: Función sin argumentos que hace la petición
    :type send: collections.abc.Callable
    :return: El código HTTP, o el nombre del error (nunca su mensaje)
    :rtype: int or str
    """
    try:
        return send().status_code
    except httpx.HTTPError as error:
        return type(error).__name__


def main(args: list[str]) -> int:
    """Lee la URL y la clave, y corre la prueba de humo.

    :param args: Argumentos de la línea de comandos, sin el nombre del programa
    :type args: list[str]
    :return: 0 si todo pasa, 1 si algo falla y 2 si falta la URL o la clave
    :rtype: int
    """
    key = os.environ.get(API_KEY_VARIABLE, "").strip()
    if len(args) != 1 or not key:
        print(f"Uso: {API_KEY_VARIABLE}=<clave> python scripts/smoke.py <url>")
        return 2
    url = args[0].rstrip("/")
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        passed = run_checks(url, key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
