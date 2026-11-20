# Imagen del Support Assistant (spec/04-production.md, «Contenedor»).
# Solo lleva app/ y data/; la configuración llega por el entorno de Render,
# nunca por un archivo .env (que además queda fuera por .dockerignore).
FROM python:3.12-slim

# Sin archivos .pyc, log sin búfer (una línea JSON por evento en cuanto ocurre)
# y ningún archivo de configuración: ENV_FILE=none hace que no se busque .env.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENV_FILE=none

WORKDIR /srv/product

# Usuario sin privilegios: el proceso nunca corre como root.
RUN groupadd --system --gid 10001 assistant \
    && useradd --system --uid 10001 --gid assistant --no-create-home assistant

# Primero las dependencias, para que la capa se reutilice si solo cambia el código.
COPY requirements.txt .
RUN pip install -r requirements.txt

# El código y los datos (base de conocimiento y precios), propiedad de root y
# solo de lectura para el usuario del servicio.
COPY app/ app/
COPY data/ data/

USER assistant

EXPOSE 8000

# Render define PORT; en local se usa 8000. Se usa sh para expandir la variable
# y exec para que uvicorn reciba las señales de apagado directamente.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
