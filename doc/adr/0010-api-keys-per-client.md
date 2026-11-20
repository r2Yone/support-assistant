# 0010. Una clave por cliente, revisada en un middleware

Estado: aceptado (spec/04-production.md)

## Contexto

El producto se publica en Render y cualquiera con la URL podría gastar cuota del modelo
o leer `/metrics`. Hay que saber qué cliente hizo cada petición sin que su clave quede
nunca en el log, en la traza ni en un error.

## Decisión

- `API_KEYS` (`cliente:clave,...`) se interpreta al arrancar; una entrada mal formada
  impide arrancar con su número y su largo, nunca su valor. Se guarda con `repr=False`.
- Un middleware de seguridad protege `POST /ask` y `GET /metrics`; `/`, `/health` y
  `/docs` quedan libres. Compara bytes con `hmac.compare_digest` contra todas las claves.
- Falla cerrada: sin clave válida, `401 {"detail": "invalid or missing API key",
  "request_id"}`; con `API_KEYS` vacía nadie entra.
- Se instala por dentro del middleware de observabilidad, para que el 401 tenga folio y
  evento `request`. El nombre del cliente va en `request.state.api_client`, en `client`
  de `request`, `agent_run` y `audit`, y en los metadatos de la traza.

## Consecuencias

- Las pruebas de la 01 a la 03 necesitan una clave de prueba en sus fixtures.
- El 401 llega antes de validar el cuerpo y antes del agente: no cuesta tokens.
- Rotar una clave exige cambiar `API_KEYS` en Render y reiniciar el servicio.
