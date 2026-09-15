# Validation Script Framework

The `validation_trees/` and `rule_scripts/` directories implement a JSON-driven validation framework for enforcing business rules on request payloads. The framework decouples validation logic from application code — rules are defined as data structures.

## Components

### Validation Trees (`validation_trees/`)

Validation trees define *where* and *when* rules are applied. They map payload structure to rule scripts.

**Node Types:**
- `rootNode`: entry point; has `nodeData` with `vsfScriptFiles` and child `nodes`
- `leaf`: maps a property (`internalIdentifier`) to rule scripts
- `parent`: nested object containing its own `nodes`
- `list`: a collection; may define rules for the list itself and per-item rules via `listItem`

**Execution hooks on `list` nodes:**
- `listItem.branchNodeData.runBeforeListItem`: scripts run before each item
- `listItem.branchNodeData.runAfterListItem`: scripts run after each item

**Control flow:**
- `vsfScriptFiles[].scriptFile`: path to a rule script (relative to `rule_scripts/`)
- `vsfScriptFiles[].breakOnError`: if `true` (default), stop on first failure

### Rule Scripts (`rule_scripts/`)

Each script has a `vsfScript` array of lines. Line types:

| lineType       | Behavior |
|----------------|----------|
| `Rule`         | Evaluate `parameters.ruleText` as a boolean expression; fail validation if false |
| `Assert`       | Same as Rule — evaluate expression, fail if false |
| `ImportScript` | Load and execute `parameters.scriptFile` |
| `State`        | Store `parameters.value` expression result under `parameters.key` in context |
| `Branch`       | Conditional: `conditions` array of `{if/elseif/else, then}` blocks |
| `Information`  | No-op (diagnostic logging) |

**Branch conditions:** Each `if`/`elseif` block has `scriptLines` evaluated as a boolean test. If all lines pass (no errors), the condition is met and the corresponding `then.scriptLines` execute. An `else` block runs if no prior condition matched.

### Expression Language

Rule text uses C#-like syntax evaluated against a context containing:
- `currentProperty`: the value of the field being validated
- `parentProperty`: the parent object

Supported operations:
- Dot access: `parentProperty.fieldName`
- Comparisons: `==`, `!=`, `>=`, `<=`, `>`, `<`
- Logical: `&&`, `||`
- Literals: `null`, `true`, `false`
- Properties/methods: `.Length`, `.Count()`, `.Trim()`
