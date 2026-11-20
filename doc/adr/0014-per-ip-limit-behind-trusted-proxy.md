# 0014. Límite por IP, con la IP que agrega el proxy de confianza

Estado: aceptado (spec/05-demo.md)

## Contexto

Las peticiones de `public` no tienen clave que las distinga. En Render hay un proxy
delante: la conexión siempre viene de él, y la persona puede escribir lo que quiera en
`X-Forwarded-For`. La IP es un dato personal.

## Decisión

- Un segundo `RateLimiter` (ADR 0011), separado del de los clientes, limita a
  `PUBLIC_RATE_LIMIT_PER_MINUTE` por IP, con el mismo `429` y `Retry-After`.
- `resolve_client_ip()` usa la IP de la conexión; con `TRUST_PROXY=true`, la **última**
  entrada de `X-Forwarded-For` (la que agrega el proxy), nunca la primera. Sin
  encabezado o con la última entrada vacía, la de la conexión.
- La IP solo vive en una variable local y como llave del limitador: nunca en
  `request.state`, el log, la auditoría, la traza ni un error.
- El limitador purga las llaves sin peticiones en la ventana.

## Consecuencias

- `TRUST_PROXY=true` solo es seguro detrás de un proxy; fuera de Render queda en `false`.
- Si el proxy agregara más de un salto, todos compartirían un límite: más restrictivo,
  nunca más abierto.
- Como en la ADR 0011, el contador es del proceso y se reinicia al reiniciar.
