# 0005. Métricas en memoria de cada proceso y `outcome` decidido por el agente

Estado: aceptado (spec/02-observability.md)

## Contexto

Se pide `GET /metrics` con latencia p50/p95, tasa de error, tokens, resultados por
`outcome` y la tasa de autoservicio, sin romper la API sin estado (ADR 0001) y sin que la
memoria crezca.

## Decisión

- `Metrics` vive en memoria de cada proceso (`pid` en la respuesta), protegido con un
  candado; guarda solo las últimas 1000 latencias (`deque(maxlen=1000)`) y contadores.
- Es telemetría, no estado de la conversación: ninguna respuesta depende de ella.
- p50/p95 por rango más cercano; `slo.met` es `p95 < SLO_P95_MS`; `self_service_rate` es
  `solved / preguntas` (`0` sin preguntas); `error_rate` cuenta solo `5xx`.
- El agente decide el `outcome` (`escalated`, `incomplete`, `solved` si responde tras una
  búsqueda con artículos, si no `needs_detail`), el `article_id` y `stopped` (booleano,
  verdadero solo al llegar al tope).

## Consecuencias

- Con varias copias cada una reporta lo suyo; agregar entre procesos queda para un
  sistema externo (LangSmith o un colector).
- Las cifras se pierden al reiniciar; el log JSON es la fuente durable.
- `outcome` queda definido en un solo lugar y lo reutilizan el log, las métricas y las
  trazas de las especificaciones siguientes.
