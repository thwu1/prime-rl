The `/app/` directory contains modules for a JAX-based reinforcement learning library that computes value function targets using nonlinear transforms, multistep returns, V-trace off-policy corrections, and their composition.

Modules:
- `/app/base.py` — Array indexing utilities
- `/app/transforms.py` — Element-wise nonlinear value transforms and inverses
- `/app/multistep.py` — Multistep bootstrapped return computations
- `/app/vtrace.py` — V-trace importance-sampled off-policy corrections
- `/app/nonlinear_bellman.py` — TD-error functions operating in transformed value space, composing the above modules

Functions raising `NotImplementedError` must be implemented. Existing code may contain defects; diagnose and fix any issues preventing tests from passing.

**Constraints:**

- All implementations must be `jax.vmap`-compatible
- `stop_target_gradients` must control gradient flow: when enabled, `jax.grad` through returned values with respect to value inputs must yield zero
- Numeric results must match golden values within `rtol=1e-3`
- `compose_tx` forward applies transforms in argument order; inverse applies in reverse order
- V-trace accumulates clipped importance-sampled TD corrections backward through time
- `vtrace_td_error_and_advantage` results must satisfy: `errors + v == v + clipped_rho * (q_estimate - v)`

**Success criterion:** `cd /app && python3 -m pytest /tests/test_state.py -v` — all tests pass.
