# TTCN-3 Template Matching Semantics Reference

Based on ETSI ES 201 873-1 (TTCN-3 Core Language).

## Template Format (JSON)

Templates are JSON objects with a `"t"` key identifying the match type.
A plain value (not a dict, or a dict without `"t"`) is shorthand for exact match.

## Matching Mechanisms

### Exact (`{"t":"exact","v":<value>}`)
Value must equal `v`. Booleans are type-strict (`True != 1`).
Int/float cross-compare is allowed (`42 == 42.0`).

### AnyValue (`{"t":"any"}`)
Matches any **present** value. Fails on None/absent. TTCN-3 `?`.

### AnyOrNone (`{"t":"any_or_none"}`)
Matches anything including absent/None. TTCN-3 `*`.
In record-of context, matches zero or more contiguous elements.

### Omit (`{"t":"omit"}`)
Matches only absent values (None). Fails on any present value.

### Complement (`{"t":"complement","list":[<tmpl>,...]}`)
Matches any **present** value that does NOT match any template in `list`.
An absent/None value always fails complement matching — the complement
operator requires a present value to test against the exclusion list.

### Range (`{"t":"range","lo":<num>,"hi":<num>}`)
Matches numeric values in [lo, hi] inclusive.
Rejects non-numeric types including strings and None.
Boolean values are explicitly excluded from range matching despite
Python's `bool` being a subclass of `int` — ranges operate on
protocol-level numeric values, not truth values.

### Record (`{"t":"record","fields":{...}}`)
Each field spec: `{"tmpl":<template>, "opt":<bool>}`.

**Absent field** (key not in value dict):
- Mandatory (`opt: false`): always fail
- Optional (`opt: true`): pass if template is `omit`, `any_or_none`, or `ifpresent`; otherwise fail

**Present field**: Template `omit` → fail. Otherwise match field value against template.

**Extra fields** in value not in template → fail (except `_`-prefixed internal keys).

### Record-of / List (`{"t":"list","items":[<tmpl>,...]}`)
Left-to-right matching against value elements:
- Regular template: matches exactly one element at current position
- `any_or_none` (`*`): matches zero to N contiguous elements — the engine must
  explore all possible consumption lengths via backtracking
- `permutation`: matches N contiguous elements in any order

Multiple `*` items can appear, requiring nested backtracking across all
possible split points.

### Pattern (`{"t":"pattern","expr":<string>}`)
TTCN-3 charstring patterns (NOT regular expressions):

| Element   | Meaning                                        |
|-----------|------------------------------------------------|
| `?`       | Any single character                           |
| `*`       | Any string (zero or more characters)           |
| `\d`      | Digit `[0-9]`                                  |
| `\w`      | Letter `[a-zA-Z]` (not digits, not underscore) |
| `#(n)`    | Exactly n of preceding element                 |
| `#(n,m)`  | n to m of preceding element                    |
| `[abc]`   | Character class                                |
| `[^abc]`  | Negated class                                  |
| `.`       | Literal dot (NOT a wildcard)                   |

Patterns are implicitly anchored (must match entire string).
`\?` and `\*` match literal `?` and `*` characters.

### IfPresent (`{"t":"ifpresent","inner":<tmpl>}`)
Matches if value is absent (None) OR if present value matches inner template.

### Length (`{"t":"length","inner":<tmpl>,"lo":<int>,"hi":<int|null>}`)
Value must satisfy length bounds AND match inner template.
`hi: null` means unbounded. Applies to strings, lists, set-of.

### Subset (`{"t":"subset","members":[<value>,...]}`)
For set-of values (`{"_set": [...]}`). Every element must be in members.

### Superset (`{"t":"superset","members":[<value>,...]}`)
For set-of values. Every member must appear in value's elements.

### Permutation (`{"t":"permutation","items":[<tmpl>,...]}`)
Standalone: matches list of same length with elements in any order.
Inside list template: matches contiguous subsequence in any order.

### Template Modification (`{"t":"modifies","base":<name>,"delta":{...}}`)
Inherits all fields from named base template (resolved from registry),
overrides fields in delta. Supports chaining. Only for record templates.
The base template in the registry must never be mutated by the modification
process — the engine must create a fully independent copy before applying
the delta overrides.

## Value Representation

- **Primitives**: int, float, str, bool
- **Record**: dict (keys are field names)
- **Record-of**: list
- **Set-of**: `{"_set": [<value>, ...]}`
- **Absent**: None

## Verdict Resolution

Five verdict levels with strict total ordering:

    none(0) < pass(1) < inconc(2) < fail(3) < error(4)

Rules:
1. Each test component starts with verdict `none`
2. `set_verdict(v)` is monotonically increasing: `local = max(local, v)`
3. Test case verdict = maximum of all component verdicts
4. Component identity is immutable once created — re-creating an existing
   component must not reset its accumulated verdict state
