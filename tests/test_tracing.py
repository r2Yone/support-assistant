"""Pruebas unitarias de las trazas opcionales en LangSmith.

Usan el módulo ``langsmith`` sustituto de ``conftest.py`` (``langsmith_stub``):
nunca la red.
"""

import sys

from app import tracing
from app.config import load_settings
from app.llm import Completion

USAGE = {"input_tokens": 7, "output_tokens": 5, "total_tokens": 12}
OUTCOME = {"outcome": "solved"}
OUTCOME_TAGS = ["outcome:solved"]


def _answer():
    return 42


def _annotate_solved():
    tracing.annotate_current_run(OUTCOME, OUTCOME_TAGS)
    return "listo"


def test_tracing_needs_the_key_and_without_it_never_loads_langsmith(
    monkeypatch, tracing_environ
):
    with_key = load_settings(tracing_environ)
    assert with_key.tracing_enabled is True
    assert tracing_environ["LANGSMITH_API_KEY"] not in repr(with_key)
    without_key = load_settings({"LANGSMITH_TRACING": "true"})
    assert without_key.tracing_enabled is False
    monkeypatch.setitem(sys.modules, "langsmith", None)
    tracing.configure(without_key)
    assert tracing.traceable(name="answer")(_answer) is _answer


def test_trace_context_puts_the_request_id_and_the_client_in_the_metadata(
    langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    tracing.trace_context("folio-1", client="support")
    tracing.trace_context("folio-2")
    first, second = (options["metadata"] for options in langsmith_stub.contexts)
    assert first == {"request_id": "folio-1", "client": "support"}
    assert second["request_id"] == "folio-2"
    assert second.get("client") is None


def test_langsmith_client_receives_functions_that_hide_the_text_but_keep_the_usage(
    langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    options = langsmith_stub.clients[-1].options
    assert callable(options["hide_inputs"])
    assert callable(options["hide_outputs"])
    hidden_inputs = options["hide_inputs"]({"question": "Mi laptop no enciende"})
    assert isinstance(hidden_inputs, dict)
    assert not hidden_inputs
    outputs = {"text": "respuesta secreta", "cached": False, "usage_metadata": USAGE}
    assert options["hide_outputs"](outputs) == {"usage_metadata": USAGE}


def test_hiding_functions_keep_only_the_usage_metadata_or_nothing():
    outputs = {"text": "respuesta secreta", "usage_metadata": USAGE}
    assert tracing.keep_usage_only(outputs) == {"usage_metadata": USAGE}
    without_usage = tracing.keep_usage_only({"output": "respuesta secreta"})
    assert isinstance(without_usage, dict)
    assert not without_usage
    no_inputs = tracing.hide_all_inputs({"messages": [{"content": "hola"}]})
    assert isinstance(no_inputs, dict)
    assert not no_inputs


def test_text_is_sent_unchanged_when_hiding_is_turned_off(
    langsmith_stub, tracing_environ
):
    environ = {**tracing_environ, "HIDE_INPUTS": "false", "HIDE_OUTPUTS": "false"}
    tracing.configure(load_settings(environ))
    options = langsmith_stub.clients[-1].options
    inputs = {"messages": [{"role": "user", "content": "Mi laptop no enciende"}]}
    outputs = {"text": "respuesta", "cached": False, "usage_metadata": USAGE}
    assert options["hide_inputs"](inputs) == inputs
    assert options["hide_outputs"](outputs) == outputs


def test_traces_go_to_the_support_assistant_project_and_never_to_default(
    langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    tracing.traceable(name="agent_run")(_answer)
    tracing.trace_context("folio-1")
    assert langsmith_stub.decorations[-1]["project_name"] == "support-assistant"
    assert langsmith_stub.contexts[-1]["project_name"] == "support-assistant"
    custom = {**tracing_environ, "LANGSMITH_PROJECT": "help-desk-traces"}
    tracing.configure(load_settings(custom))
    tracing.traceable(name="agent_run")(_answer)
    tracing.trace_context("folio-2")
    assert langsmith_stub.decorations[-1]["project_name"] == "help-desk-traces"
    assert langsmith_stub.contexts[-1]["project_name"] == "help-desk-traces"
    every_call = [*langsmith_stub.decorations, *langsmith_stub.contexts]
    assert "default" not in {options["project_name"] for options in every_call}


def test_traceable_passes_the_run_type_metadata_and_output_processing_to_langsmith(
    langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    metadata = {"ls_provider": "fake", "ls_model_name": "fake-small"}
    tracing.traceable(
        name="model_complete",
        run_type="llm",
        metadata=metadata,
        process_outputs=tracing.completion_outputs,
    )(_answer)
    options = langsmith_stub.decorations[-1]
    assert (options["name"], options["run_type"]) == ("model_complete", "llm")
    assert options["metadata"] == metadata
    assert options["process_outputs"] is tracing.completion_outputs
    assert options["client"] is langsmith_stub.clients[-1]


def test_completion_outputs_report_the_usage_with_the_total_tokens():
    completion = Completion(
        text='{"answer": "Listo"}', input_tokens=7, output_tokens=5, cached=True
    )
    assert tracing.completion_outputs(completion) == {
        "text": '{"answer": "Listo"}',
        "cached": True,
        "usage_metadata": USAGE,
    }


def test_annotate_current_run_adds_metadata_and_tags_to_the_open_trace(
    langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    assert tracing.traceable(name="agent_run")(_annotate_solved)() == "listo"
    run = langsmith_stub.runs_named("agent_run")[0]
    assert run.added_metadata == OUTCOME
    assert run.tags == OUTCOME_TAGS


def test_annotate_current_run_never_raises_whatever_happens_to_langsmith(
    monkeypatch, langsmith_stub, tracing_environ
):
    tracing.configure(load_settings(tracing_environ))
    tracing.annotate_current_run(OUTCOME, OUTCOME_TAGS)
    langsmith_stub.failure = langsmith_stub.READING_RUN
    tracing.annotate_current_run(OUTCOME, OUTCOME_TAGS)
    langsmith_stub.failure = langsmith_stub.ADDING_METADATA
    assert tracing.traceable(name="agent_run")(_annotate_solved)() == "listo"
    tracing.configure(load_settings({}))
    monkeypatch.setitem(sys.modules, "langsmith", None)
    tracing.annotate_current_run(OUTCOME, OUTCOME_TAGS)
    assert not any(run.added_metadata for run in langsmith_stub.runs)
