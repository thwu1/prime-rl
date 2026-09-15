# ChocoPy Type Summary JSON Format

The type checker must return a JSON object with this exact structure:

```json
{
  "well_typed": <boolean>,
  "globals": {
    "<name>": {"type": "<type_string>", "kind": "var"|"func"}
  },
  "classes": {
    "<name>": {
      "superclass": "<class_name>",
      "attributes": {"<name>": "<type_string>"},
      "methods": {"<name>": "<signature_string>"}
    }
  },
  "errors": [
    {"message": "<error description>"}
  ]
}
```

## Type String Format

| Type | String |
|------|--------|
| Integer | `"int"` |
| Boolean | `"bool"` |
| String | `"str"` |
| Object | `"object"` |
| None type | `"<None>"` |
| Empty type | `"<Empty>"` |
| List of T | `"[T]"` (e.g., `"[int]"`, `"[[str]]"`) |
| User class | Class name (e.g., `"Counter"`, `"Animal"`) |
| Function | `"(param_types) -> return_type"` (e.g., `"(int, str) -> bool"`, `"() -> object"`) |

## Rules

- `globals` contains only user-defined global variables and functions (not built-ins like `print`, `input`, `len`).
- `classes` contains only user-defined classes (not `object`, `int`, `bool`, `str`).
- `attributes` lists only attributes directly defined on that class (not inherited).
- `methods` lists only methods directly defined on that class (not inherited). Include `__init__` only if explicitly defined in the class body.
- Method signatures include the `self` parameter type (e.g., `"(Counter) -> int"` for a method with only self).
- `errors` is an empty list when `well_typed` is `true`.
- When `well_typed` is `false`, `globals` and `classes` contain whatever was successfully collected before the error was detected (may be partial depending on which phase detected the error).
