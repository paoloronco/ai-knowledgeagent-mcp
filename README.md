# Knowledge MCP

Search your documents through an MCP server. The Docker image contains the Web UI, ingestion service, MCP server, and Qdrant. After starting the container, use the Web UI to upload documents, review the policy, run indexing, schedule updates, and enable or disable MCP. No repository clone or local Python installation is required for the standard setup.

## Docker installation

Install Docker, then run:

```bash
docker pull paoloronco/knowledge-mcp:latest
docker run -d --name knowledge-mcp --restart unless-stopped -p 127.0.0.1:8080:8080 -p 127.0.0.1:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage paoloronco/knowledge-mcp:latest
```

Open **http://127.0.0.1:8080** on the Docker host. Upload a folder or files in the Web UI, review the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), then run the ten-document test or a full index. The MCP endpoint is **http://127.0.0.1:8000/mcp** when enabled; it is for MCP clients, not a browser page.

The two named volumes keep uploaded documents, settings, indexing state, model cache, and Qdrant data across container replacements. Do not remove them if you want to keep the index. Qdrant listens only inside the container and is not published to the host.

If Docker runs on another machine, use a secure port forward or authenticated proxy to open the Web UI. It has no built-in login, so the Docker command binds both published ports to localhost.

### Update or stop

To replace the container with the latest image while keeping its volumes:

```bash
docker pull paoloronco/knowledge-mcp:latest
docker stop -t 30 knowledge-mcp
docker rm knowledge-mcp
docker run -d --name knowledge-mcp --restart unless-stopped -p 127.0.0.1:8080:8080 -p 127.0.0.1:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage paoloronco/knowledge-mcp:latest
```

To stop it without removing the container, run `docker stop knowledge-mcp`; use `docker start knowledge-mcp` to start it again.

### Use an existing host folder

For a large collection already on the Docker host, add a read-only mount and select it as the source:

```bash
docker run -d --name knowledge-mcp --restart unless-stopped -p 127.0.0.1:8080:8080 -p 127.0.0.1:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage -v /absolute/path/to/documents:/knowledge:ro -e KNOWLEDGE_ROOT=/knowledge paoloronco/knowledge-mcp:latest
```

Replace the path with an existing absolute path; on Windows, use a path such as `C:/Users/Name/Documents`. The Web UI can select a subfolder within this mount. Browser uploads are disabled while a host folder is mounted. If you already have a separate Qdrant container, its index is **not** imported automatically. Keep that container and its storage until you have planned a migration.

## Docker Compose alternative

The public repository also provides [compose.yaml](compose.yaml). Choose either `docker run` or Compose: their default volume names differ.

```bash
git clone https://github.com/paoloronco/ai-knowledgeagent-mcp.git
cd ai-knowledgeagent-mcp
docker compose up -d
```

For an existing host folder, see the override example in [Docker deployment notes](docs/docker.md). To update, run `git pull`, `docker compose pull`, then `docker compose up -d`. If upgrading an older two-container Compose installation, run `docker compose down` **before** `git pull` so the old Qdrant process releases its volume; `down` keeps the data volumes.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
