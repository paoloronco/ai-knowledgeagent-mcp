# Knowledge MCP

Search your documents through an MCP server. Docker Compose runs the app and Qdrant; the local Web UI handles document uploads, indexing, policy changes, scheduling, and MCP on/off control. No local Python installation is needed.

## Start with Docker

Install Docker with Compose, then run these commands from a terminal:

```bash
git clone https://github.com/paoloronco/ai-knowledgeagent-mcp.git
cd ai-knowledgeagent-mcp
docker pull paoloronco/knowledge-mcp:latest
docker compose up -d
```

Open **http://127.0.0.1:8080**. Select a folder or files in the Web UI, upload them, review the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), and start a ten-document test or a full index. Uploaded files, indexing state, model cache, and Qdrant data persist in Docker volumes. The MCP endpoint is **http://127.0.0.1:8000/mcp** when enabled; use an MCP client, not a browser page, to call it.

`docker run paoloronco/knowledge-mcp` by itself does not start Qdrant or publish the Web UI port. Use the Compose command above for the complete app. If Docker runs on another machine, forward port 8080 securely to your computer; the Web UI has no built-in login. Both app ports are bound to localhost by default.

### Use an existing host folder instead of uploading

For a large collection already on the Docker host, create `compose.override.yaml` beside `compose.yaml`:

```yaml
services:
  app:
    environment:
      KNOWLEDGE_ROOT: /knowledge
    volumes:
      - type: bind
        source: /absolute/path/to/documents
        target: /knowledge
        read_only: true
        bind:
          create_host_path: false
```

Replace `source` with an existing absolute host path, then run `docker compose up -d`. The Web UI can choose a subfolder within this mount; browser uploads are disabled in this mode. On Windows, use a path such as `C:/Users/Name/Documents`.

Compose starts its own Qdrant volume. It does **not** import data from a separately running Qdrant container. Keep your previous Qdrant volume and ingestion state until you have verified a migration.
If upgrading from the earlier Compose setup that used `KNOWLEDGE_HOST_PATH`, add the read-only mount above for that same folder before running a full index. The new default library starts empty, and a full index removes previously indexed documents that are absent from the selected source.

## Update or stop

```bash
git pull
docker pull paoloronco/knowledge-mcp:latest
docker compose up -d
```

`docker compose down` stops the stack and keeps its volumes. **`docker compose down -v` deletes them**, including uploaded documents and the index. For remote access, put an authenticated proxy in front of the Web UI and MCP server; see the [security guide](docs/security-model.md).

## More information

- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)
- [Docker Hub publishing workflow](.github/workflows/docker.yml)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
