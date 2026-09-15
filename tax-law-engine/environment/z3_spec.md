# Z3 Formal Verification Specification for IRC §121

Implement `/app/formal_verify.py` using the Z3 SMT solver (via the `z3-solver` Python package) to verify four properties of the §121 exclusion computation. Write results to `/app/verification_results.json`.

## Output Format

`/app/verification_results.json` must be a JSON array of objects, one per property:

```json
[
  {
    "property": "<property_name>",
    "result": "proved" | "disproved" | "witness_found" | "no_witness",
    "solver_result": "unsat" | "sat"
  },
  ...
]
```

- For universal properties (should hold for all inputs): assert the **negation** and check satisfiability. If `unsat`, the property is `"proved"`. If `sat`, the property is `"disproved"`.
- For existential properties (should have a witness): assert the claim directly. If `sat`, `"witness_found"`. If `unsat`, `"no_witness"`.

## Properties to Verify

### 1. `single_cap_bound`

**Claim (universal):** For any single-filer exclusion computation with non-negative gain, depreciation in `[0, gain]`, NQ ratio in `[0, 1]`, and cap in `[0, 250000]`, the excluded gain never exceeds $250,000.

The exclusion formula to model:
```
eligible = max(0, (gain - depreciation) * (1 - nq_ratio))
excluded = min(eligible, cap)
excluded_final = min(excluded, gain)
```

Assert `excluded_final > 250000` and expect `unsat`.

### 2. `joint_cap_bound`

**Claim (universal):** Same as above but with cap in `[0, 500000]` and threshold of $500,000. Assert `excluded_final > 500000` and expect `unsat`.

### 3. `reduced_leq_full`

**Claim (universal):** For any base cap ≥ 0 and days in `[0, 730)`, the reduced cap `base_cap * days / 730` never exceeds the base cap. Assert `reduced > base_cap` and expect `unsat`.

### 4. `nq_use_can_reduce`

**Claim (existential):** There exist inputs with `gain > 0` and `nq_ratio > 0` (NQ ratio in `(0, 1]`, cap = $250,000, no depreciation) where the excluded gain with NQ use is strictly less than the excluded gain without NQ use.

Model:
```
excluded_no_nq = min(gain, 250000)
excluded_with_nq = min(max(0, gain * (1 - nq_ratio)), 250000)
excluded_with_nq_final = min(excluded_with_nq, gain)
```

Assert `excluded_with_nq_final < excluded_no_nq` and expect `sat`.
