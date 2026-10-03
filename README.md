# Knowledge MCP

![Currently under development](https://img.shields.io/badge/status-Currently%20under%20development-orange)

Search your documents through an MCP server. The Docker image includes the dashboard, ingestion service, MCP server, and Qdrant. Use the dashboard to select a document root, configure indexing, schedule updates, and manage services.

## Docker quick start

On Linux or a Linux NAS, start the application from any directory with a recent Docker Compose:

```bash
docker compose -f https://github.com/paoloronco/ai-knowledgeagent-mcp.git up -d
```

- Open `http://HOST_IP:8080`.
- Onboarding guides you through dashboard login, service checks, document root selection, the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), a dry-run test, and initial indexing.
- Enter any host document root path, such as `/mnt/documents`, and click **+**. Compose starts and connects the host agent automatically; no host software installation or manual pairing is required.
- After initial indexing completes, start the MCP server from the dashboard. The endpoint is available at `http://HOST_IP:8000/mcp`.
- Use the dashboard to manage services and schedule incremental indexing.
- Persistent Docker volumes retain documents, settings, indexing state, the model cache, Qdrant data, and the agent connection across container updates.

[compose.yaml](compose.yaml) provides the container name, restart policy, ports, volumes, and automatic host agent. The agent receives read-only access to the Linux host filesystem and reads the root selected in the dashboard. With a local repository clone, run `docker compose up -d`.

### Update or stop

To update the image while keeping settings, documents, and the Qdrant index, run `docker compose -f https://github.com/paoloronco/ai-knowledgeagent-mcp.git pull` followed by the quick-start command above. To stop it, use the same `-f` URL with `stop`. With a local clone, omit `-f` and the URL.

### Existing read-only bind mounts

If you already mount a host folder into the app container, choose **Folder already mounted inside the container** in the dashboard and enter its container path. The optional [Compose override](docs/docker.md#compose-with-an-existing-document-folder) defines that mount. Existing source selection is saved across restarts.

If you previously installed with `docker run`, keep its `knowledge_app` and `knowledge_qdrant` volumes. Compose uses project-scoped volume names, so switching commands does not automatically reuse those volumes. See the [migration notes](docs/docker.md) before switching an existing installation. A separately started Qdrant container is also **not** imported automatically.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
