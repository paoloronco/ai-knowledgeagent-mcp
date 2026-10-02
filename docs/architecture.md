# Architecture

~~~text
Documents (local directory or read-only SMB mount)
    -> ingestion/ingest.py -> dense Qdrant collection
                                |          |
                       dense query      payload scroll
                                |          |
                         mcp/retrieval.py (ranking, policy, redaction)
                                -> mcp/server.py -> MCP client
~~~

Ingestion parses supported files, hashes each file, chunks its text, embeds chunks with multilingual-e5-small and upserts them into one dense Qdrant collection. The state file records indexed SHA-256 hashes and sources. A successful complete run removes documents no longer present; --limit processes a sample and does not purge missing documents.

At first search, retrieval loads Qdrant payloads into process memory for lexical scoring, entity matching and context expansion. Dense candidates come from Qdrant. Reciprocal rank fusion combines both lists before metadata ranking and diversification. Restart the server after indexing; the in-memory payload copy is not refreshed automatically.

The MCP server is read-only with respect to source documents. Ingestion writes to Qdrant and its local state directory. Neither component provisions Cloudflare, mounts SMB, or enforces HTTP authentication. Those controls belong to the deployment.
