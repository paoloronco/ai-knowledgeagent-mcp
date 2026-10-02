import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from retrieval import DENSE_COLLECTION, MODEL_NAME, client, search


mcp = MCPServer("PRHomelab Knowledge")

@mcp.tool()
def knowledge_status() -> dict:
    """Check Qdrant availability and the current collection size."""
    try:
        indexed_chunks = client.count(DENSE_COLLECTION, exact=True).count
        status = "ok"
    except Exception:
        indexed_chunks = None
        status = "unavailable"
    return {
        "status": status,
        "backend": "qdrant-hybrid",
        "retrieval": "anchor-aware dense + lexical hybrid",
        "dense_embedding_model": MODEL_NAME,
        "dense_collection": DENSE_COLLECTION,
        "indexed_chunks": indexed_chunks,
    }


@mcp.tool()
def search_private_knowledge(query: str) -> dict:
    """
    Search the private PRHomelab technical knowledge base.

    Returns relevant chunks together with their source document,
    page/slide when available, section metadata and retrieval score.
    """

    return search(query)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
    )
