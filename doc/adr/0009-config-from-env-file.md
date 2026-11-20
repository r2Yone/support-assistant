# 0009. Configuración desde `.env` sin pisar el entorno

Estado: aceptado (spec/03-costs.md)

## Contexto

La persona configura el producto en `product/.env`, que lleva secretos (`CF_API_TOKEN`,
`LANGSMITH_API_KEY`). Las pruebas y las verificaciones de la fábrica no deben depender
de ese archivo.

## Decisión

- Solo `load_settings()` sin argumentos (el arranque real) lee el archivo de `ENV_FILE`
  (por omisión `.env`, relativo a `product/`) con `python-dotenv` y `override=False`: el
  entorno siempre gana. Si el archivo no existe se sigue sin error; `ENV_FILE=none` no lee
  nada.
- `load_settings(environ)` y `create_app(settings=...)` nunca leen el archivo.
- `CF_ACCOUNT_ID` y `CF_API_TOKEN` se guardan con `repr=False`; los errores de
  configuración nombran la variable, nunca su valor. `.env.example` lista todas las
  variables con los secretos vacíos.

## Consecuencias

- Las claves del archivo también llegan a las librerías que leen el entorno (LangSmith).
- Las verificaciones corren aisladas con `ENV_FILE=none`.
- `.env` no se sube al repositorio ni se copia; su contenido nunca va al log.
