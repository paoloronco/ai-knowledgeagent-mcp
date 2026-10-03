# Knowledge MCP

![Currently under development](https://img.shields.io/badge/status-Currently%20under%20development-orange)

Search your documents through an MCP server. The Docker image includes the dashboard, ingestion service, MCP server, and Qdrant. Use the dashboard to select a document root, configure indexing, schedule updates, and manage services.

## Docker image

Download and start the image:

```bash
docker pull paoloronco/knowledge-mcp
docker run paoloronco/knowledge-mcp
```

These commands start the services inside the container in the foreground. They do **not** publish the dashboard or MCP ports or grant access to host folders. Docker requires these settings when creating the container; they cannot be supplied as image defaults. See Docker's [port publication](https://docs.docker.com/reference/dockerfile/#expose) and [host folder mounts](https://docs.docker.com/engine/storage/bind-mounts/) documentation.

For a deployment with dashboard access, persistent storage, and automatic Linux/NAS host folder access, see the [deployment guide](docs/docker.md). Keep existing data volumes when updating an installation.

## Dashboard

Once the application has been deployed with networking and document access configured:

- Open `http://HOST_IP:8080`.
- Onboarding guides you through dashboard login, service checks, document root selection, the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), a dry-run test, and initial indexing.
- Enter a **Document root path**, such as `/mnt/documents`, and click **+**. With the automatic host agent connected, the path refers to a folder on the Linux host.
- After initial indexing completes, start the MCP server from the dashboard. The endpoint is available at `http://HOST_IP:8000/mcp`.
- Use the dashboard to manage services and schedule incremental indexing.
- Persistent Docker volumes retain documents, settings, indexing state, the model cache, Qdrant data, and the agent connection across container updates.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
