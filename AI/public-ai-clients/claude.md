# Claude

Expose the server through an authenticated HTTPS MCP endpoint. The [Cloudflare guide](../../knowledge-mcp/security/cloudflare/README.md) describes one way to do that. Follow Anthropic's current [custom connector instructions](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) to add the remote MCP URL. Product menus and plan availability can change.

Use the public portal URL if you created a Cloudflare MCP portal, or the protected origin URL if your client and authentication flow support it. Test the connection by calling knowledge_status. Search takes only one argument: query. The server does not accept per-call limit settings.

Retrieved excerpts are sent to Claude. Review the [security model](../../docs/security-model.md) and index policy before connecting a private corpus.
