# EAMxx Namelist Parameter Resolution Engine — Specification

## Overview

The parameter resolution engine reads a hierarchical XML configuration file
(`namelist_defaults.xml`) containing parameter definitions with conditional
selectors. It resolves parameter values based on case environment variables and
provides methods for querying, modifying, tracing, comparing, and exporting
parameters.

## XML Format

### Selectors

```xml
<selectors>
  <selector name="hgrid" case_env="ATM_GRID"/>
  <selector name="nlev" case_env="CMAKE_OPTIONS" regex=".*NUM_VERTICAL_LEV\s+(\d+).*"/>
</selectors>
```

- **name**: Short name used in parameter element attributes.
- **case_env**: Key in the case environment dict to read.
- **regex** (optional): Applied to the case_env value; the **first captured
  group** becomes the selector value. If omitted the raw value is used. If the
  regex does not match, the selector evaluates to `None`.

### Parameters vs Groups

- A **group** is an XML element whose children are other groups or parameters.
  Groups have no meaningful text content — only hierarchy.
- A **parameter** is an XML element with text content representing a value.
  A parameter may have multiple elements with the same tag name under the same
  parent: one unselectored (the default) and zero or more with selector
  attributes (conditional overrides).

### Metadata Attributes

Present on the default (first unselectored) element of a parameter:

| Attribute       | Description |
|-----------------|-------------|
| `type`          | `integer`, `real`, `logical`, `string`, `file`, `array(string)` |
| `constraints`   | Validation constraint expression (see below) |
| `valid_values`  | Comma-separated list of allowed values |
| `locked`        | `"true"` → parameter cannot be modified via set/append/remove |
| `doc`           | Documentation string |

These five attributes (`type`, `constraints`, `valid_values`, `locked`, `doc`)
are **metadata** — they are NOT selector conditions. Selectored override
elements inherit the metadata from the default element and should not repeat it.

## Resolution Rules

### Selector Matching on Parameter Elements

Every XML attribute on a parameter element that is **not** a metadata key
is treated as a selector/env condition.

1. **Named selector** (attribute name matches a defined selector name):
   The attribute value is compared to the resolved selector value.
   - **Exact match**: `hgrid="ne30pg2"` matches if the hgrid selector resolved
     to `"ne30pg2"`.
   - **Pipe alternation**: `hgrid="ne30pg2|ne120pg2"` matches if the hgrid
     selector resolved to `"ne30pg2"` OR `"ne120pg2"`. Split on `|`, match
     if any alternative equals the resolved value.

2. **Case-env key** (attribute name matches a key in case_env but is not a
   defined selector): The attribute value is used as a **regex** matched
   against the full case-env value (`re.fullmatch` semantics).

3. **Negation**: An attribute value starting with `!` negates the match.
   Strip `!` before matching, then invert the result.

4. **Conjunction**: When an element has **multiple** selector attributes,
   **all** must match (logical AND).

### Precedence

1. All elements for a given parameter tag under the same parent are scanned
   in **document order**.
2. The unselectored (default) element provides the initial value.
3. Each subsequent selectored element that matches **overwrites** the value.
4. **Last matching element wins.**
5. If there is no default and no selectored element matches, the parameter
   is omitted (undefined).

## Constraint Syntax

### Single constraints

| Operator       | Meaning            |
|----------------|--------------------|
| `gt N`         | value > N          |
| `ge N`         | value >= N         |
| `lt N`         | value < N          |
| `le N`         | value <= N         |
| `ne N`         | value != N         |
| `mod N`        | value % N == 0     |
| `mod N eq M`   | value % N == M     |

### Compound constraints

- `c1 @@ c2` — logical AND (all must pass)
- `c1 || c2` — logical OR (any must pass)

Example: `"gt 0 @@ mod 300 eq 0"` → value > 0 AND value is a multiple of 300.

## Variable Substitution

String and file values may contain `${VAR}` placeholders:

1. Check case environment variables (e.g., `${DIN_LOC_ROOT}`).
2. Check resolved selector values **case-insensitively** (e.g., `${HGRID}` →
   value of the `hgrid` selector; `${NLEV}` → value of the `nlev` selector).
