A complete set of 78 formal Structural Operational Semantics (SOS) rules is provided at `/app/semantics/rules.txt` for a simple imperative language called IMP. These SOS rules define **nonstandard semantics** where certain operators have been silently remapped from their usual mathematical behavior. You must determine the remappings by reading the formal rules.

A Lark parser grammar for IMP is provided at `/app/imp.lark`. The Lark library (Python) is pre-installed. `check-jsonschema` and `jq` are also available.

Build a working interpreter that faithfully implements the given SOS rules as a **small-step abstract machine**. For each IMP program in `/app/programs/`, your interpreter must produce:

1. **Final state**: the terminal variable store (or `"ERROR"` if the program reaches an error state)
2. **Step count**: the total number of abstract machine transitions taken
3. **Rule histogram**: for each transition, record the **innermost rule** applied in the derivation tree (the leaf/axiom rule that performs the actual computation or state change). The histogram maps rule numbers to their frequency counts.

Additionally, analyze the SOS rules holistically and extract the **operator mapping** — what mathematical operation each syntactic operator actually computes under the nonstandard semantics.

Write results to `/app/results.json` conforming to the JSON schema at `/app/schema/output_schema.json`. Validate your output against the schema using `check-jsonschema`.

Output format:
```json
{
  "operator_mapping": {
    "binary_+": "<actual_operation>",
    "binary_-": "<actual_operation>",
    "binary_*": "<actual_operation>",
    "binary_/": "<actual_operation>",
    "binary_%": "<actual_operation>",
    "unary_+": "<actual_operation>",
    "unary_-": "<actual_operation>",
    "<": "<actual_operation>",
    "<=": "<actual_operation>",
    ">": "<actual_operation>",
    ">=": "<actual_operation>",
    "==": "<actual_operation>",
    "!=": "<actual_operation>",
    "&&": "<actual_operation>",
    "||": "<actual_operation>",
    "!": "<actual_operation>"
  },
  "programs": {
    "<filename_without_ext>": {
      "final_state": {"var": value, ...} or "ERROR",
      "step_count": <integer>,
      "rule_histogram": {"<rule_number>": <count>, ...}
    }
  }
}
```

Use canonical names for operations: `subtraction`, `addition`, `division`, `multiplication`, `modulo`, `negation`, `identity`, `greater_than`, `greater_equal`, `less_than`, `less_equal`, `not_equal`, `equal`, `conjunction`, `disjunction`.

Semantics notes:
- Each abstract machine transition applies exactly one derivation tree of SOS rules. The **innermost rule** is the deepest rule in the tree (the one that actually performs work: variable lookup, arithmetic, comparison, branching, or control flow state change).
- Structural/congruence rules (e.g., "reduce sub-expression in context") are the outer part of the derivation; their innermost leaf is what gets recorded.
- Axiom rules (rules with only side-conditions, no derivation premises) are their own innermost rule.
- All integer arithmetic uses truncation toward zero for division.
- The store maps variable names to integer values; `int x` initializes `x` to 0.
- `halt` produces a terminal configuration. `break`/`continue` outside a loop produce `ERROR`.