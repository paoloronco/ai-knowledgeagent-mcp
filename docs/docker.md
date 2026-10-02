# Docker deployment notes

The standard `docker run` command is in the [root README](../README.md). The image starts its own Qdrant process and stores its data at `/qdrant/storage`. Browser uploads, settings, ingestion state, and the model cache are under `/data`. Both paths need persistent Docker volumes.

## Compose with an existing document folder

Create `compose.override.yaml` beside `compose.yaml`:

```yaml
services:
  app:
    environment:
      KNOWLEDGE_ROOT: /knowledge
    volumes:
      - type: bind
        source: /absolute/path/to/documents
        target: /knowledge
        read_only: true
        bind:
          create_host_path: false
```

Replace `source` with an existing absolute host path, then run `docker compose up -d`. The Web UI can select a subfolder within the mount. Browser uploads are disabled in this mode. On Windows, use a path such as `C:/Users/Name/Documents`.

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
