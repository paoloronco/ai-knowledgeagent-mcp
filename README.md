# Knowledge MCP

![Currently under development](https://img.shields.io/badge/status-Currently%20under%20development-orange)

Search your documents through an MCP server. The Docker image includes the dashboard, ingestion service, MCP server, and Qdrant. Use the dashboard to select a document root, configure indexing, schedule updates, and manage services.

## Docker image

Download the image, then start the complete application on a Linux Docker host:

```bash
docker pull paoloronco/knowledge-mcp
docker run -d --name knowledge-mcp --restart unless-stopped \
  -p 8080:8080 -p 8000:8000 \
  -e AUTO_HOST_AGENT_CONFIG=/run/host-agent/agent.json \
  -v knowledge_app:/data \
  -v knowledge_qdrant:/qdrant/storage \
  -v knowledge_agent:/run/host-agent \
  paoloronco/knowledge-mcp
```

Open `http://HOST_IP:8080` for the Web UI. Qdrant stays on container loopback; port 8000 serves MCP after onboarding and indexing. The named volumes preserve settings, documents, model cache, and Qdrant data. Docker restarts the container after a process failure or host reboot; the app also restarts a failed Qdrant or enabled MCP child process. Review the [indexing policy](knowledge-mcp/mcp/index-policy.yaml) before indexing.

To let the Web UI select folders on the Linux host, install its companion container with this **one command on the same host**:

```bash
docker run -d --name knowledge-mcp-host-agent --restart unless-stopped \
  --network container:knowledge-mcp --read-only \
  --cap-drop ALL --cap-add DAC_READ_SEARCH \
  --security-opt no-new-privileges \
  -v knowledge_agent:/run/host-agent:ro \
  -v /:/host:ro \
  --tmpfs /host/proc:ro,noexec,nosuid,size=1m \
  --tmpfs /host/sys:ro,noexec,nosuid,size=1m \
  --tmpfs /host/dev:ro,noexec,nosuid,size=1m \
  --tmpfs /host/run:ro,noexec,nosuid,size=1m \
  paoloronco/knowledge-mcp \
  python host_agent.py run --config /run/host-agent/agent.json --host-root /host --log-stdout
```

The companion reads the selected Linux folder through a read-only host mount, applies the indexing policy, and synchronizes eligible documents into the app volume. It exposes no port and needs no Docker socket. Select a folder such as `/mnt/documents` in the Web UI after enabling login. See [deployment and migration notes](docs/docker.md) for updates and the alternative Compose setup.

The exact bare command `docker run paoloronco/knowledge-mcp` starts only an isolated foreground container. An image cannot set the host's published ports, mounts, or restart policy; Docker requires those options at container creation. See Docker's [port publication](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/) and [restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/) documentation.

## Dashboard

Once the application has been deployed with networking and document access configured:

- Open `http://HOST_IP:8080`.
- Onboarding guides you through dashboard login, service checks, document root selection, the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), a dry-run test, and initial indexing.
- Enter a **Document root path**, such as `/mnt/documents`, and click **+**. With the automatic host agent connected, the path refers to a folder on the Linux host.
- After initial indexing completes, start the MCP server from the dashboard. The endpoint is available at `http://HOST_IP:8000/mcp`. Add an authenticated proxy or Cloudflare Access before exposing it beyond a trusted LAN.
- Use the dashboard to manage services and schedule incremental indexing.
- Persistent Docker volumes retain documents, settings, indexing state, the model cache, Qdrant data, and the agent connection across container updates.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
