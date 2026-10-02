# ADK client setup

This directory contains an example agent and its requirements. Install the packages in requirements.txt in a virtual environment or managed runtime.

Provide these environment variables:

~~~text
GOOGLE_CLOUD_PROJECT=your-project-id
KNOWLEDGE_MCP_URL=https://your-protected-hostname.example.com/mcp
KNOWLEDGE_MCP_SECRET_ID=knowledge-mcp-cloudflare-access
GOOGLE_MODEL=your-available-gemini-model
~~~

Create the named Secret Manager secret with the exact value expected by the Cloudflare Access Authorization header and grant the runtime identity access to that secret only. The agent reads the secret at import time, so missing credentials or environment variables fail immediately.

The code is an example integration, not an automated deployment recipe. Validate the installed Google ADK API and model availability in your target runtime before deploying.
