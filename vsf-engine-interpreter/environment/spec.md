# ESVTS Mock Server Specification

## Overview

The NIST Entropy Source Validation Test System (ESVTS) uses a REST API secured with mutual TLS (mTLS), TOTP-based login, and JWT session management to validate entropy sources per SP 800-90B. This specification defines the complete requirements for a mock ESVTS server.

---

## 1. PKI Infrastructure

Generate a certificate hierarchy at `/app/pki/` using the `openssl` command-line tool.

### Required Files

| File | Description |
|------|-------------|
| `ca.key` | Root CA private key (RSA, >= 2048 bits) |
| `ca.crt` | Root CA self-signed certificate |
| `server.key` | Server private key (RSA, >= 2048 bits) |
| `server.crt` | Server certificate signed by Root CA |
| `client.key` | Client private key (RSA, >= 2048 bits) |
| `client.crt` | Client certificate signed by Root CA |

### Certificate Requirements

- The Root CA certificate must be self-signed with a subject containing "ESVTS" in the CN or O field.
- The server certificate must include:
  - Subject Alternative Name (SAN): `DNS:localhost` and `IP:127.0.0.1`
  - Extended Key Usage: `serverAuth`
- The client certificate must include:
  - Extended Key Usage: `clientAuth`
- All certificates must form a valid chain: `openssl verify -CAfile ca.crt server.crt` and `openssl verify -CAfile ca.crt client.crt` must succeed.
- Certificates should have reasonable validity periods (e.g., 365+ days).

---

## 2. Authentication

### 2.1 Mutual TLS (mTLS)

The server must enforce client certificate authentication. The SSL/TLS context must:
- Load the server certificate and private key
- Load the CA certificate to verify client certificates
- Set verification mode to require valid client certificates

Connections without a valid client certificate must be rejected at the TLS level.

### 2.2 TOTP — Time-based One-Time Password (RFC 6238)

Parameters:
- Hash algorithm: HMAC-SHA1
- Time step (X): 30 seconds
- Code length: 8 digits, zero-padded
- Seed: hex-encoded in `/app/totp_seed.txt`

Algorithm:
1. Compute time counter: `T = floor(unix_timestamp / X)`
2. Encode T as an 8-byte big-endian unsigned integer
3. Compute `H = HMAC-SHA1(seed_bytes, T_bytes)`
4. Dynamic truncation:
   - `offset = H[19] & 0x0F`
   - `code = (H[offset] & 0x7F) << 24 | H[offset+1] << 16 | H[offset+2] << 8 | H[offset+3]`
5. Return `str(code % 10^digits)`, zero-padded to 8 characters

Verification must accept codes within a configurable window (default: ±1 time step).

### 2.3 JWT — JSON Web Token

Signing algorithm: HMAC-SHA256 (HS256)  
Secret: plaintext in `/app/jwt_secret.txt`

Structure: `base64url(header) + "." + base64url(payload) + "." + base64url(signature)`

- Header: `{"alg":"HS256","typ":"JWT"}`
- Payload includes `iat` (issued-at, unix timestamp) and `exp` (expiration, unix timestamp)
- Default expiry: 1800 seconds (30 minutes)
- Base64url encoding: standard base64 with `+` → `-`, `/` → `_`, no `=` padding
- Signature: `HMAC-SHA256(secret, header_b64 + "." + payload_b64)`

Verification:
1. Split token into header, payload, signature parts
2. Recompute and compare signature (constant-time comparison)
3. Check `exp` >= current time
4. Return decoded payload dict, or `None` on any failure

---

## 3. Authentication Module API

File: `/app/esvts_auth.py`

