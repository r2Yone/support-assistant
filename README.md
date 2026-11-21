# Support Assistant

## Requisitos y primeros pasos

Esta sección es para quien descarga el repositorio y lo corre con sus propias cuentas
y claves.

### Requisitos

- **Git**, para clonar el repositorio.
- **Python 3.12**, o **Docker** en lugar de Python (ver «Con Docker»).

### Cuentas

| Cuenta | ¿Obligatoria? | Qué se necesita |
| --- | --- | --- |
| Cloudflare | Solo para el modelo real | El **Account ID**, un AI Gateway creado (su nombre va en `CF_GATEWAY_ID`) y un token de API con los permisos **Workers AI: Read** y **AI Gateway: Run** |
| LangSmith | Opcional | Una API key, para ver las trazas |
| Render | Opcional | Una cuenta, solo para publicar el servicio |

### Pasos

Los comandos se corren desde la carpeta del producto (`product/`).

Windows (PowerShell):

```powershell
git clone <url-del-repositorio>
cd <carpeta-del-repositorio>\product
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Completa los valores de .env (ver «El .env mínimo»)
uvicorn app.main:app --port 8000
```

macOS/Linux:

```bash
git clone <url-del-repositorio>
cd <carpeta-del-repositorio>/product
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Completa los valores de .env (ver «El .env mínimo»)
uvicorn app.main:app --port 8000
```

Después abre `http://127.0.0.1:8000` en el navegador. Las variables están descritas en
«Variables de entorno» y en `.env.example`.

### El `.env` mínimo

Para el modelo real con la página de demo (los valores entre `< >` son de ejemplo:
cámbialos por los tuyos y nunca los subas al repositorio):

```bash
MODEL_PROVIDER=gateway
CF_ACCOUNT_ID=<tu-account-id>
CF_GATEWAY_ID=<tu-gateway>
CF_API_TOKEN=<tu-token>
API_KEYS=local:<tu-clave-de-32-caracteres>
PUBLIC_PAGE=true
```

La clave de `API_KEYS` se genera como explica «Crear una clave».

### Probarlo sin ninguna cuenta

Basta con esta línea en `.env`; responde el modelo simulado (`MODEL_PROVIDER=fake`, por
omisión), sin red y sin gastar cuota:

```bash
PUBLIC_PAGE=true
```

### Con Docker

```bash
docker build -t support-assistant .
docker run -p 8000:8000 --env-file .env support-assistant
```

Docker lee el `.env` en tu máquina: el `.env` nunca entra en la imagen (lo excluye
`.dockerignore`).

### Para correr las pruebas

Las herramientas de prueba no van en `requirements.txt` porque la imagen de Docker no
las necesita; se instalan aparte:

```bash
pip install pytest-playwright pylint
python -m playwright install chromium
pytest tests
```

Las de punta a punta necesitan el producto corriendo con `PUBLIC_PAGE=true`; en otra
terminal:

```bash
pytest e2e --base-url http://127.0.0.1:8000
```

Los comandos completos que corre el CI están en «Pruebas».

## Qué es

Primer nivel de la mesa de ayuda de la empresa. La persona describe su problema con
sus palabras en una página web; un agente lo clasifica, busca una solución vigente en
la base de conocimiento (`data/knowledge_base.json`) y, si no la encuentra, indica con
qué equipo humano se transfiere.

- API web con FastAPI, sin estado: el historial lo guarda el navegador y lo manda en
  cada petición. Escalar es correr más copias.
- Un solo agente con dos herramientas, `search_knowledge_base(problem)` y
  `escalate_to_human(category)`, en un bucle con tope.
- El modelo se usa a través de la interfaz `complete(messages)`: el modelo simulado
  (`MODEL_PROVIDER=fake`, determinista y sin red) o el real, Workers AI de Cloudflare
  a través de AI Gateway (`MODEL_PROVIDER=gateway`).
- Costos: cada respuesta dice qué modelo usó, por qué y cuánto costó. Cuatro palancas
  lo abaratan: enrutamiento por regla, ventana de historial, tope de salida y caché
  del gateway.
