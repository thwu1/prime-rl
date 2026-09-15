The OCaml project at `/app/` contains a Menhir-based parser for a mini functional language supporting let bindings, if-then-else, lambdas, function application, arithmetic, comparisons, logical operators, sequences, and unary minus. The grammar (`src/parser.mly`), lexer (`src/lexer.mll`), and AST definition (`src/ast.ml`) are complete and conflict-free. The build system is configured with Menhir's `--table` and `--inspection` flags, and `menhirLib` is available as a library dependency.

The current driver (`src/driver.ml`) uses the monolithic parser API: it stops at the first syntax error, outputs no AST, and gives only "syntax error" as a message. Rewrite the driver so the executable (built via `dune build`, invoked as `/app/_build/default/src/driver.exe`) reads source code from stdin and writes a single JSON object to stdout.

**Success output:** `{"status":"ok","ast":<ast-json>}`

**Error output:** `{"status":"error","errors":[{"line":<int>,"col":<int>,"message":"<string>"},...]}`

**AST JSON schema** (recursive `<expr>`):
- Integer: `{"tag":"int","value":<int>}`
- Boolean: `{"tag":"bool","value":<bool>}`
- Variable: `{"tag":"var","name":"<string>"}`
- Binary op: `{"tag":"binop","op":"<op>","left":<expr>,"right":<expr>}` — ops: `+`, `-`, `*`, `/`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `&&`, `||`
- Unary minus: `{"tag":"neg","expr":<expr>}`
- Let: `{"tag":"let","name":"<string>","bind":<expr>,"body":<expr>}`
- If: `{"tag":"if","cond":<expr>,"then":<expr>,"else":<expr>}`
- Lambda: `{"tag":"fun","param":"<string>","body":<expr>}`
- Application: `{"tag":"app","fn":<expr>,"arg":<expr>}`
- Sequence: `{"tag":"seq","first":<expr>,"second":<expr>}`

**Error recovery requirements:**
- Switch from the monolithic API to Menhir's incremental table-based API with error introspection to recover from syntax errors and continue parsing, collecting all errors in a single pass.
- After detecting an error, resume parsing the remaining input to find additional errors. The recovery must not skip too aggressively — each distinct error site in the input must be reported independently.
- Detect at least 2 independent errors in inputs like `1 + ; 2 + ; 3` and `+ ; *`.
- Error messages must be context-sensitive: use the incremental API's inspection capabilities to determine what tokens the parser expected at the error point. Each message must be at least 16 characters long, must not be just "syntax error", and should contain "unexpected" or "expected" phrasing.
- Positions (`line`, `col`) are 1-based and point to the offending token.

**Success criteria:**
1. `dune build` succeeds.
2. Valid programs produce correct AST JSON matching the schema.
3. Erroneous programs produce error JSON with accurate positions and descriptive messages.
4. Multiple errors at distinct positions are all detected in one pass.
