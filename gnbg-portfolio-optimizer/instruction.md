Implement a high-performance black-box continuous optimization solver at `/app/solver.py` that achieves competitive performance on problems from the GNBG (Generalized Numerical Benchmark Generator) test suite, accessed via the `iohgnbg` Python package.

Your solver module must expose exactly this interface:

```python
def solve(objective_fn, dimension, lower_bounds, upper_bounds, max_evaluations):
    """
    Minimize objective_fn over the box-constrained domain.

    Args:
        objective_fn: callable taking a numpy array of shape (dimension,), returns float
        dimension: int, number of decision variables
        lower_bounds: array-like of floats, per-variable lower bounds
        upper_bounds: array-like of floats, per-variable upper bounds
        max_evaluations: int, hard limit on objective_fn calls

    Returns:
        (best_x, best_f): tuple where best_x is a numpy array of the best solution
        found (not None, length == dimension), and best_f is its numeric objective value
        (int, float, or numpy floating type).
    """
```

## Validation

The solver is first validated on a simple 2D sphere function (`f(x) = sum(x_i^2)` with bounds `[-5, 5]^2` and 10,000 evaluations). The solver must achieve `best_f < 0.01` on this test.

## GNBG benchmark evaluation

The solver is then evaluated on four GNBG benchmark instances with a budget of **200,000 function evaluations** each. Error is measured as `|best_f - f*|` where `f*` is the known global optimum retrieved from the `iohgnbg` problem metadata. The specific problems and required error thresholds are:

| Problem ID | Category | Error threshold |
|---|---|---|
| 1 | Foundational (unimodal) | < 1e-2 |
| 4 | Foundational (unimodal) | < 1e-1 |
| 8 | Coupled variable interactions | < 1.0 |
| 12 | Multimodal / asymmetric | < 10.0 |

Budget compliance is enforced: the solver must not exceed the evaluation budget by more than 2% (i.e., at most `budget * 1.02` function evaluations per problem).

The solver must handle arbitrary dimensions and non-uniform box constraints, strictly respect the evaluation budget, and operate as a pure black-box optimizer with no access to problem structure, gradients, or internal parameters. Achieving the required thresholds demands an algorithm that adapts to diverse landscape morphologies — conditioning, asymmetry, variable interactions, basin shape, and deceptiveness — rather than relying on a single strategy.

Install any solver dependencies you need into the environment at `/app/`.