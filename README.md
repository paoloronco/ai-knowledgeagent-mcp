# Knowledge MCP

An MCP server for searching a private document collection. Ingestion parses local files, builds multilingual dense embeddings in Qdrant, and keeps source paths and page/section metadata. Search combines Qdrant dense retrieval with lexical scoring over a local copy of the indexed payloads. The server returns selected text to its MCP client after output redaction.

This repository is a portable version of a personal homelab project. It does not include the private documents, Qdrant data, credentials, or a running Cloudflare configuration.

There is currently no LICENSE file. Choose a license before making the repository public.

## Repository layout

- [knowledge-mcp/](knowledge-mcp/README.md): server, ingestion, dependencies and policy
- [docs/](docs/README.md): architecture, retrieval, security and troubleshooting
- [AI/](AI/README.md): Cloudflare, ChatGPT, Claude and Google ADK notes

## Quick start

Use Python 3.10+ and a local Qdrant instance listening on 127.0.0.1:6333. From the repository root:

~~~bash
cd knowledge-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
~~~

Edit .env: set KNOWLEDGE_ROOT to an existing document directory. Review [index-policy.yaml](knowledge-mcp/mcp/index-policy.yaml) before indexing any private data. The default server bind address is localhost; configure an authenticated reverse proxy before making it reachable remotely.

~~~bash
python ingestion/ingest.py --dry-run --limit 10
python ingestion/ingest.py
python mcp/server.py
~~~

Run a complete ingestion without --limit when you want removed files purged from Qdrant. Restart the MCP server after ingestion so its in-memory lexical corpus reflects the new index. Connect an MCP Streamable HTTP client to http://127.0.0.1:8000/mcp and call knowledge_status or search_private_knowledge with a query string.

For a Linux service example, see [deployment](knowledge-mcp/mcp/deployment/README.md).

## What the server does

- Parses PDF, DOCX, PPTX, Markdown, HTML and text files.
- Deduplicates files by SHA-256 and updates Qdrant incrementally.
- Filters excluded paths and file types at ingestion, then applies restricted and historical path rules at retrieval.
- Returns up to eight diversified results per search; the dense and lexical candidate limits are 60 each.
- Redacts common credential patterns in returned text. This is a best-effort output filter, not a guarantee that private data cannot leave the server.

## Limits

Search loads the complete Qdrant payload corpus into memory on its first call; restart the server after each ingestion run. The lexical scorer is a substring-based heuristic, not a Qdrant sparse-vector index. Scanned PDFs without an extractable text layer are not OCRed. Keep the source mount read-only and review the index policy before making the MCP endpoint available to clients.

## Documentation

Start with [architecture](docs/architecture.md), [security](docs/security-model.md), and [retrieval](docs/retrieval.md). The service has no built-in authentication; the deployment must provide it.
