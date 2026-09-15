The expression evaluator at `/app/` compiles expressions to bytecode and executes them on a stack-based VM. The pipeline is: lexer/parser (`parse.go`) → compiler (`compile.go`) → VM (`vm.go`). `parse.go` and `main.go` are correct and must not be modified.

The evaluator currently fails on many expression types. Your goal is to make it pass all tests by fixing bugs in `/app/compile.go` and `/app/vm.go`, and by implementing missing functionality.

**What must work:** integer/string literals, booleans, `nil`, arithmetic (`+`,`-`,`*`,`/`,`%`), comparisons, unary (`-`,`!`), short-circuit `&&`/`||`, ternary `? :`, nil coalescing `??`, inclusive range `a..b`, `val in collection` (arrays and maps), array/map literals, indexing, `len()`, and iterator builtins: `filter`, `map`, `any`, `all`, `count`, `reduce`. These builtins use predicate syntax where `#` is the current element, `#acc` is the accumulator (for `reduce`), and `#index` is the iteration index.

**Disassembler** (`/app/disasm.go`): Implement `Disassemble(prog *Program) string` producing a bytecode listing. Each instruction on one line:

```
ADDR OPNAME ARG[    ; CONSTVAL]
```

`ADDR`: zero-padded 4-digit decimal address. `OPNAME`: opcode identifier matching the constant names in `compile.go` (e.g., `OpPush`). The `; CONSTVAL` suffix appears only for `OpPush` and `OpLoadEnv`, showing the constant value (strings quoted). `main.go` already handles the `--disasm` flag.

**Verification:**
- `go build -o /app/evaluator .` in `/app/` succeeds.
- The evaluator accepts JSON on stdin (`{"expr": "...", "env": {...}}`) and outputs the result as JSON.
- All expression types listed above produce correct results, including nested compositions of iterator builtins over ranges.
- `--disasm` produces correctly formatted bytecode listings.
