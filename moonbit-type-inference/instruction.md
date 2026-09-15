Implement a type inference engine as a MoonBit project at `/app/`.

A MoonBit project skeleton exists at `/app/` with `moon.mod.json`, `moon.pkg.json`, and a pre-written whitebox test file `hm_wbtest.mbt` containing 15 test cases. Implement all source code needed so that `moon test` passes with all 15 tests succeeding.

The MoonBit toolchain (`moon`) is pre-installed at `/root/.moon/bin/`. If `moon` is not on your PATH, add it with `export PATH="/root/.moon/bin:$PATH"`. If the toolchain is missing, install it with `curl -fsSL https://cli.moonbitlang.com/install/unix.sh | bash`.

You must implement a function `infer_type(expr : String) -> String` in the root package that parses an S-expression-based expression language and returns the inferred type as a string, or `"TYPE ERROR"` if type inference fails.

**Expression language syntax:**
- Integer literals: `42`, `-3`
- Boolean literals: `true`, `false`
- Variables: `x`, `foo`
- Lambda abstractions: `(fn x body)`
- Function application: `(f arg)`
- Let bindings: `(let x def body)`
- Recursive let bindings: `(letrec f def body)`
- Conditionals: `(if cond then else)`
- Binary operators: `(+ a b)`, `(- a b)`, `(* a b)`, `(== a b)`, `(< a b)`

**Type output format:**
- Base types: `Int`, `Bool`
- Function types: right-associative arrows, e.g. `a -> b -> c` means `a -> (b -> c)`. Parenthesize the left side of an arrow if and only if it is itself a function type, e.g. `(a -> a) -> a -> a`
- Type variables: named `a`, `b`, `c`, ..., `z` in order of first appearance during a left-to-right depth-first traversal of the final inferred type
- On any error (parse error, unbound variable, type mismatch, or infinite types like `(fn x (x x))`): return `"TYPE ERROR"`

**Typing rules:**
- Arithmetic operators (`+`, `-`, `*`) require `Int` operands and return `Int`
- Comparison operators (`==`, `<`) require `Int` operands and return `Bool`
- `if` requires a `Bool` condition; both branches must have the same type
- `let` bindings produce polymorphic types: `(let id (fn x x) ...)` allows `id` to be used at different types within the body
- `letrec` bindings support self-referencing definitions
- All implementation `.mbt` files go in `/app/` (root package alongside the test file)
- Run `moon test` to verify