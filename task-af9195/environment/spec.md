# Moving Peaks Benchmark — Specification

## Architecture

- **C library source**: `/app/src/gmpb.c`, API header: `/app/src/gmpb.h`
- **Build**: `make` in `/app/` (produces `/app/libgmpb.so`)
- **Instance configs & thresholds**: `/app/config.db` (SQLite database)
- **Evaluation runner**: `/app/runner.py` (loads library via `ctypes`, reads config from SQLite)

## Landscape

The fitness landscape is a composition of *m* peaks:

    f(x) = max_{i=1..m}  h_i / (1 + w_i · ‖x − c_i‖²)

| Symbol | Meaning                            | Range           |
|--------|------------------------------------|-----------------|
| h_i    | Height of peak *i*                 | [30, 70]        |
| w_i    | Sharpness of peak *i*              | [0.001, 0.01]   |
| c_i    | Center of peak *i*                 | [0, 100]^d      |

At the center, `f(c_i) = h_i`.  Larger `w_i` → narrower peak.
The half-height radius is approximately `1/√w_i` (≈ 10–31 distance units).

## Dynamics

The landscape changes every `change_frequency` evaluations.
At each change event, for every peak *i*:

1. **Position shift** (correlated random walk):
   ```
   r_i ~ N(0, I)
   v_i = shift_severity · normalize(0.5 · r_i + 0.5 · v_i_prev)
   c_i ← reflect(c_i + v_i,  [0, 100]^d)
   ```
   where `reflect` bounces values back into bounds.

2. **Height change**:
   ```
   h_i ← clip(h_i + 7.0 · N(0,1),  [30, 70])
   ```

3. **Sharpness change**:
   ```
   w_i ← clip(w_i + 0.001 · N(0,1),  [0.001, 0.01])
   ```

Height changes are large enough that the *identity* of the global-best
peak switches frequently between change events.

## Offline Error

    E = (1/N) Σ_{k=1}^{N} max(0, f*(t_k) − best_found(k))

- `N` = total number of fitness evaluations
- `f*(t_k)` = true optimum value in the environment active at evaluation `k`
- `best_found(k)` = best fitness value seen so far **within the current
  environment** (resets at each change event)

Lower offline error is better.

## Problem Instances

Six instances (F1–F6) with varying parameters are defined in `/app/config.db`.

    sqlite3 /app/config.db "SELECT * FROM instances"

Each instance has an offline error threshold in the `thresholds` table:

    sqlite3 /app/config.db "SELECT * FROM thresholds"

Parameters vary across dimensions (5–10), peak counts (10–25), change
frequencies (1000–5000), and shift severities (1.0–3.0).
