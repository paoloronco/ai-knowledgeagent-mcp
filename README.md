# Knowledge MCP

![Currently under development](https://img.shields.io/badge/status-Currently%20under%20development-orange)

Search your documents through an MCP server. The Docker image includes the dashboard, ingestion service, MCP server, and Qdrant. Use the dashboard to select a document root, configure indexing, schedule updates, and manage services.

## Docker image

Download the image, then start the complete application on a Linux Docker host:

```bash
docker pull paoloronco/knowledge-mcp:latest
docker run -d --name knowledge-mcp --restart unless-stopped \
  -p 8080:8080 -p 8000:8000 \
  -e AUTO_HOST_AGENT_CONFIG=/run/host-agent/agent.json \
  -v knowledge_app:/data \
  -v knowledge_qdrant:/qdrant/storage \
  -v knowledge_agent:/run/host-agent \
  paoloronco/knowledge-mcp:latest
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
  paoloronco/knowledge-mcp:latest \
  python host_agent.py run --config /run/host-agent/agent.json --host-root /host --log-stdout
```

Both containers use `paoloronco/knowledge-mcp:latest`, but have separate names and roles: `knowledge-mcp` runs the Web UI, MCP, and Qdrant; `knowledge-mcp-host-agent` runs `host_agent.py`, reads the Linux host through `/host`, and shares the app container's network. The [Compose deployment](docs/docker.md#linuxnas-deployment) uses the same names and roles.

The companion reads the selected Linux folder through a read-only host mount, applies the indexing policy, and synchronizes eligible documents into the app volume. It exposes no port and needs no Docker socket. Select a folder such as `/mnt/documents` in the Web UI; dashboard login is optional. See [deployment and migration notes](docs/docker.md) for updates and the alternative Compose setup.

The exact bare command `docker run paoloronco/knowledge-mcp` starts only an isolated foreground container. An image cannot set the host's published ports, mounts, or restart policy; Docker requires those options at container creation. See Docker's [port publication](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/) and [restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/) documentation.

## Dashboard

Once the application has been deployed with networking and document access configured:

- Open `http://HOST_IP:8080`.
- Onboarding guides you through optional dashboard login, service checks, document folder selection, the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), a manual document scan, a dry-run test, and initial indexing. If you skip login, anyone who can reach port 8080 can manage the dashboard.
- Enter a folder path such as `/mnt/documents` and click **+**. The app checks access before adding it to the list; you can add or remove multiple folders that share a non-root parent. With the host agent connected, paths refer to folders on the Linux host.
- After saving the policy, press **Scan** to view the eligible count and a preview. **View all eligible documents** opens the full list and offers TXT, LOG, and JSON downloads. The dry run starts only after the scan finds eligible documents.
- Initial indexing opens the dedicated indexing page with live stage, document count, percentage where available, and the log. Once it finishes, the other dashboard sections are available at separate `/dashboard/…` URLs.
- After initial indexing completes, start the MCP server from the dashboard. The endpoint is available at `http://HOST_IP:8000/mcp`. Add an authenticated proxy or Cloudflare Access before exposing it beyond a trusted LAN.
- Use the dashboard to manage services and schedule incremental indexing.
- Persistent Docker volumes retain documents, settings, indexing state, the model cache, Qdrant data, and the agent connection across container updates.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
