A parser for a small functional language is provided at `/app/lang.py`. The language is a lambda calculus in Administrative Normal Form supporting closures, recursive bindings, mutable variables (`set!`), and first-class continuations (`call/cc`). Example programs are in `/app/programs/`.

A Guile Scheme reference runner is at `/app/reference/run_guile.sh`. Since the programs are valid Scheme, run any program through Guile to observe correct behavior: `/app/reference/run_guile.sh /app/programs/<file>.scm`.

Create the following deliverables in `/app/`:

**`/app/interp.py`** — An interpreter for the language. Must export `run(text: str)` that parses and evaluates the given program text, returning `int` for integers and `bool` for booleans. Must correctly evaluate all programs in `/app/programs/` with results matching the Guile reference.

**`/app/analysis.py`** — A whole-program flow analysis that determines, for each variable in the program, which lambda definitions (identified by `Lam.label` from the parser) could be bound to that variable during any possible execution. Must export `analyze(text: str) -> dict[str, set[int]]`. The result must be sound: every lambda that could reach a variable at runtime must appear in its result set. Over-approximation is acceptable.

**`/app/flow_graph.dot` and `/app/flow_graph.svg`** — A directed graph of the analysis results for `/app/programs/higher_order.scm`. Lambda definitions appear as rectangular nodes labeled `L<number>`. Variables with non-empty flow sets appear as elliptical nodes. Directed edges go from each lambda node to each variable it may flow to. Render the DOT file to SVG using the `dot` command.

Do not modify `/app/lang.py`.