# Security model

## Boundaries

- The dashboard has no browser document upload. The paired host agent can transfer policy-eligible documents into the app's persistent volume. It runs under the host user's permissions; choose a dedicated user with read access only to intended source folders where possible. Legacy uploaded documents may also remain in the volume. Treat the whole volume as private data.
- Host folder selection requires dashboard login. The agent pairing key is shown only when created and stored hashed in the app volume. Keep the host-side key file private. The agent accepts plain HTTP only over the host's loopback address; use HTTPS for a remote dashboard.
- Bind Qdrant to localhost. The application does not authenticate to Qdrant by default.
- Docker publishes the Web UI and MCP server on the host's LAN interfaces. The Web UI can use a password; the MCP server has no built-in login. Limit access with a firewall and add an authenticated HTTPS proxy or Cloudflare Access before Internet exposure. Use HTTPS when entering the Web UI password over a network.
- Review index-policy.yaml before ingestion. Directory and extension filters are the first boundary. Retrieval repeats restricted-path filtering, including Windows-style separators, as a second boundary.
- Avoid putting secrets in the source corpus. The output redactor only recognizes common patterns in returned fields. It cannot guarantee removal of arbitrary credentials or sensitive prose.
- MCP clients receive selected source text. Retrieved excerpts leave the host by design.

## Operational checks

1. If using a host source folder through the agent, check its connection and synchronization status before indexing. If using a bind mount, verify that it is read-only.
2. Inspect the ingestion policy and a dry-run sample before the first full index.
3. Keep .env, Cloudflare tokens, the Qdrant volume and ingestion state outside version control.
4. Test authentication on the public hostname before giving it to a client.
5. Rotate any exposed credential; redaction does not undo exposure.

The [Cloudflare guide](cloudflare-access.md) covers one possible access layer. No specific homelab address, Google project, or Cloudflare token is required by this repository.