- Observabilidad: cada petición tiene un folio (`request_id`), el log es JSON (una
  línea por evento) y `GET /metrics` mide latencia, errores, tokens y cuántos
  problemas se resuelven sin un humano. Las trazas en LangSmith son opcionales.
- Seguridad: una clave por cliente (`X-API-Key`), límite de peticiones por cliente y
  reglas de compliance que impiden arrancar en producción con una mala configuración
  (`doc/compliance-checklist.md`).
- Modo demo (`PUBLIC_PAGE=true`): la página pregunta sin clave, con un límite por
  dirección IP y un tope de gasto diario (ver «Modo demo»).

La arquitectura y sus decisiones están en `doc/architecture.md` y `doc/adr/`.

La página no pide clave: para usarla enciende el modo demo (`PUBLIC_PAGE=true` en
`product/.env`, ver «Modo demo»). Las integraciones preguntan con una clave de
`API_KEYS` (ver «Claves de acceso»).

### La página

`GET /` es una página de chat de soporte en un solo archivo (`app/static/index.html`,
con su CSS y su JavaScript, sin recursos de otros sitios y con la tipografía del
sistema). Muestra el texto de bienvenida, tres ejemplos que se pueden pulsar para
escribirlos en el campo de pregunta, las burbujas de la conversación (la persona a la
derecha, el asistente a la izquierda, con el id del artículo como etiqueta), el folio
de cada respuesta y la tarjeta de transferencia. Enter envía y Shift+Enter hace un
salto de línea; mientras espera muestra «Buscando una solución…». Tiene modo oscuro
automático, respeta `prefers-reduced-motion` y no guarda nada en el navegador.

## Modo demo

Con `PUBLIC_PAGE=true` cualquiera con la URL puede usar la página sin escribir una
clave. Para encenderlo en tu equipo, agrega a `product/.env`:

```bash
PUBLIC_PAGE=true
```

y arranca como siempre. Sin modo demo (`PUBLIC_PAGE=false`, por omisión) la página
muestra «Esta página necesita el modo demo (PUBLIC_PAGE=true)».

- `POST /ask` **sin** el encabezado `X-API-Key` se atiende como el cliente `public`:
  así aparece en el log (`client`), en la auditoría y en la traza.
- Una petición **con** `X-API-Key` (aunque esté vacía) se valida como siempre: con una
  clave inválida, `401`; con una válida es de su cliente, con su propio límite, y no
  cuenta para los límites de la demo.
- `GET /metrics` sigue exigiendo clave.
- Con `PUBLIC_PAGE=true`, `API_KEYS` no puede tener un cliente llamado `public`.

### Límites de la demo

- **Por dirección IP:** `PUBLIC_RATE_LIMIT_PER_MINUTE` preguntas sin clave por minuto
  (5 por omisión). Pasado el límite, `429 {"detail": "rate limit exceeded",
  "request_id": ...}` con `Retry-After`; la página muestra «Demasiadas preguntas;
  espera N segundos». La IP es la de la conexión; con `TRUST_PROXY=true` (solo detrás
  de un proxy de confianza, como Render) es la **última** entrada de
  `X-Forwarded-For`, la que agrega el proxy. La IP es un dato personal: nunca se
  escribe en el log, en la auditoría ni en la traza (por eso el access log de uvicorn
  está apagado; el evento `request` lo reemplaza).
- **Tope de gasto diario:** el producto suma el `cost_usd` de las preguntas sin clave
  del día (en UTC). Si lo gastado hoy llega a `DAILY_BUDGET_USD` (0.50 por omisión),
  responde `503 {"detail": "daily budget exhausted", "request_id": ...}` sin llamar
  al modelo, y la página muestra «La demo alcanzó su límite de hoy. Vuelve mañana».
  Al día siguiente vuelve a responder. El log escribe `budget_exhausted` (con
  `spent_usd` y `budget_usd`) una sola vez por día, y `/metrics` agrega
  `public_cost_today_usd` y `daily_budget_usd`.
- La suma vive en la memoria del proceso: si el servicio se reinicia (en Render
  `free` se duerme tras 15 minutos sin uso), empieza en cero. Es una decisión aceptada
  para la demo (`doc/compliance-checklist.md`).
