# Docker deployment notes

The one-command Compose setup and host agent setup are in the [root README](../README.md). The image starts its own Qdrant process and stores its data at `/qdrant/storage`. Settings, ingestion state, the model cache, synchronized host documents, and any documents from older versions are under `/data`. Both paths need persistent Docker volumes.

## Switching an existing `docker run` installation to Compose

The earlier `docker run` example used volumes named `knowledge_app` and `knowledge_qdrant`. To reuse them, create `compose.override.yaml` beside `compose.yaml`:

```yaml
volumes:
  app_data:
    external: true
    name: knowledge_app
  qdrant_data:
    external: true
    name: knowledge_qdrant
```

Stop and remove the old container, then start Compose:

```bash
docker stop -t 30 knowledge-mcp
docker rm knowledge-mcp
docker compose up -d
```

Keep those volumes; removing them loses the dashboard settings, indexing state, synchronized documents, and Qdrant data. If the old container had a read-only document mount, add that mount to the same override file before starting Compose.

## Select a host folder without changing Docker

The host agent runs outside the container under your host user account. Pair it once from the dashboard; then enter an absolute host path, such as `/mnt/knowledge` or `C:\Users\Name\Documents`, in **Folder on the Docker host** mode. The agent polls the dashboard, applies the indexing policy before transfer, and copies only changed eligible documents. It checks for additions and deletions every five minutes. The dashboard blocks indexing until the selected folder has synchronized and the agent is connected. Scheduled indexing then uses the existing incremental hash state, so unchanged documents are not embedded again.

The agent stores its pairing key in `~/.config/knowledge-mcp/agent.json` and logs to `~/.config/knowledge-mcp/agent.log`. On Linux, `install` creates a systemd user service and tries to enable lingering so it starts at boot; if it cannot, it prints the one-time `sudo loginctl enable-linger USER` command. Use `systemctl --user status knowledge-mcp-agent.service` to check it. On Windows, `install` creates a scheduled task that starts at sign-in. The host user must have read access to the chosen folder. To rotate the key, generate another in the dashboard and run `install` again. Treat the app volume as private: it contains a copy of eligible host documents.

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

Replace `source` with an existing absolute host path, then run `docker compose up -d`. Choose **Folder already mounted inside the container** and enter `/knowledge` as the document root; you can select the whole mount or several subfolders within it. On Windows, use a host source such as `C:/Users/Name/Documents`. A bind mount still requires a container recreation when changed.

To select folders from different host locations, mount each one under a separate subdirectory of the same container root (for example `/knowledge/team-a` and `/knowledge/team-b`), then select `/knowledge` as the document root in the dashboard.

The dashboard health check is also available at `/api/health` on port 8080 and returns an error while Qdrant is unavailable. The image uses it for its Docker health status. Scheduled indexing rescans selected folders and skips parsing and embedding files already recorded unchanged in the persistent ingestion state.

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
