#!/usr/bin/env bash
set -e

# Inicializa Chroma si no existe (ingesta de documentos RAG).
# Se ejecuta solo la primera vez; en reinicios usa la base persistida en el volumen.
if [ ! -d "/app/data/chroma" ] || [ -z "$(ls -A /app/data/chroma 2>/dev/null)" ]; then
    echo "[entrypoint] Inicializando base de datos vectorial..."
    python -m src.rag.ingest
fi

exec "$@"
