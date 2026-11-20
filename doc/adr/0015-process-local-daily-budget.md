# 0015. Tope de gasto diario de la demo en memoria del proceso

Estado: aceptado (spec/05-demo.md)

## Contexto

Con la página abierta, el límite por IP no basta: muchas IP pueden gastar la cuota del
modelo. Hace falta un tope en dólares por día, probado sin esperar un día real y sin
librerías ni almacenes nuevos.

## Decisión

- `DailyBudget(limit_usd, clock)` en `app/budget.py` suma el `cost_usd` de las respuestas
  de `public` del día UTC del reloj inyectado; al cambiar de día vuelve a cero.
- En `POST /ask`, después de validar la pregunta y **antes** de llamar al modelo: si lo
  gastado hoy es `>= DAILY_BUDGET_USD`, `503 {"detail": "daily budget exhausted",
  "request_id"}`. El evento `budget_exhausted` (`spent_usd`, `budget_usd`) se escribe
  solo la primera vez del día.
- `/metrics` muestra `public_cost_today_usd` y `daily_budget_usd`.
- Con `PUBLIC_PAGE=true`, un tope que no sea mayor que 0 impide arrancar.

## Consecuencias

- Al reiniciar (Render gratis se duerme tras 15 minutos) la suma empieza en cero:
  decisión aceptada en `doc/compliance-checklist.md`.
- Preguntas simultáneas pueden pasar el tope por unas pocas llamadas: se revisa antes y
  se suma después.
- El `503` cuenta en `error_rate` (la 02 cuenta todo `5xx`).
- Un tope compartido entre instancias necesitaría un almacén externo (otra decisión).
