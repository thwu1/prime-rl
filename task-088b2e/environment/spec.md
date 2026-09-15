# TTCN-3 Template Matching Engine — Specification

## Overview

Implement a TTCN-3 template matching engine in Python based on the matching semantics
defined in ETSI ES 201 873-1 (TTCN-3 Core Language). TTCN-3 (Testing and Test Control
Notation version 3) is a standardized testing language used in conformance testing of
communicating systems (SIP, Diameter, oneM2M, etc.). Its template matching system is the
core mechanism for verifying that protocol messages conform to specifications.

Your engine must handle 14 distinct matching mechanisms and a verdict resolution system.

## Template Format (JSON)

Templates are JSON objects with a `"t"` key identifying the match type:

| Type          | Format                                                        | Semantics |
|---------------|---------------------------------------------------------------|-----------|
| exact         | `{"t":"exact","v":<value>}`                                   | Value must equal `v` exactly. Booleans must match type (True ≠ 1). Int/float cross-compare allowed (42 == 42.0). |
| (shorthand)   | plain value (int/float/str/bool)                              | Equivalent to `{"t":"exact","v":<value>}`. A template that is not a dict or has no `"t"` key is treated as exact match. |
| any           | `{"t":"any"}`                                                 | Matches any **present** value (not None/absent). TTCN-3 `?`. |
| any\_or\_none | `{"t":"any_or_none"}`                                         | Matches anything including absent/None. In record-of context, matches zero or more elements. TTCN-3 `*`. |
| omit          | `{"t":"omit"}`                                                | Matches only absent values (None). |
| complement    | `{"t":"complement","list":[<tmpl>,...]}`                      | Matches any **present** value that does NOT match any template in `list`. None → False. |
| range         | `{"t":"range","lo":<num>,"hi":<num>}`                         | Matches numeric values in [lo, hi] inclusive. Booleans excluded. Strings → False. |
| record        | `{"t":"record","fields":{<name>:{"tmpl":<tmpl>,"opt":<bool>},...}}` | See Record Matching below. |
| list          | `{"t":"list","items":[<tmpl>,...]}`                           | See Record-of Matching below. |
| pattern       | `{"t":"pattern","expr":<string>}`                             | TTCN-3 charstring pattern matching. See Pattern Syntax below. |
| ifpresent     | `{"t":"ifpresent","inner":<tmpl>}`                            | Matches inner template OR absent (None). Only meaningful for optional record fields. |
| length        | `{"t":"length","inner":<tmpl>,"lo":<int>,"hi":<int or null>}` | Value must satisfy length constraint AND match inner template. Applies to strings, lists, and set-of. `hi` null means unbounded. |
| subset        | `{"t":"subset","members":[<value>,...]}`                      | Value must be a set-of where every element is in `members`. |
| superset      | `{"t":"superset","members":[<value>,...]}`                    | Value must be a set-of containing at least all `members`. |
| permutation   | `{"t":"permutation","items":[<tmpl>,...]}`                    | Standalone: matches a list of same length with elements in any order. Inside `list`: matches a contiguous subsequence in any order. |
| modifies      | `{"t":"modifies","base":<string>,"delta":{<field>:<tmpl>,...}}` | Inherits from named base template (looked up in registry), overrides fields in `delta`. Supports chaining. Only for record templates. |

## Value Format

- **Primitives**: `int`, `float`, `str`, `bool` — used directly
- **Record**: `dict` — keys are field names, values are field values. A field is **absent** if its key does not exist in the dict.
- **Record-of** (ordered list): `list`
- **Set-of** (unordered): `{"_set": [<value>, ...]}` — the `_set` key marks set-of values
- **Absent**: `None` — represents an omitted/absent value

Keys starting with `_` in dicts are internal markers and must be ignored during extra-field checks in record matching.

## Record Matching

A record template specifies expected fields. Each field spec has:
- `"tmpl"`: the template for the field value
- `"opt"`: boolean, whether the field is optional in the type definition

**When field is absent** (key not in value dict):
- Mandatory field (`opt: false`): always **fail**
- Optional field (`opt: true`): **pass** if template is `omit`, `any_or_none`, or `ifpresent`; otherwise **fail**

**When field is present**:
- Template is `omit`: **fail** (omit requires absence)
- Otherwise: field value must match the template

**Extra fields**: Any key in value (except `_`-prefixed) that is not in the template → **fail**.

## Record-of (List) Matching

Template items are matched left-to-right against value elements:
- Regular template: matches exactly one element at current position
- `any_or_none` (`*`): matches **zero or more** elements (requires backtracking)
- `permutation`: matches a contiguous subsequence of N elements (where N = number of permutation items) in any order, then continues matching

The matching requires backtracking when `*` is present. Multiple `*` templates can appear in the same list.

## TTCN-3 Pattern Syntax

TTCN-3 charstring patterns differ from regex:

| Pattern Element | Meaning |
|-----------------|---------|
| `?`             | Any single character |
| `*`             | Any string (zero or more characters) |
| `\d`            | Any digit `[0-9]` |
| `\w`            | Any letter `[a-zA-Z]` (NOT digits, NOT underscore) |
| `\n`            | Newline |
| `\t`            | Tab |
| `\\`            | Literal backslash |
| `\?`            | Literal `?` |
| `\*`            | Literal `*` |
| `[abc]`         | Character class |
| `[a-z]`         | Character range |
| `[^abc]`        | Negated character class |
| `#(n)`          | Exactly n repetitions of preceding element |
| `#(n,m)`        | n to m repetitions |
| `#(n,)`         | n or more repetitions |
| `#(,m)`         | 0 to m repetitions |

Within character classes, `\d` expands to `0-9` and `\w` expands to `a-zA-Z`.

Patterns must match the **entire** string (implicitly anchored).

Regular characters (including `.`, `/`, `;`, etc.) are literals — they are NOT regex metacharacters.

## Verdict Resolution

TTCN-3 defines 5 verdict levels with strict ordering:

    none(0) < pass(1) < inconc(2) < fail(3) < error(4)

Rules:
1. Each test component starts with verdict `none`
2. `set_verdict(v)` can only **increase** the local verdict: `local = max(local, v)`
3. The overall test case verdict = maximum of all component verdicts
4. Attempting to decrease a verdict has no effect (not an error)

## Required API

Create `/app/matcher.py` exporting:

```python
def match(template, value, registry=None) -> bool:
    """Match a value against a TTCN-3 template.
    
    Args:
        template: Template definition (dict with "t" key, or primitive for exact match)
        value: Value to match (JSON-compatible, None for absent)
        registry: Dict mapping template names to definitions (for modifies)
    
    Returns:
        True if value matches template
    """

class VerdictResolver:
    """TTCN-3 verdict resolution engine."""
    
    def __init__(self): ...
    def create_component(self, component_id: str): ...
    def set_verdict(self, component_id: str, verdict: str): ...
    def get_verdict(self, component_id: str) -> str: ...
    def get_test_verdict(self) -> str: ...
    def resolve_from_operations(self, operations: list) -> str: ...
```

`resolve_from_operations` processes a list of dicts:
- `{"action": "create", "component": "<id>"}` — create component
- `{"component": "<id>", "verdict": "<verdict>"}` — set verdict

Returns the final overall test verdict.
