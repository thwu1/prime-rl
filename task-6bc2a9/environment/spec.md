# Generalized Moving Peaks Benchmark (GMPB) — Specification

## Overview

GMPB generates dynamic optimization landscapes composed of multiple peaks
whose parameters (position, height, width) change between environments.
The optimizer must track the global optimum as the landscape shifts.

## Search Space

x ∈ [L, U]^D where L = -100, U = 100, and D is the dimensionality.

## Peak Function

Each peak k ∈ {0, 1, ..., m-1} at environment e is defined as:

    g_k(x, e) = h_k(e) / (1 + ||x - p_k(e)||² / w_k(e)²)

where:
- p_k(e) ∈ ℝ^D is the position (center) of peak k
- h_k(e) ∈ [H_min, H_max] is the height of peak k
- w_k(e) ∈ [W_min, W_max] is the width of peak k
- ||·|| denotes the Euclidean (L2) norm

Parameter bounds: H_min=30, H_max=70, W_min=5, W_max=20.

## Landscape Function

    f(x, e) = max_{k=0,...,m-1} g_k(x, e)

The global optimum value equals max_k h_k(e), attained at position p_{k*}(e)
where k* = argmax_k h_k(e).

## Initialization

Using `numpy.random.default_rng(seed)`, for each peak k = 0, 1, ..., m-1
(peaks processed sequentially in order):

1. `p_k(1) = rng.uniform(L_init, U_init, size=D)`     where L_init=-50, U_init=50
2. `h_k(1) = rng.uniform(H_min, H_max)`
3. `w_k(1) = rng.uniform(W_min, W_max)`
4. `v_tmp = rng.standard_normal(D)`
5. `v_k = s * v_tmp / ||v_tmp||`

Steps 1-5 are completed for peak 0 before proceeding to peak 1, etc.

## Environment Change Dynamics

When transitioning from environment e to e+1, for each peak k = 0, 1, ..., m-1
(processed sequentially in order):

1. `r_k = rng.standard_normal(D)`
2. `r_k = r_k / ||r_k||`
3. `u_k = λ * (v_k / ||v_k||) + (1 - λ) * r_k`
4. `v_k = s * u_k / ||u_k||`
5. `p_k(e+1) = clip(p_k(e) + v_k, L, U)`
6. `h_k(e+1) = clip(h_k(e) + σ_h * rng.standard_normal(), H_min, H_max)`
7. `w_k(e+1) = clip(w_k(e) + σ_w * rng.standard_normal(), W_min, W_max)`

The same `rng` object (initialized at construction) is used throughout all
environment changes. No other operations consume from this RNG.

## Fixed Parameters

- λ = 0.5 (shift correlation coefficient)
- σ_h = 1.0 (height change severity)
- σ_w = 0.5 (width change severity)
- s = shift severity (instance-specific, from config)

## Offline Error

    E_offline = (1 / N_total) * Σ_{i=1}^{N_total} (f*(e_i) - f(x*_i, e_i))

where:
- N_total = num_environments × change_frequency
- e_i is the environment index at the i-th evaluation
- f*(e_i) = max_k h_k(e_i) is the global optimum value
- x*_i is the position achieving the highest function value among all
  evaluations 1..i in the current environment e_i
- The best-found tracking resets at each environment change

The evaluate method triggers an environment change after every `change_frequency`
evaluations (except in the final environment). The returned value of the triggering
evaluation is computed in the pre-change environment; subsequent calls use the new
environment.

## Required C Function Interface

The peak evaluation kernel must be implemented in C and compiled as a shared
library (`libpeaks.so`). The GMPB Python class must call this library via
`ctypes` for all peak evaluations.

```c
double evaluate_peaks(const double *x, int dim,
                      const double *positions, const double *heights,
                      const double *widths, int num_peaks);
```

Parameters:
- `x`: evaluation point, array of `dim` doubles
- `positions`: flat row-major array of peak centers, `num_peaks × dim` doubles
  (peak 0 first: [p0_d0, p0_d1, ..., p1_d0, p1_d1, ...])
- `heights`: peak heights, `num_peaks` doubles
- `widths`: peak widths, `num_peaks` doubles
- Returns: max_k g_k(x) as defined in the peak function above

## Required Python API

```python
import numpy as np

class GMPB:
    def __init__(self, dim: int, num_peaks: int, shift_severity: float,
                 change_frequency: int, num_environments: int, seed: int):
        """Initialize the benchmark with given parameters."""
        ...

    def evaluate(self, x: np.ndarray) -> float:
        """Evaluate f(x) in the current environment.
        Increments the evaluation counter. Triggers an environment change
        after change_frequency evaluations (except in the final environment).
        Returns the landscape value at x."""
        ...

    def get_current_environment(self) -> int:
        """Return the current environment index (1-based)."""
        ...

    def get_global_optimum(self) -> tuple:
        """Return (position_array, value) of the global optimum in the
        current environment. Does NOT count as a function evaluation."""
        ...

    def get_offline_error(self) -> float:
        """Return the offline error accumulated over all evaluations so far."""
        ...

    def has_terminated(self) -> bool:
        """Return True if all evaluations
        (num_environments × change_frequency) are exhausted."""
        ...

    def has_changed(self) -> bool:
        """Return True if the most recent evaluate() call triggered
        an environment change."""
        ...

    def get_env_stats(self) -> list:
        """Return a list of dicts for each completed or in-progress
        environment. Each dict contains:
        - 'env_index': 1-based environment index
        - 'avg_error': mean of (optimum - best_found_so_far) over
          all evaluations in that environment
        - 'best_found': highest function value found in that environment
        - 'optimum_value': max peak height (global optimum) in that
          environment"""
        ...


class DynamicOptimizer:
    def __init__(self, benchmark: GMPB, seed: int = 0):
        """Initialize the optimizer with a GMPB benchmark instance."""
        ...

    def run(self) -> dict:
        """Run the optimizer until the benchmark terminates.
        Returns a dict with at least the key 'offline_error'."""
        ...
```

## SQLite Results Schema

The runner must persist results to an SQLite database with these tables:

```sql
CREATE TABLE runs (
    instance_name TEXT PRIMARY KEY,
    dim INTEGER,
    num_peaks INTEGER,
    shift_severity REAL,
    change_frequency INTEGER,
    num_environments INTEGER,
    seed INTEGER,
    offline_error REAL,
    threshold REAL,
    passed INTEGER  -- 1 if offline_error < threshold, 0 otherwise
);

CREATE TABLE env_stats (
    instance_name TEXT,
    env_index INTEGER,
    avg_error REAL,
    best_found REAL,
    optimum_value REAL,
    PRIMARY KEY (instance_name, env_index)
);
```