- Con `PUBLIC_PAGE=true` el producto no arranca si `DAILY_BUDGET_USD` o
  `PUBLIC_RATE_LIMIT_PER_MINUTE` no son mayores que 0.

## Claves de acceso

`POST /ask` y `GET /metrics` exigen el encabezado `X-API-Key` (salvo `/ask` sin clave
en modo demo); `GET /`, `GET /health` y `/docs` no piden clave. Sin `API_KEYS` y sin
modo demo nadie puede preguntar (falla cerrada).

### Crear una clave

1. Genera una clave aleatoria de 16 caracteres o más (en producción es obligatorio):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Agrégala en `product/.env` (o en Render > Environment) con el nombre del cliente:

   ```bash
   API_KEYS=soporte:<la clave generada>,portal:<otra clave>
   ```

   Cada cliente tiene su propia clave; un cliente o una clave repetidos, o una entrada
   sin `:`, impiden arrancar. El error dice qué entrada falla y su largo, nunca su
   valor. Para rotar una clave, cambia `API_KEYS` y reinicia el servicio.

3. Entrega la clave al cliente por un canal privado. Nunca la escribas en el código, en
   un ticket ni en el repositorio.

El log y la traza llevan el nombre del cliente (`client`), nunca la clave. Las claves
se comparan con `hmac.compare_digest`.

### Usar la clave

La página ya no pide clave (ver «Modo demo»): nunca manda `X-API-Key` ni guarda nada
en el navegador. Las integraciones mandan la clave en el encabezado, por ejemplo con
`curl`:

```bash
curl -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -H "X-API-Key: $SUPPORT_API_KEY" \
  -d '{"question": "No me puedo conectar a la VPN desde mi casa"}'
```

### Límite de peticiones

Cada cliente puede hacer `RATE_LIMIT_PER_MINUTE` peticiones en 60 segundos (ventana
deslizante). Pasado el límite, la respuesta es `429 {"detail": "rate limit exceeded",
"request_id": ...}` con `Retry-After` (segundos que faltan, al menos 1). El contador
vive en la memoria del proceso: se reinicia al reiniciar y no se comparte entre
instancias.

### Compliance en producción

Con `ENVIRONMENT=production` el producto no arranca si `MODEL_PROVIDER=fake`, si
`API_KEYS` está vacía o tiene una clave de menos de 16 caracteres, o si
`LANGSMITH_TRACING=true` y `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`. El error
nombra la regla, nunca un valor secreto. La lista completa y cómo se comprueba cada
regla están en `doc/compliance-checklist.md`.

## Configuración con `.env`

La configuración va en un archivo `product/.env`, no en variables escritas en la
terminal:

```bash
cp .env.example .env
```

Edita `.env` con tus valores. Al arrancar, el producto lee el archivo que indica
`ENV_FILE` (por omisión `.env`; una ruta relativa se resuelve contra `product/`):

- Si una variable está en el entorno y en el archivo, gana la del entorno.
- Si el archivo no existe, se arranca solo con el entorno, sin error.
- Con `ENV_FILE=none` no se lee ningún archivo (así corren las verificaciones).

`.env` lleva secretos: nunca se sube al repositorio ni se copia a otro lado, y su
contenido nunca se escribe en el log ni en un error.

## Modelo real (Workers AI a través de AI Gateway)

1. En Cloudflare, crea un AI Gateway con la autenticación encendida
   (**Authenticated Gateway**) y un token de API con estos permisos de la cuenta:
   - **Workers AI: Read**
   - **AI Gateway: Run**
2. En `product/.env` pon:

   ```bash
   MODEL_PROVIDER=gateway
   CF_ACCOUNT_ID=<id de tu cuenta>
   CF_GATEWAY_ID=<nombre de tu gateway>
   CF_API_TOKEN=<tu token>
   ```

3. Arranca como siempre con `uvicorn app.main:app --port 8000`.

El producto llama a
`https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions`
con `Authorization: Bearer {CF_API_TOKEN}` y `cf-aig-authorization: Bearer
{CF_API_TOKEN}` (el encabezado del gateway autenticado), una sola vez por vuelta y sin
reintentos. Si el token no tiene los dos permisos o el gateway no acepta el encabezado,
`POST /ask` responde `502`.
Con `gateway`, si falta cualquiera de las tres variables `CF_*` el producto no arranca;
el error nombra la variable, nunca su valor. La cuenta y el token nunca aparecen en el
log, en un error ni en el `repr` de la configuración.

