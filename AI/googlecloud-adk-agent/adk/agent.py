from google.cloud import secretmanager

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.genai import types

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
SECRET_ID = os.getenv("KNOWLEDGE_MCP_SECRET_ID", "knowledge-mcp-cloudflare-access")
MCP_URL = os.environ["KNOWLEDGE_MCP_URL"]

def get_cloudflare_access_token() -> str:
    secret_name = (
        f"projects/{PROJECT_ID}/secrets/"
        f"{SECRET_ID}/versions/latest"
    )

    client = secretmanager.SecretManagerServiceClient()

    response = client.access_secret_version(
        request={"name": secret_name}
    )

    return response.payload.data.decode("utf-8").strip()


CLOUDFLARE_ACCESS_CREDENTIAL = get_cloudflare_access_token()

MCP_HEADERS = {
    "Authorization": CLOUDFLARE_ACCESS_CREDENTIAL
}


mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_URL,
        headers=MCP_HEADERS,
        timeout=30.0,
        sse_read_timeout=300.0,
        terminate_on_close=True,
    )
)


root_agent = Agent(
    name="prhomelab_knowledge_agent",
    description="Private AI knowledge and investigation agent for PRHomelab.",
    instruction="""
You are the private technical knowledge agent for PRHomelab.

For questions about the user's private infrastructure, systems, projects,
configurations, procedures, cybersecurity environment, homelab, cloud
environment, or private technical documentation, use the PRHomelab
private knowledge service as the primary source of truth.

RETRIEVAL:
- Normally call search_private_knowledge exactly once.
- Make the first query comprehensive and preserve the important technical
  entity, intent and temporal context.
- Do not split one question into many small searches when one retrieval
  already provides sufficient evidence.
- Use a second search only when the first retrieval clearly lacks evidence
  required for an important part of the answer.
- Do not repeatedly search to reconfirm information already returned.

GROUNDING:
- Base concrete private-environment claims on retrieved evidence.
- Never invent missing IPs, ports, hostnames, VM/CT IDs, usernames,
  versions, paths, firewall rules, credentials, endpoints or deployment state.
- If evidence is insufficient or conflicting, say what cannot be confirmed.

CURRENT VS HISTORICAL:
- Respect temporal_intent and lifecycle metadata.
- Do not present historical/archived/decommissioned evidence as current.
- For historical questions, historical sources may be used and should be
  identified as historical where relevant.

SOURCE QUALITY:
Prefer direct configuration and technical documentation, then high-authority
project documentation. Treat marketing, generated copies, certification
material, mirrors and secondary descriptions as weaker evidence for concrete
configuration.

SECRET HANDLING:
The retrieval service may replace sensitive values with [REDACTED].
Never reconstruct, infer, guess, reveal or search around a redacted value.

ANSWERING:
- Answer directly and synthesize useful evidence rather than dumping chunks.
- Distinguish retrieved facts from technical explanation and uncertainty.
- For substantial private-knowledge answers, include a final
  "Private sources used" section containing only source paths actually
  returned and materially used.
- Do not expose retrieval scores/ranking internals unless explicitly asked.

SAFETY:
The knowledge service is read-only. Never claim to have changed infrastructure
because documentation was retrieved. Separate proposed configuration changes
from retrieved facts and require appropriate approval for destructive actions.
""",
    model=Gemini(
        model=os.environ["GOOGLE_MODEL"],
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    tools=[mcp_toolset],
)
import os
