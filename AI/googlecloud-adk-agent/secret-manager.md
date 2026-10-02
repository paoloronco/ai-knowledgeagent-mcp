# Secret Manager

The optional ADK example reads the secret named by KNOWLEDGE_MCP_SECRET_ID from GOOGLE_CLOUD_PROJECT. Its value is passed as the Authorization header to the MCP endpoint. Match this value to the Cloudflare Access policy configured for your deployment.

Keep the secret out of source control and grant the runtime identity secretAccessor on this secret only. For Cloudflare's standard service-token headers, adapt the client to send CF-Access-Client-Id and CF-Access-Client-Secret separately.
