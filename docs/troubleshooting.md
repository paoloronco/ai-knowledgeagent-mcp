# Troubleshooting

## Docker container exits immediately or the Web UI is unreachable

Run `docker compose up -d` from the repository root. A bare `docker run` does not publish port 8080 or start Qdrant. Check `docker compose ps` and `docker compose logs app`. The Web UI is available at `http://127.0.0.1:8080` on the Docker host. To open it from another computer, use a secure port forward or authenticated proxy.

## ImportError: MCPServer

Install the declared dependencies in the active virtual environment: python -m pip install -r knowledge-mcp/requirements.txt. The server uses the MCP Python SDK 2.x import path mcp.server.mcpserver.

## Missing policy or knowledge root

Create knowledge-mcp/.env from .env.example and set KNOWLEDGE_ROOT to an existing directory. Ingestion reads knowledge-mcp/mcp/index-policy.yaml by default; POLICY_FILE can override it.

## Qdrant unavailable

Check curl --fail http://127.0.0.1:6333/readyz and QDRANT_URL. knowledge_status reports unavailable when it cannot count the collection. Ingestion must create and populate the collection before the first search.

## Search misses newly indexed files

Restart the MCP server after ingestion. Retrieval snapshots Qdrant payloads into memory on its first search.

## Empty PDF results

The parser extracts embedded text only. It does not OCR scanned pages.

## SentenceTransformer import fails in torchvision

Check that torch and torchvision in the active environment are compatible. A mismatched pair can fail before the embedding model loads. Ingestion dry runs and knowledge_status do not require the model.

## Remote client receives 403

Check the proxy or Cloudflare Access policy. The MCP server does not issue 403 on its own. Test the endpoint with an MCP client, not a plain GET request.

## Service logs

On a systemd deployment, use sudo journalctl -u knowledge-mcp -f. Ingestion parse errors are written under INGESTION_BASE_DIR/logs/errors.log.