## API

| Método y ruta | Qué hace |
| --- | --- |
| `GET /` | La página web (sin clave) |
| `GET /health` | `{"status": "ok", "pid": <id del proceso>}` (sin clave) |
| `POST /ask` | Responde una pregunta (con `X-API-Key`; sin clave en modo demo) |
| `GET /metrics` | Métricas de este proceso (con `X-API-Key`) |

Ejemplo de `POST /ask`:

```bash
curl -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -H "X-API-Key: $SUPPORT_API_KEY" \
  -d '{"question": "No me puedo conectar a la VPN desde mi casa", "history": []}'
```

Sin clave (fuera del modo demo) o con una inválida la respuesta es `401 {"detail":
"invalid or missing API key", "request_id": ...}`, antes de validar el cuerpo; por
encima del límite, `429` con `Retry-After`; en modo demo, con el tope de gasto
alcanzado, `503 {"detail": "daily budget exhausted", "request_id": ...}`.

La respuesta trae `answer`, `steps`, `tools_used`, `escalated`, `team`,
`input_tokens`, `output_tokens`, `request_id`, `outcome`, `model` (el modelo que
respondió), `route` (por qué se eligió), `cached_calls` (llamadas que vinieron de la
caché del gateway) y `cost_usd` (el costo de la respuesta). Una pregunta vacía, en
blanco o más larga que `MAX_QUESTION_CHARS` da `422`. `history` es opcional y cada
mensaje tiene `role` (`user` o `assistant`) y `content`.

`outcome` dice cómo terminó la pregunta:

- `solved`: se entregó la solución de un artículo de la base de conocimiento.
- `escalated`: se transfirió con un equipo humano.
- `needs_detail`: se pidió a la persona que describiera mejor su problema.
- `incomplete`: el agente llegó al tope de vueltas sin responder.

Si algo truena, la respuesta es `500` con `{"detail": "internal error",
"request_id": ...}`. Si el modelo real falla (red, tiempo de espera, código de error o
respuesta inválida), la respuesta es `502` con `{"detail": "model unavailable",
"request_id": ...}` y el log registra un evento `error` con el tipo de error.

## Costos

Los precios están en `data/model_prices.json` (USD por millón de tokens). Un modelo
configurado que no esté en la tabla impide arrancar.

- **Enrutamiento** (`ROUTING`): una regla en código manda la pregunta a `MODEL_LARGE`
  si el enrutamiento está apagado (`route: routing_disabled`), si pasa de
  `ROUTER_MAX_CHARS` caracteres (`long_question`) o si contiene, como palabra o frase
  completa y sin distinguir mayúsculas ni acentos, «por qué», «explica», «varios»,
  «todos», «otra vez» o «sigue» (`keyword:<palabra>`). Si no, a `MODEL_SMALL`
  (`default`).
- **Ventana de historial** (`HISTORY_WINDOW`): al modelo solo llegan los últimos
  mensajes del historial (0: ninguno).
- **Tope de salida** (`MODEL_MAX_TOKENS`) en cada llamada.
- **Caché del gateway** (`CACHE_TTL_SECONDS` mayor que 0): se manda
  `cf-aig-cache-ttl`; una llamada con `cf-aig-cache-status: HIT` cuenta en
  `cached_calls` y no cuesta.

Con `MODEL_PROVIDER=fake` hay dos modelos simulados que se llaman como `MODEL_SMALL` y
`MODEL_LARGE`: responden igual, pero se cobran con el precio de su nombre. Así las
palancas se miden sin red y sin gastar cuota.

La búsqueda usa las palabras de la pregunta de la persona junto con las del `problem`
que manda el modelo, y la transferencia siempre responde `Te comunico con <equipo>.`
sin otra llamada al modelo.

## Observabilidad

### Folio (`request_id`)

