A Java application at `/app/` partially implements a FEEL decision table engine per DMN 1.4. Given a decision table definition (JSON) and input values (JSON), it evaluates FEEL unary tests to determine matching rules, applies the hit policy, and produces the result as JSON.

**Build and run:**
```
/app/build.sh
/app/run.sh <table.json> <input.json>
```

The engine has defects in its evaluation pipeline and is missing the PRIORITY hit policy. Fix all defects and implement missing functionality so the engine conforms to the DMN 1.4 specification.

**Unary test evaluation requirements:**
- Range intervals `[a..b]`, `(a..b]`, `[a..b)`, `(a..b)` — bracket notation determines boundary inclusivity
- Negation `not(expr)` inverts the inner result; `not(null)` remains `null`
- Comma-separated tests are disjunctions (OR): true if any individual test matches
- Null input to any comparison or range test must yield `null` per FEEL ternary logic, not `false`

**All six hit policies must be supported:**
- `UNIQUE` — exactly zero or one match; `{"_error": "..."}` if multiple rules match
- `ANY` — all matches must produce identical output; `{"_error": "..."}` if outputs differ
- `FIRST` — first match in rule definition order
- `PRIORITY` — when multiple rules match, return the output whose first output-column value has the highest priority (earliest index in that column's `outputValues` list)
- `RULE_ORDER` — all matches as a JSON array in rule definition order
- `COLLECT`+`NONE` — all outputs as a JSON array
- `COLLECT`+`SUM`/`MIN`/`MAX` — aggregate first output column with decimal-precise arithmetic
- `COLLECT`+`COUNT` — count of matched rules

**Decision table JSON schema:**
```json
{
  "hitPolicy": "UNIQUE|ANY|FIRST|PRIORITY|RULE_ORDER|COLLECT",
  "aggregation": "NONE|SUM|MIN|MAX|COUNT",
  "inputs": [{"name": "x", "type": "number|string|boolean|date"}],
  "outputs": [{"name": "y", "type": "...", "outputValues": ["high","med","low"]}],
  "rules": [{"inputs": ["<unary-test>", ...], "outputs": ["<literal>", ...]}]
}
```

The `outputValues` array on an output column defines priority ordering for `PRIORITY` (index 0 = highest priority). It may be absent for other hit policies.

**Input:** `{"x": value, ...}` — `null` represents missing data.

**Output:** JSON object for single-result policies, JSON array for multi-result, `{"_error":"msg"}` for violations, `null` when no rules match.
