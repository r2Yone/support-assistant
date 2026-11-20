# Lista de compliance del Support Assistant

Reglas de `spec/04-production.md` que el producto revisa solo. Las de arranque se
aplican con `ENVIRONMENT=production` al final de `load_settings()`: si una falla, el
import de `app.main` termina con `ConfigError`, el proceso no arranca y Render conserva
la versión anterior (ADR 0012). Ningún error lleva un valor secreto: solo nombra la
regla, la variable y, si aplica, el número de la entrada.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no es `fake` | `app/compliance.py`, `_check_model` | `tests/test_compliance.py` (`fake-model`); contrato `test_production_refuses_the_fake_model` |
| En producción `API_KEYS` no está vacía | `app/compliance.py`, `_check_api_keys` | `tests/test_compliance.py` (`no-keys`) |
| En producción cada clave tiene 16 caracteres o más | `app/compliance.py`, `_check_api_keys` (`MIN_PRODUCTION_KEY_CHARS`) | `tests/test_compliance.py` (`short-key`); contrato `test_production_refuses_a_short_key_without_leaking_it` |
| En producción, con `LANGSMITH_TRACING=true`, `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` | `app/compliance.py`, `_check_tracing` | `tests/test_compliance.py` (`inputs-shown`, `outputs-shown`) |
| En `development` las reglas de producción no se aplican; en producción con todo en regla arranca | `app/compliance.py`, `check_production` | `tests/test_compliance.py`; contrato `test_production_starts_when_every_rule_holds` |
| `ENVIRONMENT` solo vale `development` o `production` | `app/config.py`, `_environment` | `tests/test_config.py` (`ENVIRONMENT=staging`) |
| `API_KEYS` mal formada impide arrancar; el error dice la entrada y su largo, nunca su valor | `app/security.py`, `parse_api_keys`; `app/config.py`, `_api_keys` (`from None`) | `tests/test_security.py`; contrato `test_a_broken_api_keys_never_leaks_the_key` |
| Las claves no aparecen en `repr` de la configuración | `app/config.py` (`api_keys` con `repr=False`); `app/security.py` (`ApiClient.key` con `repr=False`) | `tests/test_config.py` (`test_production_settings_have_closed_defaults_and_never_show_the_keys`) |
| `POST /ask` y `GET /metrics` exigen `X-API-Key` (salvo `/ask` sin clave en modo demo); sin clave válida, `401` con `request_id` | `app/security.py`, `install_security_middleware` | `tests/features/production.feature`; contratos `test_asking_without_a_key_returns_401`, `test_metrics_need_a_key` |
| `/`, `/health` y `/docs` no piden clave | `app/security.py` (`PROTECTED_PATHS`) | `tests/features/production.feature` («Public pages answer without a key») |
| Falla cerrada: con `API_KEYS` vacía nadie entra | `app/security.py`, `ApiKeyAuthenticator.identify` | `tests/test_security.py` (`test_without_configured_keys_nobody_is_let_in`) |
| Las claves se comparan con `hmac.compare_digest`, contra todas, en bytes UTF-8 | `app/security.py`, `ApiKeyAuthenticator.identify` | `tests/test_security.py` (`test_every_configured_key_is_compared_in_constant_time`) |
| El log lleva el nombre del cliente (`client`), nunca la clave | `app/observability.py` (`request`); `app/main.py` (`agent_run`, `audit`, `error`) | `tests/features/production.feature` (eventos con `client`, clave ausente del log) |
| La traza lleva el nombre del cliente en sus metadatos | `app/tracing.py`, `trace_context` | `tests/test_tracing.py` |
| Más de `RATE_LIMIT_PER_MINUTE` peticiones por minuto: `429` con `Retry-After` | `app/rate_limit.py`, `RateLimiter`; `app/security.py` | `tests/test_rate_limit.py`; `tests/features/production.feature`; contrato `test_too_many_requests_returns_429_with_retry_after` |
| El modelo real manda `cf-aig-authorization: Bearer {CF_API_TOKEN}`; el token no va al log, al `repr` ni a un error | `app/gateway.py`, `GatewayModel` | `tests/test_gateway.py`; `tests/features/production.feature` (gateway simulado con `httpx.MockTransport`) |
| La página no pide ni guarda una clave (sin `data-testid="api-key"`, `sessionStorage`, `localStorage` ni `X-API-Key`); mensajes de 401, 429 y 503 con `textContent` | `app/static/index.html` | `tests/test_api.py` (`test_home_page_never_asks_for_a_key_and_explains_the_demo_limits`); `e2e/test_support_page.py` (`test_page_without_key_field_answers_a_question`); contrato `test_the_page_asks_for_no_key` |

