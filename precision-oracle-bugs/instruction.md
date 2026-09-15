The file `/app/precision_oracle.py` computes 10 special function values to 50 significant digits using naive algorithms. Most results are incorrect — some catastrophically so — due to fundamental algorithmic limitations that manifest differently for each computation. Run the oracle and examine its output to diagnose the failures.

Produce `/app/adaptive_engine.py` that correctly evaluates all 10 quantities using precision-adaptive methods with two independent algorithms per computation for cross-validation.

## Computation Targets

**Polylogarithm** Li_s(z) — keys `2:0.5`, `2:-1`, `3:-1`, `2:1-1e-20`

**Hurwitz zeta** ζ(s,a) — keys `2:0.25`, `3:0.75`, `0.5:0.25`

**Hilbert determinant** det(H_n) — keys `10`, `15`, `20`

## Output Schemas

### `/app/output/results.json`

```json
{
  "polylog": {"2:0.5": "<50 sig digits>", "2:-1": "...", "3:-1": "...", "2:1-1e-20": "..."},
  "hurwitz_zeta": {"2:0.25": "...", "3:0.75": "...", "0.5:0.25": "..."},
  "hilbert_det": {"10": "...", "15": "...", "20": "..."}
}
```

### `/app/output/diagnostics.json`

```json
{
  "computations": {
    "<category>:<param>": {
      "algorithm_a": {"name": "<string>", "value": "<string>"},
      "algorithm_b": {"name": "<different string>", "value": "<string>"},
      "agreement_digits": "<int: digits both algorithms agree on>",
      "cross_check_passed": "<bool: true if agreement_digits >= 45>"
    }
  },
  "summary": {
    "all_cross_checks_passed": "<bool>",
    "min_agreement_digits": "<int>",
    "total_computations": 10
  }
}
```

Computation keys: `polylog:2:0.5`, `polylog:2:-1`, `polylog:3:-1`, `polylog:2:1-1e-20`, `hurwitz_zeta:2:0.25`, `hurwitz_zeta:3:0.75`, `hurwitz_zeta:0.5:0.25`, `hilbert_det:10`, `hilbert_det:15`, `hilbert_det:20`.

## Acceptance Criteria

- All 10 result values match references to ≥40 significant digits.
- Both algorithm values individually correct to ≥35 significant digits.
- All cross-checks show ≥45 digits of agreement.
- `summary.all_cross_checks_passed` is `true`, `summary.min_agreement_digits` ≥ 45, `summary.total_computations` equals 10.