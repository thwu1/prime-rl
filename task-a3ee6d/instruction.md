Two AES-256 CTR_DRBG implementations are available for compliance auditing:

- `/app/impl_alpha/ctr_drbg.py` — Python implementation
- `/app/impl_beta/libctrdrbg.so` — compiled C shared library (API: `/app/impl_beta/ctrdrbg.h`)
- `/app/vectors/CTR_DRBG_AES256.rsp` — CAVP test vectors (8 configurations, 24 vectors total)
- `/app/vectors/CTR_DRBG_AES256_intermediate.txt` — reference intermediate state values
- `/app/run_validation.py` — minimal spot-check (covers 2 of 24 vectors)

Audit both implementations against the complete CAVP vector set. The following files must exist in `/app/` when complete:

- **`impl_alpha/ctr_drbg.py`** — must produce correct Key, V, and ReturnedBits for all 24 CAVP vectors across all 8 configurations.
- **`harness_beta.py`**
- **`cross_validate.sh`** — must be executable and exit 0.
- **`audit_report.json`** — structured compliance report (schema below).

## audit_report.json schema

```json
{
  "implementations": [
    {
      "name": "<impl_alpha or impl_beta>",
      "total_vectors": "<int>",
      "passed": "<int>",
      "failed": "<int>",
      "defects": [
        {
          "id": "<string>",
          "affected_configs": ["<string>"],
          "root_cause": "<string>",
          "severity": "<critical|high|medium|low>",
          "sp800_90a_section": "<string>"
        }
      ],
      "compliance_verdict": "<pass|fail>"
    }
  ],
  "cross_validation": {
    "intermediate_checks": "<int>",
    "checks_passed": "<int>"
  },
  "recommendation": "<string>"
}
```

- Both `impl_alpha` and `impl_beta` entries required, with accurate test results.
- `impl_alpha` must show all 24 vectors passing after correction.
- Non-compliant implementations must list at least 2 defects, each with valid `severity` (`critical`, `high`, `medium`, or `low`) and `sp800_90a_section`.
- `cross_validation`: `intermediate_checks` >= 3 and `checks_passed` >= 3.
- `recommendation` must be a substantive explanation (not a placeholder).