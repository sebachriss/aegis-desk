# Imagen de la API de Aegis Desk (FastAPI + LangGraph).
# Construir: docker build -t aegis-desk-api .
FROM python:3.11-slim

# Evitar buffers y archivos .pyc innecesarios
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias del sistema para compilar extensiones nativas (ej. chroma-hnswlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root para ejecutar la aplicación
RUN groupadd -r aegis && \
    useradd -r -g aegis -s /bin/false -d /app aegis && \
    mkdir -p /app/data && \
    chown -R aegis:aegis /app

# Instalar dependencias en un venv propiedad del usuario no-root
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY --chown=aegis:aegis requirements.txt requirements-lock.txt ./
RUN pip install -r requirements-lock.txt

# Copiar solo el código fuente (respetando .dockerignore)
COPY --chown=aegis:aegis . .

# Entrypoint: inicializa Chroma si no existe (ingesta RAG) antes de arrancar
RUN chmod +x /app/scripts/docker-entrypoint-api.sh

USER aegis

EXPOSE 8000

# Healthcheck real sobre el endpoint /health de la API
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint-api.sh"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
