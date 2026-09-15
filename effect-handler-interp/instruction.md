A lark-based interpreter for a small functional language lives at `/app/`. The grammar (`/app/grammar.lark`), AST transformer (`/app/transform.py`), and evaluator (`/app/eval.py`) currently support basic expressions — arithmetic, conditionals, lambdas, application, let/def bindings, sequences, and print.

The language's algebraic effect system is unimplemented: effect declarations, `handle`/`with` expressions, and `do` operations are absent from the grammar and evaluator. The AST node definitions in `/app/ast_nodes.py` already include all required node types (`EffectDecl`, `HandleExpr`, `DoExpr`, `HandlerClause`, `ReturnClause`) — do not modify that file.

Ten example programs in `/app/examples/` each have a `.eff` source and `.expected` output. Only `01_basic.eff` (no effects) currently parses; the other nine fail. Extend the grammar, transformer, and evaluator so all ten programs produce their expected output. The handler semantics must support multi-shot continuations (resume called multiple times), continuation discarding, nested handler shadowing, multi-operation handlers, and cross-effect interaction.

`python3 /app/run_all.py` reports pass/fail status for all examples.