Si el cliente manda `X-Request-ID` con 1 a 128 caracteres `A-Z a-z 0-9 . _ : -`, se
usa ese valor; si no, se genera un UUID. Toda respuesta lo devuelve en el encabezado
`X-Request-ID` y `POST /ask` también en el cuerpo. La página lo muestra como
`request_id: <id>` bajo cada respuesta y, si hubo transferencia, como
«Te transferimos con <equipo>. Folio: <id>».

### Log JSON

Una línea JSON por evento en la salida estándar, escrita en cuanto ocurre, con `ts`
(ISO 8601 en UTC), `service`, `event` y `request_id`:

| Evento | Campos |
| --- | --- |
| `request` | `method`, `path`, `status`, `latency_ms`, `client` (`null` sin clave válida; uno por petición) |
| `agent_run` | `client`, `question_chars`, `history_messages`, `steps`, `tools`, `outcome`, `team`, `article_id`, `input_tokens`, `output_tokens`, `stopped`, `model`, `route`, `cached_calls`, `cost_usd`; con `LOG_CONVERSATION_TEXT=true`, también `question` y `answer` |
| `audit` | `client`, `action: "tool_call"`, `tool`; en la búsqueda `problem_chars`, `category` y `article_ids`; en la transferencia `category` y `team` |
| `error` | `error_type` (el tipo, nunca el mensaje) |
| `budget_exhausted` | `spent_usd`, `budget_usd` (modo demo; una vez por día UTC) |

El texto del historial, el del problema en `audit` y el de `request` o `error` nunca
se registran. Advertencia: con `LOG_CONVERSATION_TEXT=true` (por omisión) el log
contiene lo que escribieron las personas. En producción queda encendida como decisión
aceptada (acceso a los logs solo para el equipo de soporte), documentada en
`doc/compliance-checklist.md`; se apaga con `LOG_CONVERSATION_TEXT=false`.

### Buscar una petición por su folio

La persona da a soporte el folio que ve en la página. Para ver todo lo que pasó con
esa petición, filtra el log por ese `request_id`:

```bash
uvicorn app.main:app --port 8000 > product.log
grep '"request_id": "folio-123"' product.log
```

Las líneas salen en orden: `audit` de cada herramienta, `agent_run` y `request` (o
`error` y `request` si algo tronó). Con `jq`:
`jq 'select(.request_id == "folio-123")' product.log`.

### Métricas

`GET /metrics` devuelve las métricas de este proceso:

```json
{"pid": 1234, "requests": 10, "error_rate": 0.0,
 "latency_ms": {"p50": 3.1, "p95": 8.0}, "tokens": {"input": 120, "output": 40},
 "outcomes": {"solved": 4, "escalated": 3, "needs_detail": 2, "incomplete": 0},
 "self_service_rate": 0.444, "slo": {"p95_ms_target": 4000, "met": true},
 "cost_usd": 0.0000412, "cost_per_solved_usd": 0.0000103}
```

- `error_rate`: fracción de peticiones con código `5xx`.
- `self_service_rate`: preguntas `solved` entre las respondidas por `POST /ask`.
- `cost_usd`: costo acumulado de este proceso.
- `cost_per_solved_usd`: `cost_usd` entre las preguntas `solved` (`0` si no hay
  ninguna): lo que cuesta resolver un problema sin un humano.
- `slo.met`: `true` si el p95 está por debajo de `SLO_P95_MS`. La meta por omisión es
  de 4 segundos (`4000` ms): con el modelo real cada pregunta hace dos llamadas al
  modelo y un p95 de 2 segundos no es alcanzable.
- Solo se guardan las últimas 1000 latencias; percentiles por rango más cercano.

### Trazas en LangSmith (opcional)

Con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY` en el entorno, cada corrida del
agente, cada llamada al modelo y cada herramienta quedan como trazas con el
`request_id` y el nombre del cliente (`client`) en sus metadatos. Sin la clave, el
producto funciona igual y no intenta conectarse (ni carga `langsmith`). La clave nunca
se escribe en el log ni en el código.

#### Crear la clave

1. Entra a [smith.langchain.com](https://smith.langchain.com) y abre **Settings >
   API Keys > Create API Key**.
2. Copia la clave (empieza con `lsv2_`). Solo se muestra una vez.
3. Guárdala solo en `product/.env` o en Render > Environment; nunca en el código, en un
   ticket ni en el repositorio.

#### Encender las trazas en tu equipo

En `product/.env`:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<tu clave>
LANGSMITH_PROJECT=support-assistant
# Solo en desarrollo, para ver el texto de preguntas y respuestas:
HIDE_INPUTS=false
HIDE_OUTPUTS=false
```

