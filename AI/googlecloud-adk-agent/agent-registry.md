# Agent Registry

Agent Registry is optional metadata for a Google ADK deployment. The active agent in adk/agent.py connects directly to KNOWLEDGE_MCP_URL; registration is not part of the MCP server setup.

The server advertises knowledge_status with no arguments and search_private_knowledge with one required string argument, query. Discover tool schemas from the running MCP endpoint rather than maintaining a second manual JSON toolspec in this repository.
