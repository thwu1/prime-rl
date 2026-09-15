Build a server on port 8080, startable via `bash /app/start.sh`, that implements SMART Backend Services authorization (RFC 7523 JWT Bearer + OAuth 2.0 `client_credentials`) and FHIR Bulk Data Access `$export`.

The server is parameterized by deployment-specific configuration in `/app/config/instance.json` — token issuance, JWT validation thresholds, response headers, and access token claims all depend on values in this file. Nothing from instance config may be hardcoded; the server must read and honor every field at startup.

Read `/app/spec/requirements.md` for the full protocol specification covering:
- Token endpoint with JWT client assertion validation
- Access token issuance with deployment-specific claims
- JWKS endpoint
- Async bulk data export lifecycle (kick-off, status polling, NDJSON download, cancellation)
- Custom response header requirements
- Authentication enforcement

Client registrations and cryptographic keys are in `/app/config/`. FHIR R4 resources to export are in `/app/data/fhir/` — discover resource types dynamically from the directory structure rather than hardcoding a fixed set.