Si tu cuenta es de la región europea, agrega también
`LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`. Arranca como siempre y abre
el proyecto `support-assistant` en LangSmith. Con `ENVIRONMENT=production` el producto
no arranca si `HIDE_INPUTS` o `HIDE_OUTPUTS` no valen `true`.

#### Encender las trazas en Render

El Blueprint ya fija `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=support-assistant`,
`HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`. Para ver las trazas, agrega
`LANGSMITH_API_KEY` en Render > Environment y guarda: Render redespliega. Sin la clave
las trazas siguen apagadas y el servicio responde igual.

#### Qué se ve en cada traza

Las trazas van al proyecto de `LANGSMITH_PROJECT` (`support-assistant` por omisión,
nunca `default`).

- `agent_run` (tipo `chain`): la corrida completa. Además del `request_id`, al terminar
  lleva los metadatos `model`, `route`, `outcome`, `escalated`, `team`, `article_id`,
  `cached_calls`, `cost_usd`, `steps` y `client`, y las etiquetas `outcome:<outcome>`,
  `route:<route>` y `model:<modelo>`. Si el modelo falla (`502`), no se anota.
- `model_complete` (tipo `llm`): una por llamada al modelo, con los metadatos
  `ls_provider` (`cloudflare` o `fake`) y `ls_model_name` (el modelo usado). Sus
  salidas traen `usage_metadata` con `input_tokens`, `output_tokens` y
  `total_tokens`: así LangSmith muestra los tokens de cada llamada.
- `search_knowledge_base` y `escalate_to_human` (tipo `tool`): una por herramienta.

Con `HIDE_INPUTS=true` (por omisión) no se manda ninguna entrada. Con
`HIDE_OUTPUTS=true` (por omisión) de las salidas solo se manda `usage_metadata`: el
texto de la respuesta nunca sale, pero los tokens sí. Las trazas nunca llevan una
clave, la IP de la persona ni el contenido de `.env`.

Las trazas se mandan en segundo plano: si LangSmith no responde o la clave es
inválida, `POST /ask` responde igual y en el mismo tiempo; el aviso queda en el logger
de la librería (stderr) y nunca en el evento `error` del log.

#### Filtrar por etiquetas

En el proyecto de LangSmith, en **Runs**, agrega un filtro **Tags** con la etiqueta
que buscas, por ejemplo:

- `outcome:escalated`: todas las transferencias con un humano.
- `outcome:incomplete`: las preguntas que llegaron al tope de vueltas.
- `route:long_question` o `route:keyword:explica`: por qué se eligió el modelo.
- `model:@cf/meta/llama-3.3-70b-instruct-fp8-fast`: las que respondió el modelo capaz.

