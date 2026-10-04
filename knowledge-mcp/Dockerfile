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
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    RUN_MODE=production

WORKDIR /app
COPY requirements.txt .
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_EXPECTED_CUDA=cpu
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libunwind8 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir torch==2.14.0 --index-url "$TORCH_INDEX_URL" \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "import os, torch; expected=os.environ['TORCH_EXPECTED_CUDA']; assert (torch.version.cuda or 'cpu') == expected, (torch.version.cuda, expected)"
COPY --from=qdrant /qdrant/qdrant /qdrant/qdrant
COPY --from=qdrant /qdrant/config /qdrant/config
COPY --from=qdrant /qdrant/static /qdrant/static
COPY ingestion/ ingestion/
COPY mcp/ mcp/
COPY host_agent.py .

EXPOSE 8080 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1
CMD ["python", "mcp/entrypoint.py"]
