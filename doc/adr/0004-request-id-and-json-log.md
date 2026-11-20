# 0004. Folio por petición y log JSON con reloj inyectado

Estado: aceptado (spec/02-observability.md)

## Contexto

Soporte necesita responder «¿qué pasó con la petición X?» con datos. La persona da un
folio; el log debe permitir encontrar todo lo que ocurrió con él, en vivo, sin exponer
más texto personal del necesario. Las pruebas deben ser deterministas.

## Decisión

- Un middleware asigna el `request_id`: el `X-Request-ID` del cliente si cumple
  `^[A-Za-z0-9._:-]{1,128}$`; si no, un UUID del `id_factory`. Se devuelve en toda
  respuesta (encabezado) y en el cuerpo de `POST /ask` y de los `500`.
- Log en la salida estándar, una línea JSON por evento (`request`, `agent_run`, `audit`,
  `error`) con `ts`, `service`, `event` y `request_id`, `ensure_ascii=True` y `flush()`
  por línea.
- Solo campos con nombre fijo: la pregunta y la respuesta van únicamente en `agent_run` y
  solo con `LOG_CONVERSATION_TEXT=true`; `error` lleva el tipo, nunca el mensaje.
- Reloj, métricas, destino del log e `id_factory` se inyectan en `create_app()`; el agente
  no conoce el log y reporta cada herramienta con un callback `on_tool_call`.

## Consecuencias

- Cualquier petición se reconstruye filtrando el log por su folio.
- Las pruebas usan un reloj falso, un `StringIO` y un id fijo; nada depende de la hora.
- Con `LOG_CONVERSATION_TEXT=true` (por omisión) el log contiene datos personales: antes
  de producción hay que decidir si se queda encendida y quién lee el log.
