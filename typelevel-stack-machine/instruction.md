A type-level stack machine is implemented in TypeScript at `/app/`. It uses TypeScript's type system to encode a stack-based virtual machine with arithmetic, stack manipulation, conditional branching, and a string-to-instruction parser — all computed at the type level with zero runtime code.

Running `npm install && npx tsc --noEmit` in `/app/` produces multiple type errors. The source files in `/app/src/` contain bugs in arithmetic and stack operations that cause type-level computations to produce incorrect results, caught by `Expect<Equal<...>>` assertions in the test files under `/app/tests/`. Additionally, the conditional execution mechanism (`IFZERO`/`ELSE`/`ENDIF`) produces type errors for any program containing these instructions.

**Project structure:**
- `/app/src/arithmetic.ts` — Type-level `Add`, `Subtract`, `Multiply`, `IsZero`
- `/app/src/stack-machine.ts` — `Instruction`, `Step` (single instruction executor), `Execute` (program runner), `Run`
- `/app/src/parser.ts` — String program to instruction tuple type converter
- `/app/tests/` — Test files with `Expect<Equal<actual, expected>>` type assertions

**Stack machine operations:**
- `PUSH N` — push N onto the stack (multi-digit numbers must be supported)
- `ADD` — pop two, push sum
- `SUB` — pop top (a) and second (b), push (b - a)
- `MUL` — pop two, push product
- `DUP` — duplicate top element
- `SWAP` — swap top two elements
- `POP` — discard top element
- `OVER` — copy second element to top: `[a, b, ...] -> [b, a, b, ...]`
- `ROT` — rotate third element to top: `[a, b, c, ...] -> [c, a, b, ...]`
- `IFZERO` — pop top; if zero, execute subsequent instructions; if nonzero, skip until matching `ELSE` or `ENDIF`
- `ELSE` — toggle: if currently executing, skip to matching `ENDIF`; if currently skipping at this nesting level, resume execution
- `ENDIF` — end conditional block

Nested `IFZERO`/`ELSE`/`ENDIF` blocks must work correctly — inner conditionals encountered during a skip must not prematurely trigger the outer block's `ELSE` or `ENDIF`.

**Constraints:**
- Do not modify any files under `/app/tests/`
- Do not define custom `Equal` or `Expect` types; use the `type-testing` package
- All fixes must be in `/app/src/` files only

**Success criterion:** `npx tsc --noEmit` exits with code 0 in `/app/`.
