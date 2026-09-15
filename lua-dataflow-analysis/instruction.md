The Lua static analyzer at `/app/lua_analyzer/analyze.lua` detects uninitialized local variable accesses in Lua source files. It runs a four-stage pipeline: parse, linearize, resolve_locals, detect_uninit_accesses. The first two stages are fully implemented. The last two are stubs that produce no output.

Complete these two files so the analyzer correctly identifies all uninitialized variable accesses:

- `/app/lua_analyzer/stages/resolve_locals.lua`
- `/app/lua_analyzer/stages/detect_uninit_accesses.lua`

**Do not modify** any other files under `/app/lua_analyzer/`.

**Invocation:**

```
lua5.4 /app/lua_analyzer/analyze.lua <source_file>
```

**Output:** A JSON array of warning objects sorted by `(line, column, code)`. Each warning has exactly four string/integer fields:

```json
[{"code":"321","name":"x","line":7,"column":12}]
```

**Warning codes:**

- `"321"` — reading a local variable whose reaching definitions are all uninitialized
- `"341"` — mutating (e.g., field-setting on) a local variable whose reaching definitions are all uninitialized

**Semantic rules governing when warnings fire:**

1. A warning is emitted only when **every** reaching definition at the access point is the implicit empty initial value (uninitialized). If any reaching definition is a real assignment, no warning.
2. If an access has **no** reaching definitions (the code is unreachable — e.g., after `do return end`), no warning is emitted for that access.
3. If a variable has exactly **one** value definition total (the implicit empty initial value) and is accessed, it is treated as "never set" (a separate diagnostic category) and must **not** produce a 321 or 341 warning.
4. Assignments inside closures that set upvalues count as reaching definitions for accesses to those variables in the enclosing scope and in other closures. A closure assigning an upvalue prevents a false 321 at the main-line access.
5. In partial-initialization branching (e.g., `if/elseif/else` where only some branches assign the variable), the access after the branch has both empty and non-empty reaching values — rule 1 means no warning fires.
6. `goto`/label control flow: assignments between a `goto` and its target label still propagate as reaching definitions beyond the label. An access after the label that has both the empty initial value and the skipped assignment as reaching values does not trigger a warning.
7. Numeric and generic `for` loop control variables are always considered initialized.

**Input edge cases:**

- Empty input → `[]`
- Unparseable input (syntax errors) → `[]`

**Control-flow coverage required:** `if`/`elseif`/`else`, `while`, `repeat`/`until`, numeric and generic `for`, nested closures with upvalue semantics, `goto`/labels, early returns, and multiple assignment with unpacking.

**Success criteria:** All tests pass when `/tests/test.sh` is executed.
