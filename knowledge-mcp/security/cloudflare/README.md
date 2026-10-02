# Cloudflare access

Cloudflare Tunnel can route HTTPS traffic to the local MCP server. Cloudflare Access can protect the hostname; an MCP server portal can aggregate this server for clients that support the portal's authentication flow. This repository does not create the tunnel, Access policy, OAuth configuration, or portal.

1. Run and test the MCP server locally at http://127.0.0.1:8000/mcp with an MCP client.
2. Create a Cloudflare Tunnel and route a hostname to the local service. Keep the origin bound to localhost when cloudflared runs on the same host.
3. Create an Access application and policy for the origin. Verify unauthenticated requests are denied.
4. If needed, add the protected origin as an upstream server in an MCP server portal, create a portal Access policy, and use the portal URL in ChatGPT or Claude.
5. Test tool discovery and knowledge_status through the final URL using the same authentication flow as the intended client.

For machine access, Cloudflare service tokens normally use CF-Access-Client-Id and CF-Access-Client-Secret headers. A deployment that intentionally uses an Authorization-header credential must configure that behavior in Access and in the client. Never commit either value.

Cloudflare's [MCP server portal guide](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/mcp-portal/) is the source for current portal steps and authentication options. The [Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) covers origin routing. Do not assume wildcard redirect URIs or a bare Bearer token will work for a portal.
