Build a Cool (Classroom Object-Oriented Language) interpreter as a multi-stage pipeline at `/app/coolinterp`. The architecture must use Flex for lexical analysis, compiled into a native tokenizer binary via `gcc` and `make`.

## Required components in `/app/`

- `cool.l` — Flex lexer specification for Cool that handles nested block comments, string escape sequences, case-insensitive keywords, and boolean constants
- `Makefile` — Builds the `tokenizer` binary from `cool.l` using `flex` and `gcc`
- `tokenizer` — Compiled C binary (ELF) produced by `make`; reads a `.cl` source file passed as argument and writes a token stream to stdout
- An evaluator that reads the tokenizer's output from stdin, parses it into an AST, and executes the program according to Cool semantics
- `coolinterp` — Executable entry point that pipes the tokenizer into the evaluator

Usage: `/app/coolinterp program.cl`

## Cool language specification

`/app/cool_reference.txt` contains the complete language reference. Key semantics the interpreter must handle: single inheritance (default parent Object), dynamic dispatch through inheritance chains, static dispatch via `@` operator, `SELF_TYPE` in return types and `new SELF_TYPE`, case expressions matching the closest ancestor type to the runtime type, `let` bindings with proper scoping (initializer evaluated in outer scope), attribute initialization in inheritance order (ancestors first), default values (Int=0, String="", Bool=false, others=void), nested block comments `(* (* inner *) outer *)`, string escapes (`\n`, `\t`, `\\`, `\"`, `\b`, `\f`), and all built-in methods on Object, IO, Int, String, and Bool.

## Development testing

`/app/programs/` contains Cool programs to verify your implementation against during development.