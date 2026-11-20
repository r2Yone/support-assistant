# 0006. Trazas en LangSmith opcionales y apagadas por omisión

Estado: aceptado (spec/02-observability.md)

## Contexto

Las trazas ayudan a ver cada vuelta del agente, pero el producto debe funcionar igual sin
clave, sin red y en pruebas, y no debe mandar texto de las personas sin decidirlo.

## Decisión

- `app/tracing.py` aísla LangSmith. Solo si `LANGSMITH_TRACING=true` y existe
  `LANGSMITH_API_KEY` se envuelven con `@traceable` la corrida del agente, cada
  `complete()` y cada herramienta; si no, el decorador no hace nada y no se conecta.
- La decisión sale de `Settings`, no de las variables que la librería lee por su cuenta.
- El `request_id` va en los metadatos de la traza. `HIDE_INPUTS` y `HIDE_OUTPUTS` (por
  omisión `true`) se pasan al `Client` de LangSmith.
- La clave se lee del entorno y nunca se guarda en `Settings`, el log ni el código.

## Consecuencias

- Se agrega `langsmith` a `requirements.txt`, pero sin trazas no se usa.
- Un LangSmith caído o inalcanzable no bloquea respuestas: el envío es en segundo plano.
- Por omisión las trazas no contienen texto de las preguntas ni de las respuestas.
