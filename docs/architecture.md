# Architecture

~~~text
Documents (read-only host mount or legacy document volume)
    -> ingestion/ingest.py -> dense Qdrant collection
                                |          |
                       dense query      payload scroll
                                |          |
                         mcp/retrieval.py (ranking, policy, redaction)
                                -> mcp/server.py -> MCP client
~~~

Ingestion parses supported files, hashes each file, chunks its text, embeds chunks with multilingual-e5-small and upserts them into one dense Qdrant collection. The state file records indexed SHA-256 hashes and sources. A successful complete run removes documents no longer present; --limit processes a sample and does not purge missing documents. An empty source is rejected unless `--allow-empty` is specified explicitly.

The dashboard saves a document root and selects the entire folder. It passes the container-visible root to ingestion as `KNOWLEDGE_ROOT` and selects the full root with `INDEX_SOURCE_PATHS=[""]`. Legacy subfolder selections remain stored until the user saves the document root again. Scheduled runs use the same scan and skip parsing and embedding documents whose hashes and source paths have not changed. The dashboard supervises bundled Qdrant and the MCP process. An externally managed Qdrant instance must be controlled outside the dashboard.

At first search, retrieval loads Qdrant payloads into process memory for lexical scoring, entity matching and context expansion. Dense candidates come from Qdrant. Reciprocal rank fusion combines both lists before metadata ranking and diversification. Restart the server after indexing; the in-memory payload copy is not refreshed automatically.

The MCP server is read-only with respect to source documents. Ingestion writes to Qdrant and its local state directory. Neither component provisions Cloudflare, mounts SMB, or enforces HTTP authentication. Those controls belong to the deployment.
