Implement an equality saturation optimizer as a Python module at `/app/egraph_opt.py`.

The module must expose a function `optimize(expr: str) -> str` that accepts an S-expression string representing an arithmetic expression and returns a semantically equivalent S-expression with minimum cost according to the specified cost model.

The full specification — expression language, rewrite rules, and cost model — is in `/app/spec.md`. Benchmark expressions with target costs are in `/app/benchmarks.json`.

The optimizer must use an e-graph data structure with equality saturation: build the e-graph from the input expression, apply all rewrite rules until saturation (or a reasonable iteration limit), then extract the minimum-cost equivalent expression. The output must be semantically equivalent to the input for all positive integer variable assignments and must achieve cost at or below the `max_cost` for each benchmark.