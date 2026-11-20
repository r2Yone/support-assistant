# 0008. Enrutamiento por regla y costo calculado por llamada

Estado: aceptado (spec/03-costs.md)

## Contexto

Cada respuesta debe costar menos sin empeorar, y el ahorro se tiene que poder medir sin
red ni cuota. Usar otro modelo para decidir el enrutamiento costaría y no sería
determinista.

## Decisión

- `app/routing.py`: una regla en código elige `MODEL_LARGE` (motivos `routing_disabled`,
  `long_question`, `keyword:<palabra>`, en ese orden) o `MODEL_SMALL` (`default`). Las
  palabras clave se comparan como secuencias de palabras normalizadas con `tokenize`, no
  como subcadenas. Un solo modelo por pregunta.
- `app/costs.py`: tabla de precios de `PRICES_PATH`; al arrancar se exige que
  `MODEL_SMALL` y `MODEL_LARGE` estén en ella. El costo se calcula por llamada (USD por
  millón de tokens) y una llamada con `cf-aig-cache-status: HIT` cuesta 0.
- Ventana de historial (`HISTORY_WINDOW`, 0 o más) y tope de salida (`MODEL_MAX_TOKENS`)
  se aplican en cada llamada. El costo no se redondea.
- Los modelos simulados llevan el nombre de `MODEL_SMALL`/`MODEL_LARGE` y se cobran con su
  precio: `verification evaluate` compara línea base y palancas sin red.

## Consecuencias

- `POST /ask`, `agent_run` y `/metrics` muestran modelo, motivo, llamadas cacheadas y
  costo; `cost_per_solved_usd` mide lo que cuesta resolver sin un humano.
- La regla es fácil de auditar pero gruesa: puede mandar al modelo grande preguntas
  simples que digan «todos». Se ajusta con datos, no a ojo.
- Si la segunda llamada falla, el costo de la primera no llega a `/metrics` (limitación
  aceptada en esta versión).