```python
def generate_totp(seed: bytes, timestamp: int = None, step: int = 30, digits: int = 8) -> str:
    """Generate a TOTP code. If timestamp is None, use current time."""

def verify_totp(seed: bytes, code: str, timestamp: int = None,
                step: int = 30, digits: int = 8, window: int = 1) -> bool:
    """Verify a TOTP code within ±window time steps."""

def create_jwt(claims: dict, secret: str, expires_in: int = 1800) -> str:
    """Create a signed JWT. Adds iat and exp if not present in claims."""

def verify_jwt(token: str, secret: str) -> dict | None:
    """Verify and decode a JWT. Returns payload dict or None."""
```

---

## 4. ESV Protocol Endpoints

The server at `/app/esvts_server.py` listens on port 7443 with mTLS.

### POST /esv/v1/login

Authenticates using TOTP. No Bearer token required (mTLS only).

**Request:**
```json
[{"esvVersion": "1.0"}, {"password": "<8-digit TOTP code>"}]
```

**Success (200):**
```json
[{"esvVersion": "1.0"}, {"accessToken": "<session JWT>"}]
```

The session JWT should contain at minimum `{"userId": 1, "type": "session"}`.

**Failure (403):** Invalid TOTP code.

Token refresh: if the request body includes an `accessToken` field alongside `password`, issue a fresh JWT (same semantics as initial login).

### POST /esv/v1/entropyAssessments

Registers an entropy source. Requires `Authorization: Bearer <JWT>` header.

**Request:**
```json
[
    {"esvVersion": "1.0"},
    {
        "primaryNoiseSource": "ring oscillators",
        "iidClaim": false,
        "bitsPerSample": 4,
        "hminEstimate": 3.1,
        "physical": true,
        "numberOfRestarts": 1000,
        "samplesPerRestart": 1000,
        "additionalNoiseSources": false,
        "conditioningComponent": [
            {
                "sequencePosition": 1,
                "vetted": false,
                "bijectiveClaim": false,
                "description": "custom XOR filter",
                "minNin": 16,
                "nOut": 8,
                "hOut": 7.5
            }
        ]
    }
]
```

Before accepting, the server must validate the payload using the Validation Script Framework engine (Section 7) with the tree at `/app/vsf_config/ValidationTrees/RegisterRequest/registerEntropySource.json`.

**Field name mapping** — the protocol uses camelCase but the validation tree uses PascalCase identifiers:

| Protocol (camelCase) | Validation (PascalCase) |
|---------------------|------------------------|
| primaryNoiseSource | PrimaryNoiseSource |
| iidClaim | IidClaim |
| bitsPerSample | BitsPerSample |
| hminEstimate | HMinEstimate |
| physical | IsPhysical |
| numberOfRestarts | NumberOfRestarts |
| samplesPerRestart | SamplesPerRestart |
| additionalNoiseSources | AdditionalNoiseSources |
| conditioningComponent | ConditioningComponents |
| sequencePosition | SequencePosition |
| vetted | IsVetted |
| bijectiveClaim | IsBijectiveClaim |
| description | Description |
| validationNumber | ValidationNumber |
| minNin | MinNIn |
| nOut | NOut |
| hOut | HOut |

The protocol field `numberOfOEs` (integer, default 1) does not exist in the validation tree. Instead, the validation tree expects `OperatingEnvironmentIds` as a list of integers. When mapping, generate a list of IDs `[1, 2, ..., numberOfOEs]`. If `numberOfOEs` is absent, default to `[1]`.

**Success (200):**
```json
[
    {"esvVersion": "1.0"},
    [{
        "url": "/esv/v1/entropyAssessments/<eaId>",
        "createdOn": "<ISO datetime>",
        "expiresOn": "<ISO datetime>",
        "dataFileUrls": [
            {"rawNoiseBits": "/esv/v1/entropyAssessments/<eaId>/dataFiles/<dfId1>"},
            {"restartTestBits": "/esv/v1/entropyAssessments/<eaId>/dataFiles/<dfId2>"},
            {"conditionedBits": "/esv/v1/entropyAssessments/<eaId>/dataFiles/<dfId3>", "sequencePosition": 1}
        ],
        "publishable": false,
        "accessToken": "<JWT with eaId claim>"
    }]
]
```

