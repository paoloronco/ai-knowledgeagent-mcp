# Troubleshooting

## Docker container exits immediately or the Web UI is unreachable

Use the complete `docker run` command in the root README, including port and volume flags. Check `docker ps -a` and `docker logs knowledge-mcp`. With Compose, check `docker compose ps` and `docker compose logs app`. Open `http://HOST_IP:8080` from the LAN. If it works at `http://127.0.0.1:8080` on the Docker host but not from another computer, check that Docker published port 8080 on `0.0.0.0` and that the host firewall allows it.

## Docker prints localized progress messages

The Docker client prints its own container creation and pull messages using its host settings. These messages are outside the application. On Linux, run a command with `LC_ALL=C` if you want to request English output from the Docker client, for example `LC_ALL=C docker compose up -d`.

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
