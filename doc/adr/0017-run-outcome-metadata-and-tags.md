# 0017. Cómo terminó la corrida: metadatos y etiquetas de `agent_run`

Estado: aceptado (spec/06-traces.md)

## Contexto

Para filtrar en LangSmith (por ejemplo, todas las transferencias o lo que costó un
modelo) la traza `agent_run` necesita el resultado, que solo se conoce al terminar el
bucle. Nada de lo que se agregue puede llevar la clave, la IP ni el contenido de `.env`.

## Decisión

- La traza `agent_run` envuelve un método que corre el bucle y al final llama
  `tracing.annotate_current_run(metadata, tags)` (`get_current_run_tree`, `add_metadata`
  y `add_tags`), que sin trazas no hace nada y nunca lanza.
- Metadatos, de una lista fija: `model`, `route`, `outcome`, `escalated`, `team`,
  `article_id`, `cached_calls`, `cost_usd`, `steps` y `client`, además del `request_id`
  de `trace_context`. Etiquetas: `outcome:<outcome>`, `route:<route>`, `model:<modelo>`.
- `Agent.run` recibe `client` como argumento opcional por nombre; `main.py` le pasa solo
  el nombre del cliente.

## Consecuencias

- Si el modelo falla (`ModelUnavailable`), la corrida queda como error sin estos datos.
- Agregar un campo exige cambiar la lista fija y su prueba: nada entra por accidente.
