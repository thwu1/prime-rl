You are conducting a NIST ACVP conformance audit. Three vendors — **alpha**, **beta**, and **gamma** — each submitted AES-CBC and SHA2-256 ACVP response JSON files produced by their cryptographic implementations. Each vendor's implementation contains **exactly two distinct bugs**, each affecting a different set of test groups.

Your task: analyze every vendor submission against the ACVP specification, identify which test groups fail, diagnose the root cause of each failure, classify each bug, and produce both a structured audit report and the correct reference ACVP responses.

## Input Files

- `/app/prompts/aes_cbc_prompt.json` — NIST ACVP prompt for AES-CBC (42 test groups: AFT and MCT, 128/192/256-bit keys, encrypt and decrypt)
- `/app/prompts/sha256_prompt.json` — NIST ACVP prompt for SHA2-256 (3 test groups: AFT, MCT with `mctVersion` field, LDT)
- `/app/specs/acvp_test_procedures.md` — Algorithm specification with pseudocode for all test types
- `/app/vendor_submissions/{alpha,beta,gamma}/aes_cbc_results.json` — Vendor AES-CBC responses
- `/app/vendor_submissions/{alpha,beta,gamma}/sha256_results.json` — Vendor SHA2-256 responses

## Required Output

1. `/app/audit_report.json` — Structured audit findings (schema below)
2. `/app/results/aes_cbc_results.json` — Correct reference AES-CBC response
3. `/app/results/sha256_results.json` — Correct reference SHA2-256 response

## Audit Report Schema

```json
{
  "vendor_alpha": {
    "aes_cbc_failing_groups": [<sorted tgIds>],
    "sha256_failing_groups": [<sorted tgIds>],
    "bugs": [
      {
        "affected_algorithm": "AES-CBC" or "SHA2-256",
        "affected_groups": [<sorted tgIds affected by this specific bug>],
        "category": "<bug category>"
      }
    ]
  },
  "vendor_beta": { ... },
  "vendor_gamma": { ... }
}
```

Each vendor has exactly 2 entries in `bugs`. The `affected_groups` for a vendor's two bugs are disjoint and their union equals the vendor's combined failing groups.

## Bug Categories

Classify each bug into exactly one of these categories:

- `key_schedule` — incorrect key or IV derivation between MCT outer iterations (e.g., wrong byte selection in key shuffle routine)
- `cbc_chain` — incorrect CBC mode feedback/chaining within the MCT inner loop (e.g., wrong implicit IV for block cipher)
- `ldt_expansion` — incorrect Large Data Test message construction (e.g., wrong repetition/expansion of content)
- `mct_algorithm` — wrong MCT algorithm variant selected (e.g., ignoring version-selection fields)
- `mct_state` — incorrect MCT state propagation between outer iterations (e.g., failing to update iteration seed)

All hex values in reference responses must be uppercase. Reference responses must follow the ACVP JSON structure described in the spec.