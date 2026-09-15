A cryptographic operations module at `/app/crypto_ops.py` wraps the Python `cryptography` library to provide AES-GCM, ECDSA, HMAC, and HKDF operations. The module contains multiple security-critical bugs that cause it to violate cryptographic specifications in ways that match real-world CVEs found by Project Wycheproof.

Wycheproof test vector files are available at `/app/vectors/`:
- `aes_gcm_test.json` -- AES-GCM authenticated encryption (AEAD test format)
- `ecdsa_secp256r1_sha256_test.json` -- ECDSA signature verification (ASN.1 encoded)
- `hmac_sha256_test.json` -- HMAC-SHA256 message authentication (MAC test format)
- `hkdf_sha256_test.json` -- HKDF-SHA256 key derivation

Each file follows the Wycheproof JSON schema: test groups contain shared parameters (keys, curves, hash functions) and individual test vectors with `result` fields (`"valid"`, `"invalid"`, or `"acceptable"`). The `flags` field on each vector references bug type classifications defined in the file's `notes` section.

Audit the module using these test vectors. Fix all bugs in `/app/crypto_ops.py` so that valid vectors produce correct results and invalid vectors are properly rejected. Write `/app/findings.json` documenting each bug:

```json
{
  "bugs": [
    {
      "function": "<function_name>",
      "bug_type": "<Wycheproof bugType classification>",
      "description": "<description of the bug and its security impact>"
    }
  ]
}
```