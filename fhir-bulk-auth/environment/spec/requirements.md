# SMART Backend Services Authorization & FHIR Bulk Data Export — Protocol Specification

## 1. Deployment Configuration

The server MUST read `/app/config/instance.json` at startup. This file is generated
per deployment and contains values that MUST NOT be hardcoded:

| Field                       | Type    | Description |
|-----------------------------|---------|-------------|
| `instance_id`               | string  | Unique deployment identifier. Include as `deployment_id` claim in issued access tokens, and as the value for the custom response header. |
| `token_issuer`              | string  | Value to use as the `iss` claim in all issued access tokens. |
| `custom_header`             | string  | HTTP header name that MUST be present on every FHIR endpoint response (`/fhir/*`), with `instance_id` as the value. |
| `max_assertion_lifetime_sec`| integer | Maximum allowed seconds between current time and `exp` in JWT client assertions. Reject assertions where `exp - now` exceeds this value. |
| `access_token_lifetime_sec` | integer | Lifetime of issued access tokens in seconds. Use for both the JWT `exp` claim offset and the `expires_in` response field. |

---

## 2. Token Endpoint

`POST /auth/token` — authenticates backend service clients via JWT Bearer assertions.

### 2.1 Request Parameters (application/x-www-form-urlencoded)

| Parameter               | Required Value                                                          |
|-------------------------|-------------------------------------------------------------------------|
| `grant_type`            | `client_credentials` — reject other values with 400                     |
| `client_assertion_type` | `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` — reject other values with 400 |
| `client_assertion`      | Signed JWT (see §2.2)                                                   |
| `scope`                 | Space-separated FHIR scopes (optional)                                  |

### 2.2 JWT Client Assertion Claims (all required)

| Claim | Description |
|-------|-------------|
| `iss` | Client's `client_id` — must match `sub` |
| `sub` | Client's `client_id` — must match `iss` |
| `aud` | Token endpoint URL: `http://localhost:8080/auth/token` |
| `exp` | Unix timestamp. Must be in the future. `exp - now` must not exceed `max_assertion_lifetime_sec` from instance config. |
| `jti` | Unique nonce. Previously-used values must be rejected (replay protection). |

### 2.3 Validation Order

1. Verify `grant_type` and `client_assertion_type`
2. Decode JWT, check all five claims present
3. Verify `iss == sub`
4. Look up client in `/app/config/registered_clients.json` under `clients.<client_id>`
5. Verify `aud` matches token endpoint URL
6. Verify `exp > now` and `exp - now <= max_assertion_lifetime_sec`
7. Verify `jti` has not been used before
8. Verify JWT signature against client's registered public key (from `clients.<client_id>.jwks`)

### 2.4 Success Response (HTTP 200)

```json
{
  "access_token": "<RS256-signed JWT>",
  "token_type": "bearer",
  "expires_in": <access_token_lifetime_sec from instance config>,
  "scope": "<granted scopes>"
}
```

### 2.5 Access Token JWT Claims

Sign with `/app/config/server_private_jwk.json` using RS256. Include:

- `iss`: `token_issuer` from instance config
- `sub`: authenticated client_id
- `deployment_id`: `instance_id` from instance config
- `scope`: granted scopes (intersection of requested and allowed)
- `exp`: `now + access_token_lifetime_sec`
- `iat`: current time
- `jti`: unique identifier

---

## 3. JWKS Endpoint

`GET /.well-known/jwks.json` — serve `/app/config/server_jwks.json` as-is.

---

## 4. FHIR Bulk Data Export

### 4.1 Export Kick-off

`POST /fhir/Group/1/$export`

- Requires `Authorization: Bearer <token>` and `Prefer: respond-async`
- Returns HTTP 202 with `Content-Location` header pointing to status URL
- MUST include the custom header from instance config

### 4.2 Export Status

`GET /fhir/bulk-status/<job_id>`

- Requires Bearer token authentication
- In-progress: HTTP 202
- Complete: HTTP 200 with manifest:

```json
{
  "transactionTime": "<ISO 8601>",
  "request": "<original request>",
  "requiresAccessToken": true,
  "output": [
    {"type": "<ResourceType>", "url": "<download URL>", "count": <N>}
  ],
  "error": []
}
```

The `output` array MUST contain entries for **every** resource type directory found
in `/app/data/fhir/` (excluding Group). Dynamically discover types — do not hardcode
a fixed list.

### 4.3 NDJSON Download

`GET /fhir/bulk-data/<job_id>/<resource_type>` (or equivalent URL from manifest)

- Requires Bearer token auth. Return 401 without valid token.
- `Content-Type: application/fhir+ndjson`
- One JSON resource per line, must include `resourceType` and `id`

### 4.4 Export Cancellation

`DELETE /fhir/bulk-status/<job_id>` — returns HTTP 202.

### 4.5 Authentication Enforcement

All `/fhir/*` endpoints MUST return HTTP 401 for requests without a valid Bearer token.

---

## 5. Configuration Files

| Path | Description |
|------|-------------|
| `/app/config/instance.json` | Deployment-specific parameters (see §1) |
| `/app/config/registered_clients.json` | Client registrations: `{ "token_endpoint": "...", "clients": { "<id>": { "client_id", "allowed_scopes", "jwks" } } }` |
| `/app/config/server_private_jwk.json` | Server RSA private key for signing access tokens |
| `/app/config/server_jwks.json` | Server public JWKS |
| `/app/data/fhir/<Type>/<id>.json` | FHIR R4 resources for bulk export |
