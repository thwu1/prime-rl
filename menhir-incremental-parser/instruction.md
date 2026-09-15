The environment at `/app` contains a MiniML parser project using OCaml, Menhir, and Dune. The project fails to build because the grammar at `/app/lib/parser.mly` has numerous shift/reduce conflicts, the build configuration is missing required flags, and the parser driver uses the wrong API.

Produce a working parser system satisfying all of the following:

**Build**: `dune build` in `/app` completes with zero grammar conflicts. The Menhir parser must be generated in `--table` mode (required for the incremental API). The library must depend on `menhirLib`.

**Correct Parsing**: `/app/_build/default/bin/main.exe` reads MiniML source from stdin, prints an S-expression AST to stdout. It must correctly handle: integer/boolean literals, variables, arithmetic (`+`,`-`,`*`,`/`) with standard precedence and left-associativity, comparisons (`=`,`<>`,`<`,`>`,`<=`,`>=`) non-associative, logical operators (`&&` left-assoc, `||` left-assoc, `not` prefix), unary negation, let/let-rec/in bindings, if/then/else, lambda (`fun x -> e`), function application via juxtaposition (left-associative, higher precedence than binary operators), tuples `(e,e,...)`, lists `[e;e;...]`, cons `::` (right-associative), pattern matching (`match e with | p -> e ...`), and sequencing `e;e` (right-associative; binding constructs absorb semicolons; inner match absorbs subsequent `|` arms). Patterns: wildcards `_`, variables, integers, booleans, tuple patterns, list patterns, cons patterns (right-associative).

**Incremental API**: The driver at `/app/bin/main.ml` must use Menhir's incremental API (`MenhirInterpreter` checkpoints) — not the monolithic `Parser.program Lexer.token` pattern.

**Error Messages**: A complete Menhir `.messages` file must exist at `/app/lib/errors.messages`, covering all error states of the LR automaton (verifiable via `menhir --compare-errors`). All messages must be non-empty and must not contain the placeholder `<YOUR MESSAGE HERE>`.

**Error Reporting**: On invalid input, the parser must print a diagnostic to stderr including line and column numbers, and exit with code 1.

The AST types at `/app/lib/ast.ml`, the lexer at `/app/lib/lexer.mll`, and the printer at `/app/lib/printer.ml` are correct and define the expected output format. Examine `/app/lib/printer.ml` to understand the S-expression structure. Do not modify `ast.ml`, `lexer.mll`, or `printer.ml`. You may modify or create: `/app/lib/parser.mly`, `/app/lib/dune`, `/app/lib/errors.messages`, `/app/bin/main.ml`, `/app/bin/dune`, `/app/dune-project`.
