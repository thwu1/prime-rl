`/app/lox.py` is a complete tree-walk interpreter for the Lox language (scanning, parsing, variable resolution, evaluation, closures, classes, inheritance). Study it to understand the exact semantics your transpiler must preserve.

Create `/app/lox2js.py` — a transpiler that reads a Lox source file and emits semantically equivalent JavaScript to stdout. When the generated JavaScript is executed with `node`, it must produce identical stdout, stderr content, and exit code as `python3 /app/lox.py <script>`.

**Invocation**: `python3 /app/lox2js.py script.lox > output.js && node output.js`

**Semantic gaps to bridge**:
- Lox truthiness: only `nil` and `false` are falsy (JS also treats `0`, `""`, `undefined` as falsy)
- Lox equality: `nil == nil` is `true`; different types are never equal
- Number formatting: integers print without decimals (`3` not `3.0`)
- `+` requires two numbers or two strings; arithmetic/comparison operators require numbers — mismatches are runtime errors
- Runtime errors: `message\n[line N]` to stderr, exit 70
- Parse/resolve errors: `[line N] Error at 'lexeme': message` to stderr, exit 65
- Resolver detects: top-level `return`, variable used in own initializer, `return <value>` inside `init`
- Classes: `init` constructor returns `this` implicitly; inheritance via `<`; `super.method()` dispatches on the superclass
- `clock()` returns seconds since epoch
- Logical `or`/`and` short-circuit and return the determining value, not a boolean