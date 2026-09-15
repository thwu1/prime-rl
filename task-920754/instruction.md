Build a NIST Entropy Source Validation (ESV) protocol server and deploy it at `/app/esv_server/server.py`, listening on HTTPS port 8443.

The server must provide two endpoints:

1. **`POST /esv/v1/login`** — Authenticate clients using TOTP and return a session token. Reject invalid credentials with the appropriate status code.

2. **`POST /esv/v1/entropyAssessments`** — Accept entropy source registration payloads. Require a valid session token via the `Authorization` header. Validate the registration payload against the validation framework defined in `/app/config/validation_trees/` and `/app/config/rule_scripts/`. Return structured error responses for invalid payloads.

Before starting the server, create the PKI infrastructure at `/app/pki/` required for mutual TLS enforcement — the server must reject connections that do not present a valid client certificate.

All specifications — PKI structure, authentication parameters, session token configuration, request/response formats, and validation engine semantics — are documented in the configuration files under `/app/config/`:

- `/app/config/pki_requirements.json` — certificate hierarchy and extension requirements
- `/app/config/auth_config.json` — TOTP, session token, and protocol format specifications
- `/app/config/totp_seed.txt` — TOTP seed value
- `/app/config/validation_framework.md` — validation engine architecture and expression language
- `/app/config/validation_trees/` and `/app/config/rule_scripts/` — validation rule definitions

Run the server: `python3 /app/esv_server/server.py`