A stripped x86-64 ELF binary at `/app/challenge` contains 8 functions (indexed 0–7) implementing optimized integer division/modulo by compile-time constants (magic-number multiplication sequences replacing `div`/`idiv`). The specification at `/app/spec.json` documents each function's intended operation and divisor. See `/app/README.txt` for usage and severity criteria.

Some implementations contain bugs — signedness mismatches, wrong divisors, or wrong operation types. Produce three deliverables:

**`/app/audit.json`** — JSON array of 8 objects sorted by `func_index`, each containing:
- `func_index` (int): 0–7
- `verdict` (string): `"correct"` or `"buggy"`
- `actual_operation` (string): one of `"sdiv"`, `"udiv"`, `"smod"`, `"umod"`
- `actual_divisor` (int): the divisor the function actually implements
- `bug_category` (string, buggy only): `"signedness_mismatch"`, `"wrong_divisor"`, or `"wrong_operation"`
- `witness_input` (int, buggy only): an input where actual output ≠ specified output

**`/app/remediation.json`** — Severity evaluation for each bug. Compute `error_count`: the exact number of inputs across the full signed 32-bit range [−2³¹, 2³¹−1] that produce incorrect output. This requires mathematical analysis of the bug's error domain, not brute-force enumeration. Assign severity per the criteria in README.txt. Rank bugs by `error_count` descending, breaking ties by lower `func_index`.

```json
{
  "bugs": [
    {
      "func_index": 0,
      "severity": "critical",
      "error_count": 0,
      "priority_rank": 1
    }
  ]
}
```

**`/app/challenge_fixed`** — A corrected executable binary with the same CLI interface (`./challenge_fixed <func_index> <value>`) where every function matches the specification. All buggy functions must be fixed; all correct functions must remain correct.