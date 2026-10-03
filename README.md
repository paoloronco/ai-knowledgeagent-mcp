# Knowledge MCP

Search your documents through an MCP server. The Docker image contains the Web UI, ingestion service, MCP server, and Qdrant. Mount an existing document folder read-only, then select its container path in the Web UI, review the policy, run indexing, schedule updates, and enable or disable MCP. The dashboard does not upload documents.

## Docker installation

Install Docker, replace `/absolute/path/to/documents` with an existing folder on the Docker host, then run:

```bash
docker pull paoloronco/knowledge-mcp:latest
docker run -d --name knowledge-mcp --restart unless-stopped -p 0.0.0.0:8080:8080 -p 0.0.0.0:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage --mount type=bind,src=/absolute/path/to/documents,dst=/mnt/knowledge,readonly paoloronco/knowledge-mcp:latest
```

Open `http://HOST_IP:8080` from a device on the same LAN (for example, `http://10.10.10.80:8080`). Enter `/mnt/knowledge` as the document root in the first-run guide. The path is the **container path**, not the host path. The guide offers an optional dashboard password, checks service health, lets you select folders and review the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), runs a ten-document test, then starts indexing. The dashboard shows indexing progress and controls the MCP server. The MCP endpoint is `http://HOST_IP:8000/mcp` when enabled; it is for MCP clients, not a browser page.

The two named volumes keep settings, indexing state, model cache, Qdrant data, and any documents uploaded by older versions. Do not remove them if you want to keep the index. Qdrant listens only inside the container and is not published to the host.

Ports 8080 and 8000 are published on all Docker host interfaces. The Web UI has an optional password; the MCP server still has no built-in login. Restrict access to a trusted LAN with a firewall, and add an authenticated proxy before exposing either port to the Internet. Use HTTPS when entering the dashboard password over a network.

### Update or stop

To replace the container with the latest image while keeping its volumes:

```bash
docker pull paoloronco/knowledge-mcp:latest
docker stop -t 30 knowledge-mcp
docker rm knowledge-mcp
docker run -d --name knowledge-mcp --restart unless-stopped -p 0.0.0.0:8080:8080 -p 0.0.0.0:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage --mount type=bind,src=/absolute/path/to/documents,dst=/mnt/knowledge,readonly paoloronco/knowledge-mcp:latest
```

To stop it without removing the container, run `docker stop knowledge-mcp`; use `docker start knowledge-mcp` to start it again.

### Use an existing host folder

The dashboard can select any existing folder visible inside the container. For example, if the host folder is `/mnt/knowledge`, mount it at the same path:

```bash
docker run -d --name knowledge-mcp --restart unless-stopped -p 0.0.0.0:8080:8080 -p 0.0.0.0:8000:8000 -v knowledge_app:/data -v knowledge_qdrant:/qdrant/storage --mount type=bind,src=/mnt/knowledge,dst=/mnt/knowledge,readonly paoloronco/knowledge-mcp:latest
```

On Windows, use a host path such as `C:/Users/Name/Documents` on the left of the mount and `/mnt/knowledge` on the right. Changing the dashboard setting cannot create a Docker mount; recreate the container with the mount if the path is not visible. Existing source selection is saved across restarts. If you already have a separate Qdrant container, its index is **not** imported automatically. Keep that container and its storage until you have planned a migration.

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