The `accessToken` in the response must be a JWT containing an `eaId` claim for the created assessment.

Conditioned-bits data file URLs are generated only for non-vetted, non-bijective conditioning components.

**Validation failure (400):** Return error details.  
**Missing/invalid JWT (401):** Unauthorized.

### GET /esv/v1/entropyAssessments/<eaId>

Returns status of a previously registered assessment. Requires `Authorization: Bearer <JWT>`.

**Success (200):**
```json
[
    {"esvVersion": "1.0"},
    {
        "createdOn": "<ISO datetime>",
        "status": "pendingEvaluation",
        "primaryNoiseSource": "ring oscillators",
        "iidClaim": false,
        "bitsPerSample": 4,
        "hminEstimate": 3.1,
        "physical": true
    }
]
```

**Not found (404):** Unknown eaId.  
**Missing/invalid JWT (401):** Unauthorized.

---

## 5. Protocol Client

File: `/app/esvts_client.py`

Must demonstrate the complete protocol flow:
1. Read TOTP seed and JWT secret from config files
2. Generate TOTP code from the seed
3. POST `/esv/v1/login` using mTLS client cert + TOTP → receive session JWT
4. POST `/esv/v1/entropyAssessments` with Bearer JWT → receive eaId and assessment JWT
5. GET `/esv/v1/entropyAssessments/<eaId>` with Bearer JWT → receive status
6. Print each response

The client must use mTLS with the certificates at `/app/pki/`.

---

## 6. Server Configuration

The server (`/app/esvts_server.py`) must:
- Listen on `0.0.0.0:7443`
- Use mTLS with PKI from `/app/pki/` (require client certificates)
- Read TOTP seed from `/app/totp_seed.txt`
- Read JWT secret from `/app/jwt_secret.txt`
- Integrate the validation engine for registration requests
- Store registered assessments in memory (no persistence required)
- Be startable with `python3 /app/esvts_server.py`

---

## 7. Validation Script Framework (VSF) Engine

File: `/app/vsf_engine.py`

### Overview

The VSF is a JSON-driven validation engine. It validates JSON payloads against declarative rules organized in a tree structure, decoupling validation logic from code.

Components:
1. **Validation Trees** — define payload structure and which rules apply to which properties
2. **Rule Scripts** — contain validation logic as C#-like expressions
3. **The Engine** — traverses the tree, resolves rules, and evaluates them against the payload

### Validation Trees

A validation tree is a JSON array containing one object with:
- `modelName`: string identifier for the payload type
- `rootNode`: the root of the validation tree

#### Node Structure

The `rootNode` has:
- `dataType`: string identifier for the data type
- `nodeData`: object containing `vsfScriptFiles` (array of script references)
- `nodes`: array of child nodes

#### Node Types

Child nodes have a `nodeType` field:

- **`leaf`**: Terminal node. Maps a single property to validation scripts. Contains:
  - `property.internalIdentifier`: the property name in the payload
  - `nodeData.vsfScriptFiles`: scripts to run against this property's value

- **`parent`**: Nested object node. Like leaf but also has child `nodes`. Contains:
  - `property.internalIdentifier`: the property name containing the nested object
  - `nodeData.vsfScriptFiles`: scripts to run against the object itself
  - `nodes`: child nodes for properties within the nested object

- **`list`**: Array property node. Contains:
  - `property.internalIdentifier`: the property name containing the array
  - `nodeData.vsfScriptFiles`: scripts for the list itself (count checks, uniqueness)
  - `listItem`: per-item processing definition

#### List Item Processing

The `listItem` object contains:
- `branchNodeData`: optional hooks:
  - `runBeforeListItem`: scripts executed before each item's nodes. currentProperty = list item, parentProperty = list.
  - `runAfterListItem`: scripts executed after each item's nodes. currentProperty = list item, parentProperty = list.
- `nodes`: child nodes to process for each list item

#### Script References

