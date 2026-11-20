"""El agente: un bucle con tope sobre el modelo y dos herramientas.

En cada vuelta el modelo pide una herramienta o responde. Las salidas inválidas del
modelo nunca rompen el bucle: se le devuelven como resultado de la herramienta.
"""

import json
import re
from dataclasses import dataclass, field

from app import tracing
from app.llm import (
    ESCALATE_TOOL,
    FAKE_MODEL_NAME,
    SEARCH_TOOL,
    TOOL_RESULT_PREFIX,
)
from app.routing import DEFAULT_ROUTE, Route

STEP_CAP_ANSWER = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
SOLVED = "solved"
ESCALATED = "escalated"
NEEDS_DETAIL = "needs_detail"
INCOMPLETE = "incomplete"
TOOL_CALL_ACTION = "tool_call"
MAX_CATEGORY_CHARS = 64
_CATEGORY = re.compile(rf"(?:[^\W\d_]|[ -]){{1,{MAX_CATEGORY_CHARS}}}")


class ToolError(ValueError):
    """El modelo pidió algo que el agente no puede ejecutar."""


# Un resultado tiene un campo por dato que se reporta a la API y al log.
@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una pregunta.

    :param answer: Respuesta para la persona.
    :type answer: str
    :param steps: Vueltas del bucle que se usaron.
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden.
    :type tools_used: list[str]
    :param escalated: Si se ejecutó ``escalate_to_human``.
    :type escalated: bool
    :param team: Equipo al que se transfirió, o ``None``.
    :type team: str or None
    :param input_tokens: Tokens de entrada sumados de todas las llamadas.
    :type input_tokens: int
    :param output_tokens: Tokens de salida sumados de todas las llamadas.
    :type output_tokens: int
    :param outcome: ``solved``, ``escalated``, ``needs_detail`` o ``incomplete``.
    :type outcome: str
    :param article_id: Artículo cuya solución se entregó; ``None`` si no hubo.
    :type article_id: str or None
    :param stopped: Si el bucle llegó al tope de vueltas sin responder.
    :type stopped: bool
    :param model: Nombre del modelo que respondió.
    :type model: str
    :param route: Motivo del enrutador (``default``, ``keyword:<palabra>``...).
    :type route: str
    :param cached_calls: Llamadas que vinieron de la caché del gateway.
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD (las cacheadas no cuestan).
    :type cost_usd: float
    """

    answer: str = STEP_CAP_ANSWER
    steps: int = 0
    tools_used: list = field(default_factory=list)
    escalated: bool = False
    team: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    outcome: str = NEEDS_DETAIL
    article_id: str | None = None
    stopped: bool = False
    model: str = ""
    route: str = DEFAULT_ROUTE
    cached_calls: int = 0
    cost_usd: float = 0.0


def search_audit(problem, output):
    """Datos de auditoría de una búsqueda, sin el texto del problema.

    :param problem: El problema que se buscó (solo se usa su largo).
    :type problem: str
    :param output: Lo que devolvió ``search_knowledge_base``.
    :type output: dict
    :return: ``action``, ``tool``, ``problem_chars``, ``category`` y ``article_ids``.
    :rtype: dict
    """
    return {
        "action": TOOL_CALL_ACTION,
        "tool": SEARCH_TOOL,
        "problem_chars": len(problem),
        "category": output["category"],
        "article_ids": [article["id"] for article in output["articles"]],
    }


def escalation_audit(output):
    """Datos de auditoría de una transferencia.

    :param output: Lo que devolvió ``escalate_to_human``.
    :type output: dict
    :return: ``action``, ``tool``, ``category`` y ``team``.
    :rtype: dict
    """
    return {
        "action": TOOL_CALL_ACTION,
        "tool": ESCALATE_TOOL,
        "category": output["category"],
        "team": output["team"],
    }


def traced_complete(chat, name):
    """Envuelve ``complete`` de un modelo como traza ``llm`` (ADR 0016).

    La traza lleva el proveedor y el nombre del modelo, y sus salidas incluyen
    ``usage_metadata`` con los tokens. Sin trazas devuelve la misma función.

    :param chat: Modelo con ``complete(messages)`` y, opcional, ``provider``.
    :type chat: app.llm.ChatModel
    :param name: Nombre del modelo con el que se usa.
    :type name: str
    :return: La función ``complete``, registrada como traza si hay trazas.
    :rtype: collections.abc.Callable
    """
    metadata = {
        "ls_provider": getattr(chat, "provider", FAKE_MODEL_NAME),
        "ls_model_name": name,
    }
    return tracing.traceable(
        name="model_complete",
        run_type="llm",
        metadata=metadata,
        process_outputs=tracing.completion_outputs,
    )(chat.complete)


def outcome_metadata(result, client):
    """Metadatos de la traza ``agent_run``: cómo terminó la pregunta (ADR 0017).

    Salen de una lista fija de campos del resultado: nunca una clave, una IP ni el
    texto de la conversación.

    :param result: Resultado de la pregunta.
    :type result: AgentResult
    :param client: Nombre del cliente de la API, o ``None``.
    :type client: str or None
    :return: Los diez metadatos.
    :rtype: dict
    """
    return {
        "model": result.model,
        "route": result.route,
        "outcome": result.outcome,
        "escalated": result.escalated,
        "team": result.team,
        "article_id": result.article_id,
        "cached_calls": result.cached_calls,
        "cost_usd": result.cost_usd,
        "steps": result.steps,
        "client": client,
    }


def outcome_tags(result):
    """Etiquetas de la traza ``agent_run`` para filtrar en LangSmith.

    :param result: Resultado de la pregunta.
    :type result: AgentResult
    :return: ``outcome:<outcome>``, ``route:<route>`` y ``model:<modelo>``.
    :rtype: list[str]
    """
    return [
        f"outcome:{result.outcome}",
        f"route:{result.route}",
        f"model:{result.model}",
    ]


def _ignore_tool_call(_audit):
    """Callback por omisión: no hace nada con la auditoría.

    :param _audit: Datos de auditoría de la herramienta.
    :type _audit: dict
    """


@dataclass(frozen=True)
class _Limits:
    """Topes del agente.

    :param max_steps: Tope de vueltas del bucle.
    :type max_steps: int
    :param max_question_chars: Largo máximo del argumento ``problem``.
    :type max_question_chars: int
    :param history_window: Mensajes de historial que se mandan; ``None``: todos.
    :type history_window: int or None
    """

    max_steps: int
    max_question_chars: int
    history_window: int | None


class SingleModelRouter:
    """Enrutador de un solo modelo: siempre el mismo, con el motivo ``default``.

    :param name: Nombre del modelo.
    :type name: str
    """

    def __init__(self, name):
        self._route = Route(model=name, reason=DEFAULT_ROUTE)

    def choose(self, _question):
        """Devuelve siempre el mismo modelo.

        :param _question: Pregunta de la persona (no se usa).
        :type _question: str
        :return: El modelo y el motivo ``default``.
        :rtype: app.routing.Route
        """
        return self._route


def recent_history(history, window):
    """Copia los últimos ``window`` mensajes del historial.

    :param history: Mensajes anteriores que manda el cliente.
    :type history: list[dict]
    :param window: Cuántos mensajes conservar (0: ninguno); ``None``: todos.
    :type window: int or None
    :return: Copias de los mensajes conservados, en orden.
    :rtype: list[dict]
    """
    if window is None:
        kept = history
    elif window <= 0:
        # ``history[-0:]`` devolvería todo el historial, no nada.
        kept = []
    else:
        kept = history[-window:]
    return [dict(message) for message in kept]


def parse_reply(text):
    """Interpreta la salida del modelo.

    :param text: Texto que devolvió el modelo.
    :type text: str
    :return: El objeto JSON con ``answer`` o con ``tool`` y ``args``.
    :rtype: dict
    :raises ToolError: Si no es JSON válido o no sigue el protocolo.
    """
    try:
        reply = json.loads(text)
    except ValueError as error:
        raise ToolError("error: la respuesta del modelo no es JSON válido") from error
    if not isinstance(reply, dict):
        raise ToolError("error: la respuesta del modelo debe ser un objeto JSON")
    if "answer" in reply:
        if not isinstance(reply["answer"], str) or not reply["answer"].strip():
            raise ToolError("error: answer debe ser texto no vacío")
        return reply
    if "tool" not in reply:
        raise ToolError("error: falta answer o tool en la respuesta del modelo")
    if not isinstance(reply.get("args", {}), dict):
        raise ToolError("error: args debe ser un objeto JSON")
    return reply


class Agent:
    """Agente de primer nivel de la mesa de ayuda.

    No guarda nada entre preguntas: cada llamada a ``run`` usa solo sus argumentos.

    :param model: Objeto con ``complete(messages)``.
    :type model: app.llm.ChatModel
    :param knowledge_base: Base de conocimiento con ``search`` y ``escalate``.
    :type knowledge_base: app.knowledge_base.KnowledgeBase
    :param max_steps: Tope de vueltas del bucle.
    :type max_steps: int
    :param max_question_chars: Largo máximo del argumento ``problem``.
    :type max_question_chars: int
    :param models: Modelos por nombre entre los que elige el enrutador; por
        omisión, solo ``model``.
    :type models: dict[str, app.llm.ChatModel] or None
    :param router: Enrutador que elige el modelo de cada pregunta; sin él se usa
        ``model`` con el motivo ``default``.
    :type router: app.routing.Router or None
    :param prices: Tabla de precios; sin ella el costo es 0.
    :type prices: app.costs.PriceTable or None
    :param history_window: Mensajes de historial que se mandan (0: ninguno);
        ``None`` manda todo el historial.
    :type history_window: int or None
    """

    # Las palancas de costo son opcionales y se pasan por nombre (ADR 0008).
    def __init__(  # pylint: disable=too-many-arguments
        self,
        model,
        knowledge_base,
        max_steps,
        max_question_chars,
        *,
        models=None,
        router=None,
        prices=None,
        history_window=None,
    ):
        self._limits = _Limits(max_steps, max_question_chars, history_window)
        self._router = router or SingleModelRouter(getattr(model, "name", ""))
        self._prices = prices
        # Sin trazas, ``traceable`` devuelve la misma función (ADR 0006).
        self._default_complete = traced_complete(model, getattr(model, "name", ""))
        self._completes = {
            name: traced_complete(chat, name) for name, chat in (models or {}).items()
        }
        self._tools = {
            SEARCH_TOOL: tracing.traceable(name=SEARCH_TOOL, run_type="tool")(
                knowledge_base.search
            ),
            ESCALATE_TOOL: tracing.traceable(name=ESCALATE_TOOL, run_type="tool")(
                knowledge_base.escalate
            ),
        }
        self._traced_run = tracing.traceable(name="agent_run")(self._annotated_loop)

    def run(self, question, history, on_tool_call=None, *, client=None):
        """Responde una pregunta en un bucle con tope.

        :param question: Pregunta de la persona.
        :type question: str
        :param history: Mensajes anteriores que manda el cliente.
        :type history: list[dict]
        :param on_tool_call: Función que recibe los datos de auditoría de cada
            herramienta ejecutada con éxito (nunca el texto del problema).
        :type on_tool_call: collections.abc.Callable or None
        :param client: Nombre del cliente de la API para la traza (nunca su clave),
            o ``None``.
        :type client: str or None
        :return: La respuesta, las vueltas, las herramientas, los tokens y cómo
            terminó.
        :rtype: AgentResult
        """
        if on_tool_call is None:
            on_tool_call = _ignore_tool_call
        return self._traced_run(question, history, on_tool_call, client)

    def _annotated_loop(self, question, history, on_tool_call, client):
        """Corre el bucle y anota la traza ``agent_run`` con cómo terminó.

        Si el bucle lanza una excepción, no se anota y la excepción sigue.

        :param question: Pregunta de la persona.
        :type question: str
        :param history: Mensajes anteriores que manda el cliente.
        :type history: list[dict]
        :param on_tool_call: Función que recibe la auditoría de cada herramienta.
        :type on_tool_call: collections.abc.Callable
        :param client: Nombre del cliente de la API, o ``None``.
        :type client: str or None
        :return: El resultado de la pregunta.
        :rtype: AgentResult
        """
        result = self._loop(question, history, on_tool_call)
        tracing.annotate_current_run(
            outcome_metadata(result, client), outcome_tags(result)
        )
        return result

    def _loop(self, question, history, on_tool_call):
        """El bucle con tope: el modelo pide herramientas hasta responder.

        :param question: Pregunta de la persona.
        :type question: str
        :param history: Mensajes anteriores que manda el cliente.
        :type history: list[dict]
        :param on_tool_call: Función que recibe la auditoría de cada herramienta.
        :type on_tool_call: collections.abc.Callable
        :return: El resultado de la pregunta.
        :rtype: AgentResult
        """
        route = self._router.choose(question)
        complete = self._completes.get(route.model, self._default_complete)
        messages = recent_history(history, self._limits.history_window)
        messages.append({"role": "user", "content": question})
        result = AgentResult(model=route.model, route=route.reason)
        found = []
        for step in range(1, self._limits.max_steps + 1):
            result.steps = step
            completion = complete([dict(m) for m in messages])
            self._account(result, completion)
            messages.append({"role": "assistant", "content": completion.text})
            try:
                reply = parse_reply(completion.text)
                if "answer" in reply:
                    return self._answered(result, reply["answer"], found)
                output, audit = self._execute(
                    reply["tool"], reply.get("args", {}), question
                )
            except ToolError as error:
                output = str(error)
            else:
                result.tools_used.append(reply["tool"])
                on_tool_call(audit)
                if reply["tool"] == ESCALATE_TOOL:
                    return self._escalated(result, output)
                found = audit["article_ids"]
                output = json.dumps(output, ensure_ascii=False)
            messages.append({"role": "user", "content": TOOL_RESULT_PREFIX + output})
        result.answer = STEP_CAP_ANSWER
        result.outcome = INCOMPLETE
        result.stopped = True
        return result

    @staticmethod
    def _answered(result, answer, found):
        """Termina el bucle con una respuesta del modelo.

        Si la última búsqueda encontró artículos, la pregunta quedó resuelta con el
        primero; si no, se le pidió a la persona más detalle.

        :param result: Resultado acumulado.
        :type result: AgentResult
        :param answer: Respuesta del modelo.
        :type answer: str
        :param found: Ids de los artículos de la última búsqueda.
        :type found: list[str]
        :return: El resultado con la respuesta y su ``outcome``.
        :rtype: AgentResult
        """
        result.answer = answer
        if found:
            result.outcome = SOLVED
            result.article_id = found[0]
        else:
            result.outcome = NEEDS_DETAIL
        return result

    @staticmethod
    def _escalated(result, output):
        """Termina el bucle tras una transferencia exitosa (ADR 0003).

        :param result: Resultado acumulado.
        :type result: AgentResult
        :param output: Lo que devolvió ``escalate_to_human``.
        :type output: dict
        :return: El resultado con la transferencia.
        :rtype: AgentResult
        """
        result.escalated = True
        result.team = output["team"]
        result.answer = f"Te comunico con {output['team']}."
        result.outcome = ESCALATED
        return result

    def _account(self, result, completion):
        """Suma los tokens y el costo de una llamada al modelo.

        Una llamada que vino de la caché del gateway suma sus tokens pero no cuesta.

        :param result: Resultado acumulado (con el modelo elegido en ``model``).
        :type result: AgentResult
        :param completion: Respuesta del modelo.
        :type completion: app.llm.Completion
        """
        result.input_tokens += completion.input_tokens
        result.output_tokens += completion.output_tokens
        if completion.cached:
            result.cached_calls += 1
        elif self._prices is not None:
            result.cost_usd += self._prices.cost_usd(
                result.model, completion.input_tokens, completion.output_tokens
            )

    def _execute(self, tool, args, question):
        """Valida los argumentos y ejecuta una herramienta.

        La búsqueda usa la unión de las palabras de la pregunta y del ``problem``
        que manda el modelo: si el modelo reformula, no se pierde el artículo.

        :param tool: Nombre de la herramienta.
        :type tool: object
        :param args: Argumentos de la herramienta.
        :type args: dict
        :param question: Pregunta de esta petición (no el historial).
        :type question: str
        :return: La salida de la herramienta y sus datos de auditoría.
        :rtype: tuple[dict, dict]
        :raises ToolError: Si la herramienta no existe o los argumentos son inválidos.
        """
        if tool == SEARCH_TOOL:
            problem = self._valid_problem(args)
            output = self._tools[SEARCH_TOOL](f"{question}\n{problem}")
            return output, search_audit(problem, output)
        if tool == ESCALATE_TOOL:
            output = self._tools[ESCALATE_TOOL](self._valid_category(args))
            return output, escalation_audit(output)
        raise ToolError(f"error: la herramienta {tool!r} no existe")

    def _valid_problem(self, args):
        """Valida ``problem``: texto no vacío de hasta ``max_question_chars``.

        :param args: Argumentos de la herramienta.
        :type args: dict
        :return: El problema.
        :rtype: str
        :raises ToolError: Si falta o es inválido.
        """
        problem = args.get("problem")
        if not isinstance(problem, str) or not problem.strip():
            raise ToolError("error: problem debe ser texto no vacío")
        max_chars = self._limits.max_question_chars
        if len(problem) > max_chars:
            raise ToolError(f"error: problem excede {max_chars} caracteres")
        return problem

    @staticmethod
    def _valid_category(args):
        """Valida ``category``: de 1 a 64 letras, espacios o guiones.

        :param args: Argumentos de la herramienta.
        :type args: dict
        :return: La categoría.
        :rtype: str
        :raises ToolError: Si falta o es inválida.
        """
        category = args.get("category")
        valid = (
            isinstance(category, str)
            and category.strip()
            and _CATEGORY.fullmatch(category)
        )
        if not valid:
            raise ToolError(
                "error: category debe tener de 1 a 64 letras, espacios o guiones"
            )
        return category
