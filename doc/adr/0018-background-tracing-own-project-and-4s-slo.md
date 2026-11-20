# 0018. Trazas en segundo plano, proyecto propio y meta p95 de 4 s

Estado: aceptado (spec/06-traces.md)

## Contexto

En Render las trazas se encienden (`LANGSMITH_TRACING=true`) y solo falta la clave. Un
LangSmith caído o una clave inválida no pueden frenar ni romper `POST /ask`. Sin proyecto
explícito la librería usa `default`. Con el modelo real cada pregunta hace dos llamadas
y el p95 de 2 s no es alcanzable.

## Decisión

- El envío lo hace el hilo del `Client` de LangSmith; las funciones propias de
  `app/tracing.py` que corren en la petición (anotar, procesar salidas) descartan sus
  excepciones. Los avisos de la librería van a su logger, nunca al evento `error`.
- `LANGSMITH_PROJECT` (por omisión `support-assistant`) se pasa como `project_name` en
  `traceable` y `trace_context`.
- `SLO_P95_MS` vale `4000` por omisión y en `render.yaml`.

## Consecuencias

- Una traza se puede perder sin aviso para la persona; se acepta.
- Al apagar con LangSmith inalcanzable, el hilo de envío puede tardar en terminar.
- `slo.met` en `/metrics` es más fácil de cumplir; la meta se puede volver a bajar con la
  variable, sin cambiar código.