También puedes filtrar por metadatos, por ejemplo `client` o `request_id` para seguir
la petición de un folio.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `ENV_FILE` | `.env` | Archivo de configuración que se lee al arrancar (`none`: ninguno) |
| `ENVIRONMENT` | `development` | Con `production` se aplican las reglas de compliance |
| `API_KEYS` | (vacía) | Clientes y claves, `cliente:clave,cliente2:clave2` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (1 o más) |
| `PUBLIC_PAGE` | `false` | Modo demo: `/ask` sin clave, con límites (`true` o `false`) |
| `PUBLIC_RATE_LIMIT_PER_MINUTE` | `5` | Preguntas sin clave por IP por minuto |
| `DAILY_BUDGET_USD` | `0.50` | Tope de gasto diario de las preguntas sin clave |
| `TRUST_PROXY` | `false` | Leer la IP de `X-Forwarded-For` (solo detrás de un proxy, como Render) |
| `MODEL_PROVIDER` | `fake` | Qué modelo usar: `fake` (simulado) o `gateway` (Workers AI) |
| `CF_ACCOUNT_ID` | (vacía) | Cuenta de Cloudflare (obligatoria con `gateway`) |
| `CF_GATEWAY_ID` | `default` | Nombre del AI Gateway |
| `CF_API_TOKEN` | (vacía) | Token de Cloudflare, secreto (obligatorio con `gateway`) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta (`true` o `false`) |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan al modelo (0 o más) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida por llamada |
| `MODEL_TEMPERATURE` | `0` | Temperatura; con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo (relativa a `product/`) |
| `AGENT_MAX_STEPS` | `4` | Tope de vueltas del bucle del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `KB_PATH` | `data/knowledge_base.json` | La base de conocimiento (relativa a `product/`) |
| `KB_MIN_SCORE` | `2` | Palabras clave que deben coincidir para ofrecer un artículo |
| `KB_MAX_RESULTS` | `2` | Artículos que devuelve la búsqueda como máximo |
| `SERVICE_NAME` | `support-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `4000` | Meta de latencia p95 en milisegundos (4 segundos) |
| `LOG_CONVERSATION_TEXT` | `true` | Registrar pregunta y respuesta en `agent_run` (`true` o `false`) |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas (`true` o `false`) |
| `LANGSMITH_API_KEY` | (vacía) | Clave de LangSmith, secreta; sin ella no hay trazas |
| `LANGSMITH_PROJECT` | `support-assistant` | Proyecto de LangSmith donde caen las trazas (no vacío) |
| `LANGSMITH_ENDPOINT` | (de la librería) | Solo para cuentas de la región europea de LangSmith |
| `HIDE_INPUTS` | `true` | No mandar a LangSmith ninguna entrada |
| `HIDE_OUTPUTS` | `true` | De las salidas mandar solo `usage_metadata` (los tokens), nunca el texto |

Un valor inválido (por ejemplo `AGENT_MAX_STEPS=0`, `KB_MIN_SCORE=0`, `SLO_P95_MS=0`,
`LOG_CONVERSATION_TEXT=quizas`, `HIDE_INPUTS=1`, `ROUTER_MAX_CHARS=0`,
`HISTORY_WINDOW=-1`, `MODEL_TEMPERATURE=x`, `CACHE_TTL_SECONDS=-1`, `ROUTING=si`,
`ENVIRONMENT=staging`, `RATE_LIMIT_PER_MINUTE=0`, `PUBLIC_PAGE=si`,
`DAILY_BUDGET_USD=nan`, `LANGSMITH_PROJECT` vacía, con `PUBLIC_PAGE=true` un `DAILY_BUDGET_USD=0` o
`PUBLIC_RATE_LIMIT_PER_MINUTE=0`, un `API_KEYS` mal formado o un
`KB_PATH` o `PRICES_PATH` que no existe o no tiene la forma descrita) impide arrancar
con un mensaje que nombra la variable.

## Pruebas

Los pasos son los mismos que corre el CI (`.github/workflows/ci.yml`), desde
`product/`.

### Estilo (pylint, 88 columnas)

pylint no es parte de la aplicación; se instala aparte:

```bash
pip install pylint
python -m pylint app tests --max-line-length=88 --fail-under=10 \
  --disable=missing-function-docstring,redefined-outer-name,too-few-public-methods
```

### Unitarias y BDD (cobertura de 80 % o más)

```bash
ENV_FILE=none python -m pytest -q tests --cov=app --cov-fail-under=80
```

Los escenarios Gherkin están en `tests/features/` y las pruebas unitarias en `tests/`.

### De punta a punta (Playwright)

Las pruebas de `e2e/` abren la página en Chromium contra el producto ya arrancado en
modo demo (`PUBLIC_PAGE=true`). No usan ninguna clave: la página pregunta sin ella.

1. Instala pytest-playwright y el navegador como explica «Para correr las pruebas»
   (no son parte de la aplicación).

2. En una terminal, arranca el producto con el modelo simulado y el modo demo:

   ```bash
   MODEL_PROVIDER=fake ENV_FILE=none PUBLIC_PAGE=true \
     python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

3. En otra terminal:

   ```bash
   python -m pytest e2e -q -p no:cacheprovider --base-url http://127.0.0.1:8000
   ```

Toda la suite hace como mucho 5 `POST /ask`, porque todas las pruebas salen de la
misma IP y el límite por omisión es de 5 preguntas sin clave por minuto.

