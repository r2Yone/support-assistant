# 0011. Límite de peticiones por cliente en memoria del proceso

Estado: aceptado (spec/04-production.md)

## Contexto

Un cliente con clave válida podría mandar muchas preguntas y agotar la cuota del
modelo. La regla debe probarse sin esperar un minuto real y sin librerías nuevas.

## Decisión

- `RateLimiter(limit_per_minute, clock)` guarda, por cliente, las horas de sus últimas
  peticiones aceptadas (ventana deslizante de 60 s). El reloj es el mismo `Clock`
  inyectado de la 02.
- Si el cliente ya tiene `RATE_LIMIT_PER_MINUTE` peticiones en la ventana: `429
  {"detail": "rate limit exceeded", "request_id"}` con `Retry-After` en segundos
  enteros, redondeado hacia arriba y al menos 1.
- Se revisa después de autenticar: las peticiones sin clave no cuentan.

## Consecuencias

- Como las métricas (ADR 0005), el contador es del proceso: con varias instancias o
  tras reiniciar se reinicia. Render `free` corre una sola instancia.
- La memoria está acotada por clientes conocidos por `RATE_LIMIT_PER_MINUTE`.
- Un límite compartido entre instancias necesitaría un almacén externo (otra decisión).
