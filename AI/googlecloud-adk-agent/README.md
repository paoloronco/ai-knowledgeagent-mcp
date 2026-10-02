# Google ADK example

[adk/agent.py](adk/agent.py) is an optional client of the Knowledge MCP server. It retrieves a Cloudflare Access credential from Google Secret Manager and supplies it to the MCP connection. It is not required for the server or ingestion.

Set GOOGLE_CLOUD_PROJECT, KNOWLEDGE_MCP_URL, and optionally KNOWLEDGE_MCP_SECRET_ID in the runtime environment. The default secret name is knowledge-mcp-cloudflare-access. The example expects the secret value to be the exact Authorization header value configured in Cloudflare Access. Grant secretAccessor only on that secret to the runtime identity.

Install [adk/requirements.txt](adk/requirements.txt) in the agent runtime. Test with a protected MCP endpoint and a separate Secret Manager project before deployment. The example has not been validated against a live Google ADK runtime in this repository review; APIs and model names should be checked against the version you deploy.

The [server security model](../../docs/security-model.md) still applies: returned excerpts are visible to the agent. Do not give the agent credentials it does not need.
