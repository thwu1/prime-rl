Build a type-checking pipeline for ChocoPy, a statically typed subset of Python 3.6 with classes, inheritance, nested functions, and lists. The formal type system specification is at `/app/chocopy_spec.md`.

Create three artifacts that together form a complete build-and-verify pipeline:

**`/app/typechecker.py`** — Module exporting `type_check(source: str) -> dict`. Must return a type summary JSON object with keys: `well_typed` (bool), `globals` (map of name to `{type, kind}`), `classes` (map of name to `{superclass, attributes, methods}`), `errors` (list of `{message}`). Full format details are in `/app/type_summary_format.md`. Only user-defined classes appear in `classes`; built-in types (object, int, bool, str) are omitted. Built-in functions (print, input, len) are omitted from `globals`. Type string format: `"int"`, `"bool"`, `"str"`, `"[int]"`, `"ClassName"`, `"(int, str) -> bool"`. Method signatures include the self parameter.

**`/app/chocopy_tc`** — Executable CLI wrapper (with shebang) using `argparse`. Accepts a source file path as a positional argument and a `--pretty` flag for indented output. Prints type summary JSON to stdout. Exits 0 if well-typed, 1 if a type error is found.

**`/app/Makefile`** — Based on the skeleton at `/app/Makefile.skeleton`. Must provide these `make` targets:
- `typecheck-all`: Run `chocopy_tc` on every `programs/*.py` file, writing JSON results to `build/`
- `validate`: Use `jq` to verify each JSON result in `build/` has valid structure (all required keys present, correct value types)
- `diff-check`: Normalize each JSON result with `jq -S` and compare against the matching reference in `reference_asts/` using `diff`
- `clean`: Remove `build/`

Running `make typecheck-all && make validate && make diff-check` must succeed with zero differences against the reference typed ASTs in `/app/reference_asts/`.

The type checker must correctly handle: type conformance (subtyping via class hierarchy), assignment compatibility (`<None>` assignable to non-primitive types, `<Empty>` to any list type), join/LUB computation for conditional expressions and list displays, method override validation (return type and non-self parameter types must match exactly), nested function scoping with `nonlocal`/`global` declarations, `is` operator restrictions (operands must not be int, bool, or str), and for-loop element type checking.

Test programs are in `/app/programs/`. Programs prefixed with `err_` contain type errors; all others are well-typed.