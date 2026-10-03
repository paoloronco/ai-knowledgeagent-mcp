FROM qdrant/qdrant:v1.19.1 AS qdrant

FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/huggingface \
    KNOWLEDGE_ROOT=/data/documents \
    INGESTION_BASE_DIR=/data/ingestion \
    POLICY_FILE=/data/index-policy.yaml \
    MCP_HOST=0.0.0.0 \
    QDRANT_URL=http://127.0.0.1:6333 \
    QDRANT__SERVICE__HOST=127.0.0.1 \
    RUN_MODE=production

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libunwind8 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY --from=qdrant /qdrant/qdrant /qdrant/qdrant
COPY --from=qdrant /qdrant/config /qdrant/config
COPY --from=qdrant /qdrant/static /qdrant/static
COPY ingestion/ ingestion/
COPY mcp/ mcp/
COPY host_agent.py .

EXPOSE 8080 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1
CMD ["python", "mcp/entrypoint.py"]