`vsfScriptFiles` is an array of objects with:
- `scriptFile`: path relative to the rules base directory
- `breakOnError`: optional boolean (default `true`). When true and the script fails, subsequent scripts in the same array are skipped. When false, processing continues.

#### Context Variables

During validation:
- `currentProperty`: the value currently being validated
- `parentProperty`: the parent object containing the current property

For root-level leaf `BitsPerSample`:
- `currentProperty` = `payload["BitsPerSample"]`
- `parentProperty` = `payload`

For `runBeforeListItem`/`runAfterListItem`:
- `currentProperty` = the list item
- `parentProperty` = the list

### Rule Scripts

A rule script is a JSON file with a `vsfScript` array of line objects.

#### Line Types

**Rule** — Evaluates an expression. Two modes:
- `"ruleType": "External"`: validation rule. If false, a `ValidationError` is recorded.
- No ruleType: condition check. If false, the line fails but no error is recorded.

**ImportScript** — Loads and executes another rule script. Path relative to rules base dir.

**Branch** — Conditional execution with `if`/`elseif`/`else`:
```json
{
    "lineType": "Branch",
    "conditions": [
        {"if": {"scriptLines": [...]}, "then": {"scriptLines": [...]}},
        {"elseif": {"scriptLines": [...]}, "then": {"scriptLines": [...]}},
        {"else": {"scriptLines": [...]}}
    ]
}
```
Condition `scriptLines` are evaluated without collecting errors. If all condition lines succeed, the `then` block runs (errors ARE collected). Only one branch executes.

**State** — Stores a computed value: `{"lineType": "State", "parameters": {"key": "name", "value": "expression"}}`. Failures are non-fatal and do not cause short-circuiting.

**Assert** — Boolean check. If false or on error, the current script stops (no validation error reported).

**Information** — Informational/logging. No validation effect; skip silently.

**Exit** — Stops processing the current node and all its children.

#### Script Execution Semantics

Within a script, lines execute sequentially. If any line fails (except State), subsequent lines are skipped (short-circuit). At the `vsfScriptFiles` level, if a script fails and `breakOnError` is true, remaining scripts are skipped.

### Expression Language

C#-like syntax in `ruleText` fields.

**Variables:** `currentProperty`, `parentProperty`, state variables

**Property access:** `obj.PropertyName` → `obj["PropertyName"]` (dict) or `len(obj)` (string `.Length`)

**Operators:** `==`, `!=`, `>`, `>=`, `<`, `<=`, `&&` (short-circuit AND), `||` (short-circuit OR), `!` (NOT)

**Precedence (high to low):** `!`, comparisons, `&&`, `||`

**Methods:** `.Count()` (list length), `.Distinct()` (unique elements), `.StartsWith(str)`, `.Substring(index)`

**Static methods:** `string.IsNullOrWhiteSpace(expr)`, `Int32.Parse(str)`, `Regex.IsMatch(str, pattern)`

**Literals:** `null`, `true`, `false`, integers, floats, `"strings"`

### Engine API

```python
class VsfEngine:
    def __init__(self, rules_base_dir: str):
        """Initialize with path to the RuleScripts directory."""

    def validate(self, tree_path: str, payload) -> ValidationResult:
        """Validate a payload against a validation tree."""

class ValidationResult:
    passed: bool       # True if no validation errors
    errors: list       # List of ValidationError

class ValidationError:
    property_path: str  # e.g., "ConditioningComponents[0].ValidationNumber"
    rule_text: str      # The expression that failed
```

#### Property Path Format

- Root: `""` (empty string)
- Leaf: `"BitsPerSample"`
- Nested: `"Metadata.Description"`
- List item: `"ConditioningComponents[0]"`
- List item property: `"ConditioningComponents[0].ValidationNumber"`

#### Error Reporting

Only `Rule` lines with `ruleType: "External"` that evaluate to `false` produce errors. Branch conditions, Assert failures, and non-External Rules only affect control flow.
