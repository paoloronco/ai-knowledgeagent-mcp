# Knowledge MCP

![Currently under development](https://img.shields.io/badge/status-Currently%20under%20development-orange)

Search your documents through an MCP server. The Docker image contains the Web UI, ingestion service, MCP server, and Qdrant. A small host agent lets the dashboard select any document folder on the Docker host without changing Docker mounts. The dashboard also supports existing read-only bind mounts. Review the policy, run indexing, schedule updates, and enable or disable MCP. There is no browser document upload.

## Docker quick start

With a recent Docker Compose, start the application from any directory with one command:

```bash
docker compose -f https://github.com/paoloronco/ai-knowledgeagent-mcp.git up -d
```

The same command starts it again later. If your Compose version cannot read a Git repository, clone this repository once and run `docker compose up -d` in its directory. [compose.yaml](compose.yaml) supplies the image, container name, restart policy, ports 8080 and 8000, and persistent volumes. Docker downloads the image on the first start. `docker run -d knowledge-mcp` cannot provide these settings: image `EXPOSE` does not publish fixed host ports, and restart and named volume options belong to the container configuration.

Open `http://HOST_IP:8080` from a device on the same LAN. Enable dashboard login for host folder access. On the Docker **host**, install Python 3.10+ and run this one-time setup from a repository clone:

```bash
git clone https://github.com/paoloronco/ai-knowledgeagent-mcp.git
cd ai-knowledgeagent-mcp
python knowledge-mcp/host_agent.py install --url http://127.0.0.1:8080
```

In the dashboard, choose **Folder on the Docker host**, generate a pairing key, and paste it into the agent's setup prompt. Enter the host path, for example `/mnt/knowledge`, and save it. The agent runs under your host user, reads that folder, and synchronizes eligible files into the persistent application volume. Changing the dashboard path later requires no Docker change. Wait until the dashboard reports **Host documents synchronized**, then choose subfolders, review the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), run the ten-document test, and start indexing. The MCP endpoint is `http://HOST_IP:8000/mcp` when enabled; it is for MCP clients, not a browser page.

The bundled directory exclusions are mandatory, including `coverage`, `cache`, `.cache`, `vendor`, `.stversions`, `sample-folder`, `sample-folder`, `sample-folder`, and `sample-folder`. Older saved policies gain any missing exclusions at startup. After upgrading an existing index, run **Run incremental update** to remove previously indexed documents from those folders, then restart MCP. If no eligible documents remain, use `python ingestion/ingest.py --allow-empty` from `knowledge-mcp` to intentionally clear the index.

The two named volumes keep settings, indexing state, model cache, Qdrant data, synchronized host documents, and any documents uploaded by older versions. Do not remove them if you want to keep the index. Qdrant listens only inside the container and is not published to the host.

Ports 8080 and 8000 are published on all Docker host interfaces. The Web UI has an optional password; the MCP server still has no built-in login. Restrict access to a trusted LAN with a firewall, and add an authenticated proxy before exposing either port to the Internet. Use HTTPS when entering the dashboard password over a network.

### Update or stop

To update the image while keeping settings, documents, and the Qdrant index, run `docker compose -f https://github.com/paoloronco/ai-knowledgeagent-mcp.git pull` followed by the quick-start command above. To stop it, use the same `-f` URL with `stop`. With a local clone, omit `-f` and the URL.

### Existing read-only bind mounts

If you already mount a host folder into the container, choose **Folder already mounted inside the container** in the dashboard and enter its container path. The optional [Compose override](docs/docker.md#compose-with-an-existing-document-folder) defines the read-only mount. Bind mounts still require a container recreation when changed; the host agent above avoids that. Existing source selection is saved across restarts.

If you previously installed with `docker run`, keep its `knowledge_app` and `knowledge_qdrant` volumes. Compose uses project-scoped volume names, so switching commands does not automatically reuse those volumes. See the [migration notes](docs/docker.md) before switching an existing installation. A separately started Qdrant container is also **not** imported automatically.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
