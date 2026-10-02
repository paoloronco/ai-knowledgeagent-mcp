# Knowledge MCP service

The active code is [mcp/server.py](mcp/server.py), [mcp/retrieval.py](mcp/retrieval.py), and [ingestion/ingest.py](ingestion/ingest.py). The Docker control UI lives in [mcp/webui.py](mcp/webui.py). Install the packages in [requirements.txt](requirements.txt), configure [.env.example](.env.example) as .env, and review [index-policy.yaml](mcp/index-policy.yaml).

Run ingestion before starting the server:

~~~bash
python ingestion/ingest.py --dry-run --limit 10
python ingestion/ingest.py
python mcp/server.py
~~~

Both scripts load .env from this directory. The server serves Streamable HTTP at /mcp. See the [root README](../README.md) for prerequisites and [deployment guide](mcp/deployment/README.md) for a Linux service example.