### Modo demo (`spec/05-demo.md`)

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `PUBLIC_PAGE=false` por omisión: sin clave, `401` como en la 04 | `app/config.py` (`DEFAULTS`); `app/security.py`, `install_security_middleware` | `tests/test_config.py`; `tests/features/production.feature` |
| Con `PUBLIC_PAGE=true`, `POST /ask` sin `X-API-Key` es del cliente `public` en el log, la auditoría y la traza | `app/security.py` (`PUBLIC_CLIENT`); `app/main.py`, `ask` | `tests/features/demo.feature`; `tests/test_demo.py` (`test_trace_metadata_names_the_public_client_and_never_the_ip`); contrato `test_the_demo_answers_without_a_key` |
| Un `X-API-Key` presente (aunque vacío) se valida: inválido da `401`, nunca baja a `public` | `app/security.py`, `install_security_middleware` | `tests/features/demo.feature` («A key that is sent is still validated»); contrato `test_the_demo_still_rejects_a_wrong_key` |
| `GET /metrics` nunca es público | `app/security.py` (solo `/ask` es público) | `tests/features/demo.feature`; contrato `test_the_demo_still_protects_the_metrics` |
| El nombre `public` está reservado en `API_KEYS` con el modo demo; el error no muestra la clave | `app/config.py`, `_check_demo` | `tests/test_config.py` (`test_public_client_name_is_reserved_when_the_demo_is_on`) |
| Más de `PUBLIC_RATE_LIMIT_PER_MINUTE` preguntas sin clave por IP en 60 s: `429` con `Retry-After` | `app/security.py` (`PublicAccess`, `_public_retry_after`); `app/rate_limit.py` | `tests/features/demo.feature`; contrato `test_the_limit_counts_the_address_added_by_the_proxy` |
| La IP es la de la conexión; con `TRUST_PROXY=true`, la **última** entrada de `X-Forwarded-For` | `app/security.py`, `resolve_client_ip` | `tests/test_security.py`; `tests/features/demo.feature` (proxy de confianza y sin proxy) |
| La IP nunca se escribe en el log, la auditoría, la traza, un error, `request.state` ni `repr`; el access log de uvicorn está apagado | `app/security.py` (solo variable local y llave del limitador); `app/rate_limit.py` (`__repr__`); `app/observability.py`, `silence_access_log` | `tests/features/demo.feature` («The IP address is never written in the log»); `tests/test_demo.py`; contrato `test_the_demo_logs_the_public_client_but_never_the_address` |
| El limitador purga las IP sin peticiones en la ventana (la memoria no crece sin límite) | `app/rate_limit.py`, `RateLimiter._purge` | `tests/test_rate_limit.py` (`test_inactive_keys_are_purged_without_changing_the_answers`) |
| Tope de gasto diario: con lo gastado hoy (UTC, reloj inyectado) `>=` `DAILY_BUDGET_USD`, `503` sin llamar al modelo; al día siguiente vuelve a responder | `app/budget.py`, `DailyBudget`; `app/main.py`, `budget_rejection` | `tests/test_budget.py`; `tests/features/demo.feature`; contrato `test_the_daily_budget_stops_the_demo_but_not_the_keys` |
| `budget_exhausted` (`spent_usd`, `budget_usd`) se escribe una sola vez por día | `app/budget.py`, `claim_exhaustion_notice` | `tests/test_budget.py`; `tests/features/demo.feature` |
| Los clientes con clave no cuentan para el límite por IP ni para el tope | `app/main.py` (`is_public`) | `tests/features/demo.feature` («A client with a valid key does not use the demo limits») |
| `/metrics` agrega `public_cost_today_usd` y `daily_budget_usd` | `app/main.py`, `process_metrics` | `tests/features/demo.feature`; `tests/test_demo.py` |
| Con `PUBLIC_PAGE=true` no arranca si `DAILY_BUDGET_USD` o `PUBLIC_RATE_LIMIT_PER_MINUTE` no son mayores que 0; `DAILY_BUDGET_USD` debe ser un número finito | `app/config.py`, `_check_demo` y `_non_negative_float` | `tests/test_config.py`; contrato `test_the_demo_needs_a_budget` |

## Decisiones aceptadas

- **`LOG_CONVERSATION_TEXT=true` también en producción.** El log guarda la pregunta y
  la respuesta (en el evento `agent_run`) para revisar la calidad del asistente. Las
  preguntas pueden traer datos personales, así que el acceso a los logs de Render se
  limita al equipo de soporte, y la decisión se revisa antes de abrir el servicio a
  más personas. Se apaga con `LOG_CONVERSATION_TEXT=false` sin cambiar código.
- El límite de peticiones vive en memoria del proceso (ADR 0011): con varias
  instancias o tras reiniciar se reinicia. Render `free` corre una sola instancia.
- **El tope de gasto diario de la demo vive en memoria del proceso (ADR 0015).** Si el
  servicio se reinicia o se duerme (en Render `free`, tras 15 minutos sin uso), la
  suma de `public_cost_today_usd` vuelve a cero y el aviso `budget_exhausted` puede
  repetirse ese día. Además, el tope se revisa antes de llamar al modelo y se suma
  después, así que varias preguntas en vuelo pueden pasarlo un poco. Para una demo es
  aceptable: lo acotan el límite por IP, `MODEL_MAX_TOKENS` y el tope mismo.
- **Un `503` por el tope cuenta en `error_rate`** (la 02 cuenta todo `5xx`). Un día
  sin presupuesto sube la tasa de errores; la página distingue el `503` (tope) del
  `502` (modelo).
- **Detrás de Render se confía en la última entrada de `X-Forwarded-For`.** Si el
  proxy agregara más de un salto, todas las personas compartirían un solo límite:
  falla hacia lo restrictivo y el tope sigue protegiendo el gasto.
