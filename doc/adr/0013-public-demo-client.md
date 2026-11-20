# 0013. Modo demo: el cliente `public` sin clave, solo si se enciende

Estado: aceptado (spec/05-demo.md)

## Contexto

Para una demostración, cualquiera con la URL debe poder usar la página sin escribir una
clave. Las integraciones siguen entrando con `X-API-Key` y `/metrics` no puede quedar
abierto. Abrir el servicio por error sería caro.

## Decisión

- `PUBLIC_PAGE=false` por omisión: sin clave, `401` como en la 04 (falla cerrada).
- Con `PUBLIC_PAGE=true`, el mismo middleware de seguridad (ADR 0010) atiende `POST /ask`
  sin el encabezado `X-API-Key` como el cliente `public`. Si el encabezado llega, aunque
  sea vacío, se valida como antes: una clave inválida nunca baja a `public`.
- `/metrics` sigue exigiendo clave en cualquier modo.
- `public` es un nombre reservado: con el modo demo, `API_KEYS` no puede tener un
  cliente con ese nombre.
- `public` llega al log, a la auditoría y a la traza por el mismo camino que un cliente
  con clave (`request.state.api_client`).

## Consecuencias

- La página ya no maneja claves ni guarda nada en el navegador.
- Las peticiones públicas tienen sus propios límites (ADR 0014 y 0015); las de clientes
  con clave no los tocan.
- Volver al servicio cerrado es cambiar una variable, sin tocar código.
