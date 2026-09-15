The file `/app/minijax.py` implements a minimal tracing-based automatic differentiation system modeled after JAX's core architecture. It provides composable function transformations via an interpreter stack, forward-mode AD (JVP), a jaxpr intermediate representation with construction and evaluation, and pytree handling. Primitives include `add`, `mul`, `neg`, `sin`, `cos`, `exp`, `log`, `div`, `reduce_sum`, `broadcast`, and others with full JVP and abstract evaluation rules.

Implement reverse-mode automatic differentiation by creating `/app/autodiff.py` that exports working `grad` and `vjp` functions. `grad(f)` must return a function computing the gradient of scalar-valued `f` with respect to its first argument. `vjp(f, *primals)` must return `(primals_out, vjp_fn)` where `vjp_fn` maps output cotangents to input cotangents.

Requirements:
- Must build on the existing forward-mode AD and jaxpr infrastructure in `/app/minijax.py`
- Must support higher-order derivatives: `grad(grad(f))` must work correctly
- Must handle all primitives defined in minijax.py that can appear in differentiable computations
- Must produce numerically correct gradients (matching finite differences to 1e-4 tolerance)
- Must handle functions with multiple intermediate computations (chain rule, product rule)
- Must support array-valued inputs for scalar-output functions (e.g., `grad(lambda x: reduce_sum(x * x))`)