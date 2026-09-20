# La web de Alberto lista para vivir fuera del portátil: gunicorn, estáticos recogidos, sin root.
# Cómo se despliega (Railway + Cloudflare) y qué variables necesita: docs/despliegue.md.
FROM python:3.12-slim

# El mismo uv que usamos en local; instala lo que dice uv.lock, ni más ni menos.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_DEBUG=0 \
    ALMACEN_DIR=/datos/almacen \
    STATIC_ROOT=/app/staticfiles

WORKDIR /app

# Primero solo las dependencias: si cambia el código pero no uv.lock, esta capa se reutiliza.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Junta los estáticos en STATIC_ROOT; WhiteNoise los sirve desde el propio proceso.
# La clave es de mentira: aquí no arranca nada, solo se copian ficheros.
RUN DJANGO_SECRET_KEY=solo-para-collectstatic python manage.py collectstatic --noinput

# Sin root. Los PDF que sube Alberto van a /datos (un disco persistente montado ahí); outputs/ es caché.
RUN useradd --system --uid 1000 --create-home alberto \
    && mkdir -p /datos/almacen /app/outputs \
    && chown -R alberto:alberto /datos /app/outputs
USER alberto

EXPOSE 8000

# Al arrancar: migra, dice en llano qué falta (sin bloquear) y sirve.
# Un solo worker con hilos, a propósito: el avance de un repaso vive en la memoria del proceso
# (web/panel/repasos.py); con dos workers la barra preguntaría a uno y el repaso correría en el otro.
# Para cambiar algo de gunicorn sin tocar la imagen: variable GUNICORN_CMD_ARGS.
CMD ["sh", "-c", "python manage.py migrate --noinput && { python manage.py comprobar_despliegue || true; } && exec gunicorn web.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 300 --access-logfile -"]
