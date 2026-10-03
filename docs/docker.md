# Docker deployment notes

The image starts the Web UI and bundled Qdrant. Docker must configure port publication, persistent storage, and host folder access when creating containers. The [root README](../README.md#docker-image) gives complete `docker run` commands for the app and a separate Linux host agent. A bare `docker run paoloronco/knowledge-mcp` does not supply those settings.

## Linux/NAS deployment

Alternatively, the repository's [compose.yaml](../compose.yaml) configures the app and automatic host agent together, publishes ports 8080 and 8000, and retains data in Docker volumes. From a local repository checkout:

Compose creates two distinct containers from `paoloronco/knowledge-mcp:latest`: `knowledge-mcp` for the Web UI, MCP, and Qdrant, and `knowledge-mcp-host-agent` for `host_agent.py`. The host agent mounts the Linux host at `/host` read-only and shares the app container's network.

```bash
docker compose up -d
```

The app stores Qdrant data at `/qdrant/storage`. Settings, ingestion state, the model cache, and synchronized documents are under `/data`. A third volume retains the agent connection. To update, run `docker compose pull` followed by `docker compose up -d`. To stop the services, run `docker compose stop`.

For the README's `docker run` installation, update by stopping and removing the host agent first, then the app container; pull the new image and repeat both README commands. Keep the three named volumes. Recreate the agent whenever you recreate the app container because it joins the app container's network namespace.

## Switching an existing `docker run` installation to Compose

The README's `docker run` commands use volumes named `knowledge_app`, `knowledge_qdrant`, and `knowledge_agent`. To reuse them in Compose, create `compose.override.yaml` beside `compose.yaml`:

```yaml
volumes:
  app_data:
    external: true
    name: knowledge_app
  qdrant_data:
    external: true
    name: knowledge_qdrant
  host_agent_data:
    external: true
    name: knowledge_agent
```

Stop and remove the old containers, then start Compose:

```bash
docker stop -t 30 knowledge-mcp-host-agent
docker rm knowledge-mcp-host-agent
docker stop -t 30 knowledge-mcp
docker rm knowledge-mcp
docker compose up -d
```

Keep those volumes; removing them loses the dashboard settings, indexing state, synchronized documents, and Qdrant data. If the old container had a read-only document mount, add that mount to the same override file before starting Compose.

## Select a host folder without changing Docker

With the standard Compose setup on Linux/NAS:

1. Open the dashboard. Login is optional during onboarding.
2. In **Document folders**, enter any absolute **Document root path**, such as `/mnt/documents`, `/mnt/knowledge`, or `/home/user/Documents`, and click **+**.
3. Wait for **Folder ready**, then continue with **Next**.

Compose starts the host agent automatically and the app provides its connection credentials through a private Docker volume. Python, native host services, downloads, and manual pairing are not required. With **Automatic** document location, the root is interpreted on the Linux host. To use an existing app-container mount instead, explicitly select **Folder already mounted inside the container**.

The agent receives the Linux host filesystem at `/host` through a [read-only bind mount](https://docs.docker.com/engine/storage/bind-mounts/#use-a-read-only-bind-mount). It reads only the selected root, applies the indexing policy before transfer, and copies changed eligible documents into the app's persistent storage. Host symlinks are resolved within the host filesystem and restricted directories remain excluded. `/proc`, `/sys`, `/dev`, and `/run` are masked. The agent has no Docker socket and publishes no ports.

Changing the root from the dashboard requires no Docker configuration changes or container restart. The source stays at the chosen host path; indexing uses the synchronized copy. Mount external drives and network shares on the NAS before starting the stack so they are included in the agent's host mount. On kernels before Linux 5.12, Docker may retain write access on nested mounts despite a read-only parent mount; use Linux 5.12+ for recursive read-only protection.

The status under the path shows connection errors, files checked during scanning, transfer progress, and the eligible document count. **Next** waits for the sync already triggered by selecting the folder, then verifies it before continuing. The agent rescans every five minutes, responds to source changes and **Sync folder now**, and pauses synchronization while indexing runs. Scheduled indexing uses the existing incremental hash state, so unchanged documents are not embedded again.

Check the agent with `docker compose logs host-agent`. To restart it, use `docker compose restart host-agent`. The connection credentials are retained in `host_agent_data`, and the app stores only their hash in `app_data`. A Compose upgrade starts the agent without requiring user installation. Keep the existing app and Qdrant volumes during migration.

This automatic setup targets Docker Engine on Linux/NAS. Docker Desktop on Windows or macOS requires separate native filesystem sharing and is not covered by mounting the Linux root. The README's two-container `docker run` setup provides the same Linux host access without a repository checkout.

## Compose with an existing document folder

This is an optional alternative to the host agent. Create `compose.override.yaml` beside `compose.yaml`:

```yaml
services:
  app:
    volumes:
      - type: bind
        source: /absolute/path/to/documents
        target: /knowledge
        read_only: true
        bind:
          create_host_path: false
```

Replace `source` with an existing absolute host path, then run `docker compose up -d`. Open **Document access settings**, choose **Folder already mounted inside the container**, and enter `/knowledge` as the **Document root path**. Click **+**, or **Next** during onboarding, to save the entire root. On Windows, use a host source such as `C:/Users/Name/Documents`. A bind mount still requires a container recreation when changed.

To select folders from different host locations, mount each one under a separate subdirectory of the same container root (for example `/knowledge/team-a` and `/knowledge/team-b`), then select `/knowledge` as the document root in the dashboard.

The dashboard health check is also available at `/api/health` on port 8080 and returns an error while Qdrant is unavailable. The image uses it for its Docker health status. Scheduled indexing rescans the document root and skips parsing and embedding files already recorded unchanged in the persistent ingestion state.

## Upgrade from the older two-container Compose stack

The earlier Compose file ran Qdrant as a separate service. The new image contains Qdrant and mounts the **same** `qdrant_data` volume at `/qdrant/storage`; the `app_data` volume is also reused when the Compose project name stays the same. Stop the old stack before updating the repository so the old and new Qdrant processes never write to the same volume at once:

```bash
docker compose down
git pull
docker compose pull
docker compose up -d
```

Do not add `-v` to `docker compose down`. If you previously used `KNOWLEDGE_HOST_PATH`, create the read-only mount override above with that same folder before running a full index. A full index removes documents absent from its selected source. If the repository directory or Compose project name changes, Docker may create new volumes instead of reusing the old ones; check volume names before indexing.

A separately started Qdrant container is not part of this Compose project and is not imported automatically. Keep its container, volume, and ingestion state until you have verified a migration.
