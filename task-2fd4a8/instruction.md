A data encryption platform at `/app/` uses XAES-256-GCM. Three independent implementations exist:

- **Alpha**: `/app/implementations/alpha/crypto.py` (Python) — currently deployed as `/app/service/crypto.py`
- **Beta**: `/app/implementations/beta/xaes_tool` (pre-compiled Go CLI binary with `encrypt`, `decrypt`, and `derive-key` subcommands accepting hex-encoded arguments)
- **Gamma**: `/app/implementations/gamma/crypto.py` (Python)

Cross-implementation interoperability testing has revealed inconsistent results: some pairs agree on certain keys but not others, while other pairs never agree. The interop matrix is at `/app/data/reports/interop_matrix.json` with partner CSV reports in `/app/data/reports/`. The service's own round-trip tests (`/app/tests/test_roundtrip.py`) pass, masking the real issues.

The XAES-256-GCM specification is at `/app/docs/spec.txt`, with reference test vectors in `/app/vendor/interop_vectors.json`.

Determine which implementations are spec-compliant and which contain bugs. For each non-compliant implementation, identify the specific cryptographic defect.

**Deliverables:**

1. `/app/audit_report.json` with this schema:
```json
{
  "implementations": {
    "alpha": {"verdict": "compliant|non-compliant", "description": "<specific bug or confirmation>"},
    "beta":  {"verdict": "compliant|non-compliant", "description": "<specific bug or confirmation>"},
    "gamma": {"verdict": "compliant|non-compliant", "description": "<specific bug or confirmation>"}
  },
  "verification": {
    "test_key_hex": "0101010101010101010101010101010101010101010101010101010101010101",
    "L_hex": "<computed L value in hex>",
    "K1_hex": "<computed K1 value in hex>"
  }
}
```

2. A spec-compliant implementation deployed at `/app/service/crypto.py` exposing `encrypt(key, nonce, plaintext, aad)` and `decrypt(key, nonce, ciphertext, aad)`.

3. All 30 records from `/app/data/plaintext/` re-encrypted into `/app/data/corrected/` using the corrected implementation, reusing the nonce and AAD from each record's corresponding file in `/app/data/encrypted/`.