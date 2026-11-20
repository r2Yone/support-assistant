# 0007. Modelo real como adaptador de la interfaz, sin reintentos

Estado: aceptado (spec/03-costs.md)

## Contexto

Hay que usar Workers AI a través de AI Gateway sin cambiar el agente (ADR 0002), sin
llamar a la red en las pruebas y sin filtrar el token ni la cuenta. Un modelo real
reformula el problema y no siempre respeta el protocolo, y las pruebas de la 01 exigen
que el agente mande exactamente `historial + pregunta`.

## Decisión

- `app/gateway.py` define `GatewayModel`, otra implementación de `complete(messages)`.
  Antepone él mismo el prompt de sistema (papel, protocolo JSON, herramientas, reglas,
  siempre en español); el agente no sabe que existe.
- El `httpx.Client` se inyecta (`create_app(http_client=...)`); las pruebas usan
  `httpx.MockTransport`. Tiempo de espera fijo y **una sola petición**: sin reintentos.
- Cualquier falla (red, código no 2xx, respuesta sin la forma esperada) se convierte en
  `ModelUnavailable` con texto fijo, lanzada `from None`, que solo guarda el nombre del
  tipo de error. La API responde `502 {"detail": "model unavailable", "request_id"}`.
- Las reglas que importan las garantiza el código, no el prompt: la búsqueda usa la
  unión de palabras de la pregunta y del `problem`, y la transferencia termina con un
  mensaje fijo (ADR 0003).

## Consecuencias

- Costo y latencia por pregunta tienen un máximo conocido; un fallo temporal se ve como
  `502` y en `error_rate`, no se oculta con reintentos.
- Ningún mensaje de error, log ni traza contiene la URL con la cuenta, el token o el
  cuerpo del proveedor.
- Cambiar de proveedor es escribir otro adaptador.
