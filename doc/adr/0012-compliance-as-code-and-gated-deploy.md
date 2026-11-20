# 0012. Compliance al arrancar y publicación solo con el pipeline en verde

Estado: aceptado (spec/04-production.md)

## Contexto

Un error de configuración en producción (modelo simulado, claves cortas, trazas con el
texto de la persona) o un cambio que rompe las pruebas no debe llegar a Render. Las
reglas deben revisarse solas, no depender de que alguien se acuerde.

## Decisión

- `app/compliance.py` revisa las reglas al final de `load_settings()` con
  `ENVIRONMENT=production`: sin `MODEL_PROVIDER=fake`, `API_KEYS` no vacía y con claves
  de 16 caracteres o más, y si se piden trazas, `HIDE_INPUTS` y `HIDE_OUTPUTS` en
  `true`. Si una falla, el import de `app.main` termina con `ConfigError` que nombra la
  regla, nunca un valor. `doc/compliance-checklist.md` lista cada regla, dónde está y
  cómo se prueba, más las decisiones aceptadas.
- Se publica una imagen Docker (`python:3.12-slim`, usuario no root, sin `.env`). El CI
  corre `style`, `unit`, `e2e` y `docker` encadenados; Render (servicio
  `support-assistant`) usa `autoDeployTrigger: checksPass`. Los secretos van con
  `sync: false`.

## Consecuencias

- Una mala configuración deja caer el arranque y Render conserva la versión anterior.
- Un push que rompe una etapa no se publica; los ingenieros ven la etapa en Actions.
- `LOG_CONVERSATION_TEXT=true` en producción queda como decisión aceptada y revisable.
