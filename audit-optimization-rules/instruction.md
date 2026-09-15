`/app/rules.txt` contains sixteen proposed algebraic rewrite rules for a compiler's pattern-matching optimizer, modeled after GCC's `match.pd` transformation engine. Unlike a pure unsigned audit, these rules span `uint32_t`, `int32_t`, and `uint16_t` types — introducing signed integer overflow (undefined behavior per C17) and C integer promotion semantics as critical correctness dimensions.

Classify each rule into one of three verdicts:

- **correct**: The transformation is valid for all inputs satisfying stated preconditions, and no sub-expression can trigger undefined behavior.
- **incorrect**: Concrete inputs exist where LHS ≠ RHS without any undefined behavior occurring.
- **undefined_behavior**: Some inputs cause a sub-expression to trigger undefined behavior (signed overflow, division overflow, or overflow induced by implicit integer promotion from narrow unsigned types to signed `int`), making the rule unsafe for compiler optimization regardless of whether the mathematical identity holds.

Produce:

1. `/app/verdict.json` — one entry per rule (`rule_1` through `rule_16`):
```json
{
  "rule_N": {
    "verdict": "correct" | "incorrect" | "undefined_behavior",
    "witness": null | {"a": <int>, "b": <int>} | {"a": <int>, "n": <int>} | {"a": <int>}
  }
}
```
Correct rules must have `witness: null`. Incorrect rules must provide concrete values where LHS ≠ RHS. UB rules must provide values that trigger undefined behavior. Use key `"n"` for shift-amount parameters, `"b"` for second operands.

2. For each non-correct rule, a file `/app/proof/rule_N.c` — a self-contained C program that demonstrates the defect. For incorrect rules: evaluate LHS and RHS with witness values and print a line beginning with `FAIL` when they differ. For UB rules: detect the overflow condition (e.g., using `__builtin_add_overflow` or `__builtin_mul_overflow`) and print a line beginning with `FAIL` when overflow is confirmed. All proof programs must compile with `gcc -O0` and exit with code 0.