"""Reglas de compliance que se revisan al arrancar (ADR 0012).

Con ``ENVIRONMENT=production`` el producto se niega a arrancar si una regla falla.
El error nombra la regla y la variable, nunca un valor secreto. La lista de reglas,
dónde están y cómo se comprueban está en ``doc/compliance-checklist.md``.
"""

from app.errors import ConfigError

PRODUCTION = "production"
FORBIDDEN_PROVIDER = "fake"
MIN_PRODUCTION_KEY_CHARS = 16


def _check_model(settings):
    """Regla: en producción no se usa el modelo simulado.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :raises ConfigError: Si ``MODEL_PROVIDER`` es ``fake``.
    """
    if settings.model_provider == FORBIDDEN_PROVIDER:
        raise ConfigError(
            f"ENVIRONMENT={PRODUCTION} no permite "
            f"MODEL_PROVIDER={FORBIDDEN_PROVIDER}"
        )


def _check_api_keys(settings):
    """Regla: en producción hay claves y todas son largas.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :raises ConfigError: Si ``API_KEYS`` está vacía o una clave es corta (el mensaje
        dice el número de la entrada, nunca la clave).
    """
    if not settings.api_keys:
        raise ConfigError(f"ENVIRONMENT={PRODUCTION} exige API_KEYS no vacía")
    for number, client in enumerate(settings.api_keys, start=1):
        if len(client.key) < MIN_PRODUCTION_KEY_CHARS:
            raise ConfigError(
                f"ENVIRONMENT={PRODUCTION} exige claves de "
                f"{MIN_PRODUCTION_KEY_CHARS} caracteres o más en API_KEYS; "
                f"la entrada {number} no cumple"
            )


def _check_tracing(settings):
    """Regla: si se piden trazas, no se manda el texto de la conversación.

    Se usa ``LANGSMITH_TRACING`` (lo pedido), no la presencia de la clave.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :raises ConfigError: Si hay trazas y ``HIDE_INPUTS`` o ``HIDE_OUTPUTS`` no son
        ``true``.
    """
    if not settings.langsmith_tracing:
        return
    for name, hidden in (
        ("HIDE_INPUTS", settings.hide_inputs),
        ("HIDE_OUTPUTS", settings.hide_outputs),
    ):
        if not hidden:
            raise ConfigError(
                f"ENVIRONMENT={PRODUCTION} con LANGSMITH_TRACING=true exige "
                f"{name}=true"
            )


def check_production(settings):
    """Aplica las reglas de compliance si el entorno es de producción.

    En ``development`` no hace nada.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    :raises ConfigError: Con la primera regla que falla.
    """
    if settings.environment != PRODUCTION:
        return
    _check_model(settings)
    _check_api_keys(settings)
    _check_tracing(settings)