3. If no match, leave `${VAR}` as-is.

## Type Inference and Parsing

When the `type` attribute is not specified on the metadata element, the type
must be inferred from the resolved text value:

| Pattern               | Inferred type   |
|-----------------------|-----------------|
| `true` / `false`      | `logical`       |
| Contains `,`          | `array(string)` |
| Matches `[0-9]+`      | `integer`       |
| Matches float/sci     | `real`          |
| Anything else         | `string`        |

Type parsing:

| Type            | Python type   | Notes |
|-----------------|---------------|-------|
| `integer`       | `int`         | |
| `real`          | `float`       | Supports scientific notation (`740.0e3`) |
| `logical`       | `bool`        | `"true"` → `True`, `"false"` → `False` (case-insensitive) |
| `string`        | `str`         | Variable substitution applied |
| `file`          | `str`         | Variable substitution applied |
| `array(string)` | `list[str]`   | Split on `,`, strip whitespace |

## Python API

Implement `class NamelistResolver` in `/app/resolver.py`:

```python
class NamelistResolver:

    def __init__(self, xml_path: str, case_env: dict[str, str]):
        """Parse XML and resolve all parameters for the given case environment."""

    def get(self, param_path: str) -> Any:
        """
        Get the resolved value.

        param_path formats:
          - Full dot-separated path: "atmosphere.dynamics.time_step"
          - Unambiguous short name:  "time_step"
          - Scoped with `::`:        "microphysics::subcycles"

        Raises:
          KeyError   — parameter not found
          ValueError — ambiguous (multiple matches)
        """

    def get_metadata(self, param_path: str) -> dict:
        """
        Return dict with keys:
          value, type, constraints, valid_values, locked, doc, group_path
        """

    def query(self, pattern: str) -> list[str]:
        """Return sorted list of full param paths matching a regex (re.search)."""

    def set(self, param_path: str, value: str) -> None:
        """
        Set a parameter. The string is parsed to the parameter's type.
        Raises:
          ValueError      — constraint or valid_values violation
          PermissionError  — parameter is locked
        """

    def append(self, param_path: str, value: str) -> None:
        """
        Append to an array parameter.
        Raises TypeError if not array, PermissionError if locked.
        """

    def remove(self, param_path: str, value: str) -> None:
        """
        Remove from an array parameter.
        Raises TypeError if not array, ValueError if element absent,
        PermissionError if locked.
        """

    def list_params(self, group_path: str = "") -> list[str]:
        """Return sorted list of full param paths, optionally under group_path."""

    def to_yaml(self) -> str:
        """
        Generate YAML string of all resolved parameters,
        preserving the hierarchical group structure.
        """

    def explain(self, param_path: str) -> dict:
        """
        Return a resolution trace showing how a parameter got its value.

        Returns:
            {
                "path": "<full dot path>",
                "final_value": <resolved value>,
                "type": "<type string>",
                "elements": [
                    {
                        "text": "<raw XML text>",
                        "selectors": {<attr_name: attr_value>, ...},
                        "matched": <bool>,
                        "is_winner": <bool>
                    },
                    ...
                ]
            }

        Elements are listed in document order. Only elements with text
        content are included. `selectors` contains the non-metadata XML
        attributes exactly as written. `matched` indicates whether all
        selectors on that element were satisfied. `is_winner` is True
        for exactly one element: the last matched one (which determined
        the final value).

        Raises:
          KeyError   — parameter not found
          ValueError — ambiguous
        """

    def diff(self, other: 'NamelistResolver') -> dict:
        """
        Compare resolved parameters with another resolver instance.

        Returns:
            {
                "changed": {
                    "<path>": {"self": <value>, "other": <value>},
                    ...
                },
                "only_self": [<path>, ...],
                "only_other": [<path>, ...]
            }

        `changed` includes parameters present in both but with different
        values. `only_self` lists parameters in self but not other.
        `only_other` lists parameters in other but not self.
        All keys in `changed` and all lists are sorted.
        """
```
