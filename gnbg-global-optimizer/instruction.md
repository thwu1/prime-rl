A benchmark suite of 12 shifted-and-rotated numerical optimization problems is provided at `/app/benchmark.py`. The suite spans unimodal ill-conditioned landscapes (Ellipsoid, Discus, Bent Cigar), narrow-valley problems (Rosenbrock), regular multimodal (Rastrigin, Ackley, Griewank), deceptive landscapes (Schwefel, Lunacek bi-Rastrigin), and rugged/fractal surfaces (Katsuura, Schaffer F7). Problems are box-constrained (bounds vary per problem, see `problem.bounds`) with dimensions between 10 and 20.

Create `/app/optimizer.py` exporting a single function:

```python
def optimize(problem) -> np.ndarray:
```

The `problem` argument is a `Problem` instance from `/app/benchmark.py` with these attributes and methods:

- `problem.dim` — dimensionality
- `problem.bounds` — tuple `(lower, upper)` of numpy arrays
- `problem.max_evals` — total evaluation budget
- `problem.evals_used` — current evaluation count
- `problem.evaluate(x)` — returns objective value (minimise); returns `+inf` when budget is exhausted
- `problem.get_best()` — returns `(best_x, best_value)` found so far

`optimize` must return the best solution vector found. The same algorithm and parameter settings must be used for all 12 problems (no per-instance tuning). Each problem has an individual evaluation budget (50K–200K) and an error threshold. The optimizer is evaluated on whether `|f(x_best) - f*| < threshold` for each problem, and must pass on at least 10 of the 12 problems.

The suite is generated via `get_suite(seed=42)`. Study the benchmark module to understand the problem API, then implement your optimization strategy.