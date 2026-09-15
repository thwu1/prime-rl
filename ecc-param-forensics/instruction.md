An elliptic curve cryptography library deployed in a financial signing infrastructure has triggered anomalous verification failures. Three diagnostic datasets have been extracted from the library's subsystems and placed in `/app/data/`:

- `montgomery_challenge.json` — Montgomery representation parameters alleged to be correct for five standard elliptic curves (word size specified in the file)
- `ecrdsa_challenge.json` — Four ECRDSA signatures on the same message with disclosed private key and nonces, produced by two different code paths in the library
- `ecdsa_signatures.json` — Two ECDSA signatures on SECP256K1 from the production signing subsystem

A C reference tool for Montgomery arithmetic verification is available as source at `/app/tools/monty_check.c`. OpenSSL and a C compiler are installed.

Audit these datasets, identify all defects and vulnerabilities, evaluate their security impact, and produce the following artifacts in `/app/results/`:

**`montgomery_results.json`** — For each curve, your verdict on whether its Montgomery parameters are valid. JSON keyed by curve name. Correct: `{"correct": true}`. Incorrect: `{"correct": false, "errors": ["<field>", ...], "correct_r": "0x...", "correct_r_square": "0x...", "correct_mpinv": "0x...", "correct_pbitlen": <int>}`.

**`ecrdsa_results.json`** — Your determination of which standard convention (ISO 14888-3 or RFC 7091) produced each signature. Format: `{"sig_1": "ISO"|"RFC", "sig_2": ..., "sig_3": ..., "sig_4": "ISO"|"RFC"}`.

**`ecdsa_recovery.json`** — If any exploitable vulnerability exists in the ECDSA signature data, demonstrate full exploitation. Format: `{"recovered_k": "0x...", "recovered_x": "0x..."}`.

**`security_assessment.json`** — A consolidated risk assessment synthesizing all findings. You must evaluate severity of each defect considering exploitability, blast radius, and real-world impact on the financial signing deployment, and justify an overall risk rating. Format:
```json
{
  "findings": [{"id": "...", "severity": "CRITICAL"|"HIGH"|"MEDIUM"|"LOW", "category": "...", "impact": "..."}],
  "overall_risk": "CRITICAL"|"HIGH"|"MEDIUM"|"LOW",
  "risk_justification": "..."
}
```

**`detect.sh`** — Design a reusable Montgomery parameter validation tool: a standalone bash script that accepts any JSON file in the challenge format, prints names of curves with invalid parameters to stdout, and exits 0 if all valid or 1 if any are invalid. Must correctly handle arbitrary primes and word sizes, not just the five curves in this dataset.