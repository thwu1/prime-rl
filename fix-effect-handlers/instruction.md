`/app/` contains a working mini interpreter for a language with algebraic effect handlers, inspired by the Effekt research language. The interpreter (`/app/effekt.py`) evaluates AST programs via a free-monad approach, and `python3 /app/run_all.py` passes all 10 test programs in `/app/programs/`.

Your task is to **create a Guile Scheme compilation backend** for this language. Implement:

- `/app/effekt_to_scheme.py` — a Python module exporting `compile_program(ast)` that takes a mini-Effekt AST node (as returned by each program's `build()` function) and returns a string of Guile Scheme code.

- `/app/compile_all.py` — a script that compiles all 10 test programs to Scheme, runs each through Guile, and validates that the compiled output matches the Python interpreter. Must exit 0 on success and print `10/10 tests passed`.

When the generated Scheme code is executed via `guile --no-auto-compile -s <file>`, it must produce output matching the Python interpreter: each `Print`-effect value on its own line, followed by a line containing exactly `---RESULT---`, followed by the final result value formatted as Python would display it (`True`/`False` for booleans, `()` for unit, integers as-is).

The compiler must correctly implement all semantic features exercised by the test programs:
- Deep handler semantics (handlers are reinstalled around resumed continuations)
- Multi-shot continuations (resume invoked more than once in a single handler body)
- Effect propagation through nested handlers (unmatched effects bubble to outer handlers while preserving inner handler context)
- Return clauses that transform the body's natural return value but do not transform handler body results
- Abort (non-resumptive) handlers
- Recursive function bindings (LetRec)

Guile Scheme 3.0 is installed at `/usr/bin/guile`. SRFI-9 record types are available via `(use-modules (srfi srfi-9))`.

Study `/app/effekt.py` to understand the interpreter's free-monad evaluation strategy and the AST node types. All verification tests in `/tests/test_state.py` must pass.