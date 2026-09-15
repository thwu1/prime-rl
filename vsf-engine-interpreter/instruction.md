Build a functional mock of the NIST Entropy Source Validation Test System (ESVTS) at `/app/`, fully implementing the protocol and infrastructure defined in `/app/spec.md`.

The system requires three integrated subsystems:

**PKI infrastructure** (`/app/pki/`) — Use `openssl` to generate a root CA, a server certificate with Subject Alternative Name for localhost and 127.0.0.1, and a client certificate. All certificates must form a valid chain with correct X.509 key usage extensions (serverAuth, clientAuth). The server certificate must be usable for mTLS on port 7443.

**Authentication module** (`/app/esvts_auth.py`) — Implement TOTP per RFC 6238 (HMAC-SHA1, 30-second step, 8-digit codes) using the hex-encoded seed at `/app/totp_seed.txt`, and JWT management (HMAC-SHA256, base64url, 30-minute expiry) using the secret at `/app/jwt_secret.txt`. The module API is specified in `/app/spec.md`.

**Validation engine** (`/app/vsf_engine.py`) — Implement the Validation Script Framework engine specified in `/app/spec.md` using the trees and rules at `/app/vsf_config/`.

**ESVTS server** (`/app/esvts_server.py`) — An mTLS-enabled HTTPS server on port 7443 implementing three ESV protocol endpoints: TOTP-based login, entropy assessment registration with integrated payload validation, and assessment status retrieval with JWT authorization. The server must map camelCase protocol field names to PascalCase validation identifiers as specified.

**Protocol client** (`/app/esvts_client.py`) — Exercises the full login, register, and status-check flow over mTLS using the generated PKI and authentication module.