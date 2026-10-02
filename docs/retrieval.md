# Retrieval behavior

The active implementation is [retrieval.py](../knowledge-mcp/mcp/retrieval.py).

1. Detect current or historical intent and configuration or project intent using query hints.
2. Extract up to two known-entity or rare-term anchors from the loaded corpus.
3. Score eligible payloads lexically and request dense candidates from Qdrant.
4. Fuse ranks with reciprocal rank fusion (k=60), then apply source authority, type and entity affinity multipliers.
5. Keep one result per source family, with a maximum of eight results.
6. For at most two eligible configuration results, expand to the small document or nearby chunks.
7. Redact common credential patterns in returned result fields.

Default dense and lexical candidate limits are 60 each. Lexical scoring uses substring counts; it is not BM25 and the service does not query a sparse collection. Path and intent rules are heuristics: they can miss relevant material or misclassify a source. Historical paths are excluded unless the query contains a historical hint; restricted paths are always excluded.

The corpus is loaded once per server process. A restart after ingestion is required to expose new and removed files consistently in lexical search and expansion.
