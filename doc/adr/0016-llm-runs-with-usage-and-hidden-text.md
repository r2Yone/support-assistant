# 0016. Llamadas al modelo como trazas `llm` con tokens y texto oculto

Estado: aceptado (spec/06-traces.md)

## Contexto

Las trazas de la 02 muestran los pasos, pero no los tokens de cada llamada. En
producción `HIDE_OUTPUTS=true` y `HIDE_INPUTS=true`; con booleanos, LangSmith borraría
también los tokens, y apagarlos mandaría el texto de la conversación.

## Decisión

- `model_complete` se registra con `run_type="llm"` y los metadatos `ls_provider`
  (`cloudflare` o `fake`, del atributo `provider` de cada modelo) y `ls_model_name`.
- `process_outputs` convierte el `Completion` en `{"text", "cached", "usage_metadata"}`
  con `input_tokens`, `output_tokens` y `total_tokens`.
- El `Client` recibe `hide_inputs` y `hide_outputs` como funciones: con `true`, las
  entradas salen vacías y de las salidas solo queda `usage_metadata`; con `false`,
  identidad (solo en desarrollo).

## Consecuencias

- LangSmith muestra los tokens de cada llamada sin ver el texto en producción.
- `agent_run` y las herramientas quedan sin salidas con `HIDE_OUTPUTS=true`.
- Depende de `process_outputs` y de `hide_*` como funciones en `langsmith`; si la versión
  instalada no los tiene, hay que subir el mínimo de la librería.
