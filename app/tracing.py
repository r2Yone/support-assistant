"""Trazas opcionales en LangSmith (ADR 0006, 0016, 0017 y 0018).

La decisión sale de ``Settings``: solo con ``LANGSMITH_TRACING=true`` y una clave en
``LANGSMITH_API_KEY`` se importa ``langsmith`` y se envuelven las funciones. Sin eso,
``traceable`` devuelve la misma función y nunca se importa ni se conecta nada. La
clave la lee el cliente de LangSmith del entorno; este módulo nunca la toca.

Con ``HIDE_INPUTS=true`` no sale ninguna entrada y con ``HIDE_OUTPUTS=true`` de las
salidas solo sale ``usage_metadata``: el texto de la conversación nunca se manda, pero
LangSmith sigue viendo los tokens. Las trazas van siempre al proyecto de
``LANGSMITH_PROJECT`` (nunca a ``default``) y el cliente las manda en segundo plano.
"""

import contextlib

USAGE_METADATA = "usage_metadata"
_STATE = {"client": None, "project_name": None}


def hide_all_inputs(_inputs):
    """Oculta todas las entradas de una corrida.

    :param _inputs: Entradas de la corrida (no se usan).
    :type _inputs: dict
    :return: Un diccionario vacío.
    :rtype: dict
    """
    return {}


def keep_usage_only(outputs):
    """Deja de las salidas solo ``usage_metadata``, si lo hay.

    :param outputs: Salidas de la corrida.
    :type outputs: dict
    :return: ``{"usage_metadata": ...}`` o un diccionario vacío.
    :rtype: dict
    """
    if isinstance(outputs, dict) and USAGE_METADATA in outputs:
        return {USAGE_METADATA: outputs[USAGE_METADATA]}
    return {}


def _send_unchanged(payload):
    """Deja las entradas o salidas como están (solo en desarrollo).

    :param payload: Entradas o salidas de la corrida.
    :type payload: dict
    :return: El mismo diccionario.
    :rtype: dict
    """
    return payload


def completion_outputs(completion):
    """Salidas de una llamada al modelo, con el consumo de tokens.

    :param completion: Respuesta del modelo.
    :type completion: app.llm.Completion
    :return: ``text``, ``cached`` y ``usage_metadata`` con ``input_tokens``,
        ``output_tokens`` y ``total_tokens``.
    :rtype: dict
    """
    input_tokens = completion.input_tokens
    output_tokens = completion.output_tokens
    return {
        "text": completion.text,
        "cached": completion.cached,
        USAGE_METADATA: {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def configure(settings):
    """Enciende o apaga las trazas según la configuración.

    :param settings: Configuración validada.
    :type settings: app.config.Settings
    """
    if not settings.tracing_enabled:
        _STATE["client"] = None
        _STATE["project_name"] = None
        return
    # Importación diferida: sin trazas, langsmith nunca se carga.
    from langsmith import Client  # pylint: disable=import-outside-toplevel

    _STATE["project_name"] = settings.langsmith_project
    _STATE["client"] = Client(
        hide_inputs=hide_all_inputs if settings.hide_inputs else _send_unchanged,
        hide_outputs=keep_usage_only if settings.hide_outputs else _send_unchanged,
    )


def _unchanged(function):
    """Decorador que no hace nada.

    :param function: Función a decorar.
    :type function: collections.abc.Callable
    :return: La misma función.
    :rtype: collections.abc.Callable
    """
    return function


def traceable(name, run_type="chain", metadata=None, process_outputs=None):
    """Decorador que registra una función como traza, si las trazas están encendidas.

    :param name: Nombre de la traza.
    :type name: str
    :param run_type: Tipo de corrida de LangSmith (``chain``, ``llm`` o ``tool``).
    :type run_type: str
    :param metadata: Metadatos fijos de la traza (``ls_provider``...), o ``None``.
    :type metadata: dict or None
    :param process_outputs: Función que convierte el resultado en las salidas que
        se mandan, o ``None``.
    :type process_outputs: collections.abc.Callable or None
    :return: Un decorador; sin trazas, uno que devuelve la misma función.
    :rtype: collections.abc.Callable
    """
    client = _STATE["client"]
    if client is None:
        return _unchanged
    from langsmith import (  # pylint: disable=import-outside-toplevel
        traceable as langsmith_traceable,
    )

    return langsmith_traceable(
        name=name,
        run_type=run_type,
        metadata=metadata,
        process_outputs=process_outputs,
        client=client,
        project_name=_STATE["project_name"],
    )


def trace_context(request_id, client=None):
    """Contexto que pone el folio y el cliente en los metadatos de las trazas.

    Solo va el nombre del cliente, nunca su clave.

    :param request_id: Folio de la petición.
    :type request_id: str
    :param client: Nombre del cliente de la API, o ``None``.
    :type client: str or None
    :return: Un administrador de contexto; sin trazas, uno que no hace nada.
    :rtype: contextlib.AbstractContextManager
    """
    langsmith_client = _STATE["client"]
    if langsmith_client is None:
        return contextlib.nullcontext()
    from langsmith import tracing_context  # pylint: disable=import-outside-toplevel

    return tracing_context(
        enabled=True,
        client=langsmith_client,
        metadata={"request_id": request_id, "client": client},
        project_name=_STATE["project_name"],
    )


def annotate_current_run(metadata, tags):
    """Agrega metadatos y etiquetas a la traza abierta; nunca lanza.

    Sin trazas no hace nada (ni importa ``langsmith``). Sin corrida abierta, o si
    LangSmith falla al leerla o al anotarla, la falla se descarta: una traza nunca
    rompe una respuesta.

    :param metadata: Metadatos a agregar.
    :type metadata: dict
    :param tags: Etiquetas a agregar.
    :type tags: list[str]
    """
    if _STATE["client"] is None:
        return
    # Cualquier falla de la librería se descarta a propósito (ADR 0018).
    try:
        from langsmith import (  # pylint: disable=import-outside-toplevel
            get_current_run_tree,
        )

        run = get_current_run_tree()
        if run is None:
            return
        run.add_metadata(dict(metadata))
        run.add_tags(list(tags))
    except Exception:  # pylint: disable=broad-exception-caught
        return