## Contenedor y publicación

Cuatro archivos llevan el producto a producción:

| Archivo | Qué hace |
| --- | --- |
| `Dockerfile` | Imagen `python:3.12-slim` con solo `app/` y `data/`, usuario sin privilegios |
| `render.yaml` | Blueprint de Render: el servicio web `support-assistant` |
| `.github/workflows/ci.yml` | Pipeline de CI: `style -> unit -> e2e -> docker` |
| `scripts/smoke.py` | Prueba de humo contra el servicio publicado |

### Construir y correr la imagen

```bash
docker build --tag support-assistant .
docker run --rm -p 8000:8000 -e API_KEYS="local:local-example-key-0123456789" \
  support-assistant
```

La imagen tiene `ENV_FILE=none` y no lleva `.env` (lo excluye `.dockerignore`): la
configuración llega solo por el entorno. Para usar tu `product/.env` local, pásalo
con `--env-file` como explica «Con Docker»: Docker lo lee en tu máquina y no lo copia
a la imagen.

Escucha en el puerto de `PORT` (8000 si no está definida) y responde `GET /health`.
Sin `API_KEYS` arranca, pero nadie puede preguntar. Con `ENVIRONMENT=production`
aplica las reglas de compliance (ver «Compliance en producción»).

### Publicar con el Blueprint de Render

1. Sube el repositorio a GitHub y, en Render, crea un **Blueprint** desde él. Render
   lee `render.yaml` y crea el servicio web `support-assistant` (Docker, plan free,
   `healthCheckPath: /health`).
2. El Blueprint fija los valores de producción: `ENVIRONMENT=production`,
   `MODEL_PROVIDER=gateway`, `CF_GATEWAY_ID=support-assistant`,
   `LOG_CONVERSATION_TEXT=true`, `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`, y los del
   modo demo: `PUBLIC_PAGE=true`, `TRUST_PROXY=true`,
   `PUBLIC_RATE_LIMIT_PER_MINUTE=5` y `DAILY_BUDGET_USD=0.50`.
3. Los secretos `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN` tienen `sync: false`:
   no están en el repositorio y Render los pide al crear el Blueprint. Se escriben (o
   se cambian después) en Render > Environment.
4. Las trazas: el Blueprint fija `LANGSMITH_TRACING=true`,
   `LANGSMITH_PROJECT=support-assistant` y `SLO_P95_MS=4000`. `LANGSMITH_API_KEY` no
   está en el Blueprint porque es opcional: para ver las trazas, agrégala a mano en
   Render > Environment (ver «Trazas en LangSmith»).

El pipeline de `.github/workflows/ci.yml` corre en cada `push` y `pull_request` cuatro
trabajos encadenados: `style` (pylint) -> `unit` (pruebas con cobertura) -> `e2e`
(Playwright con el modelo simulado) -> `docker` (construye la imagen y comprueba que
arranca sin `.env`, sin root y responde `/health`). Con `autoDeployTrigger:
checksPass`, Render publica solo cuando los cuatro pasan.

### Prueba de humo

Después de publicar, comprueba el servicio con `scripts/smoke.py`. La clave se lee de
la variable `SMOKE_API_KEY` (nunca de un argumento, para que no quede en el historial)
y debe ser una de las de `API_KEYS` en Render:

```bash
pip install -r requirements.txt
read -rs SMOKE_API_KEY && export SMOKE_API_KEY
python scripts/smoke.py https://support-assistant.onrender.com
```

Imprime `[OK]` o `[FAIL]` para `GET /health` (200), `POST /ask` con una clave
equivocada generada al azar (401; sirve con y sin modo demo) y
`POST /ask` con clave (200), con el código recibido; la clave nunca se imprime. Un 401
con clave significa que no coincide con `API_KEYS`; un 502, que el modelo no responde.
Espera hasta 90 segundos por petición, porque Render despierta un servicio dormido del
plan free en hasta un minuto.

| Código de salida | Significado |
| --- | --- |
| `0` | Las tres comprobaciones pasan |
| `1` | Alguna comprobación falla |
| `2` | Falta la URL o la variable `SMOKE_API_KEY` |
