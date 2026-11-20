# 0003. Bucle del agente con tope y transferencia que termina el bucle

Estado: aceptado (spec/01-architecture.md)

## Contexto

Un solo agente con dos herramientas decide en un bucle. El modelo puede devolver JSON
inválido, herramientas que no existen o argumentos inválidos. El contrato de la fábrica
exige `steps == 2` al buscar y transferir, mientras que el texto de la especificación 01
sugiere 3 vueltas (buscar, transferir, responder).

## Decisión

- El bucle corre como máximo `AGENT_MAX_STEPS` vueltas; si no hay respuesta, contesta
  `No pude completar la respuesta. Intenta con una pregunta más concreta.`
- Antes de ejecutar una herramienta se validan los argumentos (`problem`: texto no vacío de
  hasta `MAX_QUESTION_CHARS`; `category`: 1 a 64 letras, espacios o guiones). Cualquier
  error se agrega como `Resultado de la herramienta: ...` y el bucle sigue; el agente nunca
  lanza la excepción a la API.
- Cuando `escalate_to_human` se ejecuta sin error, el agente termina en esa vuelta con
  `Te comunico con <team>.`, el mismo texto que daría el modelo simulado.

## Consecuencias

- El costo y la latencia de una pregunta tienen un máximo conocido.
- La transferencia ahorra una llamada al modelo y su texto no depende del modelo; queda
  alineada con el contrato y con `spec/03-costs.md`.
- Un modelo que se equivoca consume vueltas: con el tope por omisión (4) cabe un error y
  aun así buscar y responder.
