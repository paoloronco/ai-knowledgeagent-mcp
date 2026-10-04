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

### NVIDIA GPU

On a Linux Docker host with an NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), use the `:cuda` image for the **app container** and add `--gpus all` to its `docker run` command:

```bash
docker pull paoloronco/knowledge-mcp:cuda
docker run -d --name knowledge-mcp --restart unless-stopped --gpus all \
  -p 8080:8080 -p 8000:8000 \
  -e AUTO_HOST_AGENT_CONFIG=/run/host-agent/agent.json \
  -v knowledge_app:/data \
  -v knowledge_qdrant:/qdrant/storage \
  -v knowledge_agent:/run/host-agent \
  paoloronco/knowledge-mcp:cuda
```

The host agent command above stays on `:latest` and needs no GPU. For Compose, run `docker compose -f compose.yaml -f compose.gpu.yaml up -d`. To switch an existing installation, recreate the containers while keeping the same named volumes as described in [deployment notes](docs/docker.md); your indexing and settings remain in those volumes. Verify host GPU access with `docker run --rm --gpus all ubuntu nvidia-smi`. The dashboard shows the detected device, driver, free/total VRAM, CUDA availability, and whether embeddings use GPU or CPU. The CUDA image also runs on CPU if Docker exposes no GPU; set `EMBEDDING_DEVICE=cpu` to force CPU or `EMBEDDING_DEVICE=cuda` to fail fast when CUDA is unavailable.

The companion reads the selected Linux folder through a read-only host mount, applies the indexing policy, and synchronizes eligible documents into the app volume. It exposes no port and needs no Docker socket. Select a folder such as `/mnt/documents` in the Web UI; dashboard login is optional. See [deployment and migration notes](docs/docker.md) for updates and the alternative Compose setup.

The exact bare command `docker run paoloronco/knowledge-mcp` starts only an isolated foreground container. An image cannot set the host's published ports, mounts, or restart policy; Docker requires those options at container creation. See Docker's [port publication](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/) and [restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/) documentation.

## Dashboard

Once the application has been deployed with networking and document access configured:

- Open `http://HOST_IP:8080`.
- Onboarding guides you through optional dashboard login, service checks, document folder selection, the [indexing policy](knowledge-mcp/mcp/index-policy.yaml), a manual document scan, a dry-run test, and initial indexing. Each step has its own URL under `/setup/` (for example, `/setup/folders` and `/setup/eligible`), so you can reload or bookmark the current step. If you skip login, anyone who can reach port 8080 can manage the dashboard.
- Enter a folder path such as `/mnt/documents` and click **+**. The app checks access before adding it to the list; you can add or remove multiple folders that share a non-root parent. With the host agent connected, paths refer to folders on the Linux host.
- After saving the policy, press **Scan** to view the eligible count and a preview. **View all eligible documents** opens the full list and offers TXT, LOG, and JSON downloads. The dry run starts only after the scan finds eligible documents.
- In **Initial indexing**, choose an embedding model for your hardware and document mix. The same selection is available later at `/dashboard/indexing`. E5 small is the CPU-friendly default; E5 base needs more resources; BGE-M3 is the heaviest option. The cards show vector dimensions and qualitative resource guidance, not benchmark guarantees. The `:latest` image uses CPU and the `:cuda` image uses an exposed NVIDIA GPU automatically; each model downloads on first indexing and is cached in the persistent app volume.
- Initial indexing opens the dedicated indexing page with live stage, document count, percentage where available, and the log. While it runs, **Go to dashboard** lets you use the other pages; `/dashboard` also shows the current stage and progress, and **Open indexing details** returns to the full log. You can also select **Skip for now** to open `/dashboard` and start initial indexing later from `/dashboard/indexing`. The dashboard sections have separate `/dashboard/…` URLs.
- The Indexing page offers downloads for the complete output log and a timestamped status log. Document errors show their source path and reason. Fix the source or choose **Ignore this file** to add its relative path to the indexing policy, then use **Retry incremental update**; unchanged documents are skipped. Older runs still expose their full log and recent entries from the existing error log, while the status log starts with the next run.
- Changing models keeps the searchable index on the previous model until the new indexing run succeeds. Each choice has its own Qdrant collection and ingestion state. Returning to a previously indexed model updates its existing index; retaining multiple models uses additional disk space. The dry run checks parsing only and does not download or evaluate a model. BGE-M3 uses dense vectors in this app, with the same short document chunks as the other profiles.
- After initial indexing completes, start the MCP server from the dashboard. The endpoint is available at `http://HOST_IP:8000/mcp`. Add an authenticated proxy or Cloudflare Access before exposing it beyond a trusted LAN.
- The main `/dashboard` page shows service health and Qdrant/MCP controls. Document folder sync status and scheduling live under `/dashboard/folders`; use `/dashboard/indexing` for indexing progress and updates.
- Persistent Docker volumes retain documents, settings, indexing state, the model cache, Qdrant data, and the agent connection across container updates.

Model specifications: [multilingual E5 small](https://huggingface.co/intfloat/multilingual-e5-small), [multilingual E5 base](https://huggingface.co/intfloat/multilingual-e5-base), and [BGE-M3](https://huggingface.co/BAAI/bge-m3). Compare relevance on your own queries and documents before settling on a model.

## More information

- [Docker deployment and migration notes](docs/docker.md)
- [Service and manual Python setup](knowledge-mcp/README.md)
- [Architecture, security, and troubleshooting](docs/README.md)
- [AI client examples](AI/README.md)

This repository contains no private documents, credentials, or Qdrant data. It does not yet have a LICENSE file.
