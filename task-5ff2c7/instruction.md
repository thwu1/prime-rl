Four vendor-submitted Python implementations of NIST SP 800-185 derived functions (cSHAKE, KMAC, TupleHash) are at `/app/candidates/` (`vendor_alpha.py`, `vendor_beta.py`, `vendor_gamma.py`, `vendor_delta.py`). Each module imports the verified Keccak-f[1600] permutation from `/app/keccak_ffi.py` and independently implements the higher-level constructions. All four export the same API: `cshake(security, X, L, N, S)`, `kmac(security, K, X, L, S)`, `tuplehash(security, tuples, L, S)`.

Official NIST test vectors covering cSHAKE128/256, KMAC128/256, and TupleHash128/256 are in `/app/test_vectors.json`.

Conduct a FIPS certification pre-assessment of all four vendor implementations:

**Conformance testing**: Determine per-function conformance against all test vectors for each vendor.

**Defect classification**: For each non-conformant function, classify the defect considering the SP 800-185 composition graph (KMAC and TupleHash both internally invoke cSHAKE):
- **independent**: a bug in the function's own construction logic
- **inherited**: failure caused solely by a broken dependency; fixing the dependency alone restores conformance
- **compound**: the function fails due to a broken dependency AND has its own independent construction error — fixing the dependency alone would NOT restore conformance

**Security impact assessment**: For each defect with an independent component (`classification` = `"independent"` or `"compound"`), assess:
- **critical**: breaks a fundamental cryptographic property (domain separation, unambiguous encoding) enabling practical collision or cross-protocol attacks
- **high**: produces non-conformant output, breaking interoperability or weakening construction-level security guarantees

Inherited-only defects receive `null` security impact.

**Remediation**: For each non-conformant vendor, produce a corrected implementation at `/app/patched/<vendor_name>.py` that passes all NIST test vectors. Corrected files must use the same `keccak_ffi` module and export the same API.

Write the audit report to `/app/audit_report.json`:

```json
{
  "candidates": {
    "<vendor_name>": {
      "cshake": "pass" | "fail",
      "kmac": "pass" | "fail",
      "tuplehash": "pass" | "fail",
      "defects": [
        {
          "function": "<function_name>",
          "classification": "independent" | "inherited" | "compound",
          "inherited_from": "<parent_function_name or null>",
          "root_cause": "<specific SP 800-185 encoding/construction error>",
          "security_impact": "critical" | "high" | null
        }
      ],
      "recommendation": "deploy" | "reject"
    }
  },
  "selected_vendor": "<fully conformant vendor recommended for deployment>"
}
```

Vendors with zero defects: `"recommendation": "deploy"`, empty defects list. All others: `"recommendation": "reject"`. The `selected_vendor` field names the single fully conformant vendor.