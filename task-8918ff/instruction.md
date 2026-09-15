A cryptographic validation service at `/app/crypto_service.py` has been deployed with custom ASN.1 parsing and compatibility extensions layered on top of standard primitives (AES-GCM, ECDSA secp256r1/SHA-256, HMAC-SHA256, X25519, HKDF-SHA256). An internal review has flagged it as potentially containing security-critical defects.

Project Wycheproof test vectors are available at `/app/vectors/` in JSON format. Use them to systematically audit the service.

Your objectives:

1. **Audit** `/app/crypto_service.py` — identify every security vulnerability present in the code.

2. **Fix** all vulnerabilities in `/app/crypto_service.py`. Correct (valid) inputs must continue to produce correct results after your changes.

3. **Report** your findings to `/app/audit_report.json` with the following structure:

```json
{
  "vulnerabilities": [
    {
      "function": "<affected function name>",
      "bug_type": "<Wycheproof classification from the vector files>",
      "severity": "<brief severity note>",
      "description": "<what the bug is and why it is dangerous>",
      "fix": "<what you changed to fix it>"
    }
  ]
}
```

Each vulnerability's `bug_type` must correspond to a classification used in the Wycheproof test vector files.