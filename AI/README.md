# AI clients

The MCP endpoint is http://127.0.0.1:8000/mcp by default. Remote clients need an authenticated HTTPS route to it. The server itself does not implement OAuth or enforce access tokens.

- [Cloudflare Access and MCP portal](../knowledge-mcp/security/cloudflare/README.md)
- [ChatGPT](public-ai-clients/chatgpt.md)
- [Claude](public-ai-clients/claude.md)
- [Google ADK example](googlecloud-adk-agent/README.md)

The two server tools are knowledge_status() and search_private_knowledge(query). A client should normally make one comprehensive search per question and use a second only when the first misses essential evidence.
