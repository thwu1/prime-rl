`/app/autodiff.py` implements a mini automatic differentiation framework with both forward-mode (JVP via dual numbers) and reverse-mode (VJP via tape-based backpropagation) for scalar computations. It supports primitives for arithmetic, exp, log, sin, cos, along with `grad()`, `deriv()`, and `value_and_grad()` APIs. The implementation contains multiple bugs across its differentiation rules and backward pass that cause incorrect gradient computations.

`/app/numerics.py` contains six JAX numerical functions using `@jax.custom_vjp` for custom backward-pass differentiation. Multiple functions have incorrect VJP formulas, numerically unstable forward passes, or both. The `log_cosh` function lacks a `@custom_vjp` entirely and produces inf/NaN for large inputs.

Diagnose and fix all bugs in both systems. Produce:

**1. Fixed `/app/autodiff.py`** — all VJP rules, JVP rules, and the backward pass must compute mathematically correct derivatives. `grad()` must correctly differentiate arbitrary compositions of supported operations, including expressions where the same variable appears multiple times.

**2. Fixed `/app/numerics.py`** — all six functions must compute correct values, have correct gradients via `jax.grad`, and remain numerically stable for extreme input magnitudes (|x| > 700). `log_cosh` requires a new `@custom_vjp` implementation.

**3. `/app/cross_validation.json`** — for each numerics function expressible using the mini AD framework's primitives (exp, log, arithmetic), implement an equivalent function using the mini AD, compute gradients via both systems at multiple test points, and record agreement:
```json
{"<fn>": {"test_points": [{"x": <float>, "jax_grad": <float>, "autodiff_grad": <float>, "match": <bool>}], "all_match": <bool>}}
```

**4. `/app/audit_report.json`** — structured diagnosis of original bugs in both files:
```json
{
  "autodiff_bugs": {"<component>": {"issue": "...", "fix": "..."}},
  "numerics_bugs": {"<fn>": {"issues": ["..."], "fix_description": "..."}},
  "jaxpr_analysis": {"<fn>": {"primitives_used": ["..."], "num_equations": <int>}}
}
```

The `jaxpr_analysis` must contain computational graph metadata obtained via `jax.make_jaxpr` for each numerics function. Configuration parameters are in `/app/config.json`. JAX (CPU) is pre-installed.