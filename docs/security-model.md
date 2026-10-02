# Security model

## Boundaries

- Mount source documents read-only where possible. Ingestion reads them; it writes only to Qdrant and INGESTION_BASE_DIR.
- Bind Qdrant to localhost. The application does not authenticate to Qdrant by default.
- The MCP server has no built-in authentication. Bind it to 127.0.0.1 unless an authenticated HTTPS proxy or Cloudflare Access is in place.
- Review index-policy.yaml before ingestion. Directory and extension filters are the first boundary. Retrieval repeats restricted-path filtering, including Windows-style separators, as a second boundary.
- Avoid putting secrets in the source corpus. The output redactor only recognizes common patterns in returned fields. It cannot guarantee removal of arbitrary credentials or sensitive prose.
- MCP clients receive selected source text. Local source files remain on the host, but retrieved excerpts leave it by design.

## Operational checks

1. Verify that the source mount is read-only for the service account.
2. Inspect the ingestion policy and a dry-run sample before the first full index.
3. Keep .env, Cloudflare tokens, the Qdrant volume and ingestion state outside version control.
4. Test authentication on the public hostname before giving it to a client.
5. Rotate any exposed credential; redaction does not undo exposure.

The [Cloudflare guide](cloudflare-access.md) covers one possible access layer. No specific homelab address, Google project, or Cloudflare token is required by this repository.
