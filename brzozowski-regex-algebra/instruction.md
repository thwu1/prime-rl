The directory `/app/` contains the skeleton of `rex`, a command-line tool for analyzing regular expressions extended with complement (`~`) and intersection (`&`) operators. The AST node classes are defined in `/app/regex_algebra.py`, but the analysis engine is unimplemented — all core functions raise `NotImplementedError`.

Complete the tool so that:

1. All functions in `/app/regex_algebra.py` that raise `NotImplementedError` produce correct results. Each function must correctly handle all eight AST node types, including `Complement` and `Intersection`. Standard regex libraries cannot handle complement and intersection — a purpose-built analysis engine is required.

2. The CLI at `/app/rex` works as specified in `/app/SPEC.md`, supporting the `match`, `empty`, `universal`, `equivalent`, `dot`, `compile`, and `flex-spec` subcommands.

3. The `dot` subcommand outputs valid Graphviz DOT representing the finite state graph of a given expression over a specified alphabet. Running `dot -Tsvg` on the output must produce valid SVG. Accepting states must use `doublecircle` shape; non-accepting states use `circle`.

4. The `compile` subcommand constructs the DFA, generates C source code implementing it as a state machine, and compiles it with `gcc` into a standalone binary. The binary must read strings line-by-line from stdin and print `accept` or `reject` for each.

5. The `flex-spec` subcommand constructs the DFA and generates a valid `flex` lexical specification (`.l` file) that uses exclusive start conditions to represent DFA states. The generated file must be compilable via `flex` and `gcc` into a working standalone matcher.

6. All decision procedures (`is_empty`, `is_universal`, `equivalent`) must terminate for every well-formed input over any finite alphabet.

The existing AST classes (`Empty`, `Epsilon`, `Char`, `Alt`, `Seq`, `Star`, `Complement`, `Intersection`) must not be renamed or restructured.