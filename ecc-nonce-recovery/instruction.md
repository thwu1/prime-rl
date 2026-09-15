A government signing service uses NIST P-256 with three signature algorithms — ECDSA, ECGDSA, and ECRDSA — for document authentication. After a security incident was reported, perform a comprehensive cryptographic security audit of the service's signing infrastructure.

Challenge data is at `/app/challenge_data.json`. It contains P-256 curve parameters (OpenSSL name: `prime256v1`), two public keys, six signatures (indices 0–5) across the three algorithms, and algorithm specifications.

Your audit must: evaluate every signature for cryptographic vulnerabilities, determine the specific hash convention variant used for each ECRDSA signature, exploit any exploitable weakness to recover the signing private key, and produce all cryptographic artifacts in standard OpenSSL-compatible formats.

## Required outputs

### `/app/audit_report.json`

Structured vulnerability assessment with this exact schema:

```json
{
  "findings": [
    {
      "sig_index": 0,
      "status": "vulnerable",
      "vulnerability_type": "nonce_reuse",
      "details": "..."
    },
    {
      "sig_index": 1,
      "status": "safe",
      "vulnerability_type": "none",
      "details": "..."
    }
  ],
  "ecrdsa_conventions": [
    {"sig_index": 2, "convention": "iso"},
    {"sig_index": 4, "convention": "rfc"}
  ],
  "exploited_pair": [0, 3]
}
```

Requirements for `findings`:
- Must contain an entry for each of the six signatures (indices 0–5).
- `status` must be exactly `"vulnerable"` or `"safe"`.
- For signatures sharing a nonce (identifiable by matching `r` values), set `status` to `"vulnerable"` and `vulnerability_type` to `"nonce_reuse"`.
- For signatures with no detected weakness, set `status` to `"safe"`.

Requirements for `ecrdsa_conventions`:
- Must contain one entry for each ECRDSA signature.
- `convention` must be exactly `"iso"` (ISO 14888-3, big-endian hash) or `"rfc"` (RFC 7091, byte-reversed hash). Determine which by verifying each ECRDSA signature under both conventions against the provided public key.

Requirements for `exploited_pair`:
- A two-element list of the signature indices whose shared nonce was exploited to recover the private key.

### `/app/recovered_key.pem`

The recovered EC private key in PEM format (PKCS#8 or SEC1) on the `prime256v1` curve. The file must:
- Be loadable by `openssl ec -in /app/recovered_key.pem -noout` without errors.
- Report curve `prime256v1` (equivalently `P-256` or `secp256r1`) when inspected with `openssl ec -text -noout`.
- Contain the correct private key value recovered from the nonce-reuse exploit.

### `/app/public_key.pem`

The EC public key in PEM format, extracted from the private key using `openssl pkey -in /app/recovered_key.pem -pubout`. The file content must exactly match the output of that command.

### `/app/challenge_sig.der`

A DER-encoded ECDSA-SHA256 signature over the exact challenge message string from `challenge_data.json["challenge"]["message"]`, produced using `openssl dgst -sha256 -sign`. The signature must:
- Be valid ASN.1 DER (parseable by `openssl asn1parse -inform DER`).
- Verify successfully with `openssl dgst -sha256 -verify /app/public_key.pem -signature /app/challenge_sig.der <message_file>`.