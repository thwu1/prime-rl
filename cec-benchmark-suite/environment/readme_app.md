# Benchmark Evaluation Pipeline

## Overview

This pipeline evaluates 12 numerical optimization benchmark functions at
designated test points. Functions are organized as:
- F1-F8: Single shifted-and-rotated base functions
- F9-F10: Hybrid functions (partitioned multi-function)
- F11-F12: Composition functions (weighted multi-center)

Three constraint violation functions are also evaluated (on F1, F3, F9).

## Files

| File | Description |
|------|-------------|
| `benchmark.db` | SQLite database — parameter data and mathematical specifications |
| `data/*.npy` | NumPy binary files — exported parameter snapshots used by evaluator |
| `benchmark.py` | Evaluator script — loads data, evaluates functions, writes output |
| `results.json` | Output — function values at optima and test points |

## Database Schema

The database stores parameter data and mathematical specifications. Parameter
data in BLOB-encoded tables was generated programmatically. Specification
tables (formulas, reference values) were transcribed from reference
documentation. Data files in `/app/data/` are exported snapshots of database
parameter tables.

### Parameter Tables

```
shifts         (idx INTEGER PRIMARY KEY, data BLOB)
rotations      (idx INTEGER PRIMARY KEY, data BLOB)
shuffles       (name TEXT PRIMARY KEY, data BLOB)
comp_optima    (name TEXT, idx INTEGER, data BLOB)
comp_rotations (name TEXT, idx INTEGER, data BLOB)
test_points    (idx INTEGER PRIMARY KEY, data BLOB)
metadata       (key TEXT PRIMARY KEY, value TEXT)
```

### Specification Tables

```
base_function_specs  (name TEXT PRIMARY KEY, formula TEXT, notes TEXT)
function_specs       (name TEXT PRIMARY KEY, func_type TEXT, base_funcs TEXT,
                      shift_idx INTEGER, rotation_idx INTEGER, bias REAL,
                      params_json TEXT, notes TEXT)
construction_formulas (func_type TEXT PRIMARY KEY, formula TEXT, notes TEXT)
constraint_specs     (name TEXT PRIMARY KEY, target_func TEXT, formula TEXT,
                      threshold REAL, notes TEXT)
reference_values     (func_name TEXT, point_type TEXT, expected_value REAL,
                      tolerance REAL, PRIMARY KEY(func_name, point_type))
```

### BLOB Encoding

- Shift vectors: D x float64 (80 bytes each)
- Rotation matrices: D x D x float64, row-major (800 bytes each)
- Shuffles: D x int64 (80 bytes each)
- Test points: D x float64 (80 bytes each)
- Composition optima: D x float64 (80 bytes each)
- Composition rotations: D x D x float64, row-major (800 bytes each)

Decode with `numpy.frombuffer(blob, dtype=numpy.float64)` (or `int64` for shuffles).
Reshape rotation matrices to `(D, D)`.

### Key Specification Tables

- **base_function_specs**: Mathematical formula for each base function
  (sphere, elliptic, bent_cigar, discus, rosenbrock, ackley, griewank, rastrigin).
- **function_specs**: Per-function construction recipe — which base function(s),
  shift/rotation indices, bias, and additional parameters in `params_json`.
- **construction_formulas**: General construction recipe for each function type
  (`shifted_rotated`, `hybrid`, `composition`).
- **constraint_specs**: Constraint violation formulas for constrained functions.
- **reference_values**: Expected function values at optima for validation.

## Running

```
python3 /app/benchmark.py
```

Produces `results.json` with function values at each function's optimum and at
5 shared test points, plus constraint violation values.

## Output Format

```json
{
  "F1": {"optimum": <float>, "test_points": [<float>, ...]},
  ...
  "F12": {...},
  "constraints": {
    "F1": {"violations": [<float>, ...]},
    "F3": {"violations": [<float>, ...]},
    "F9": {"violations": [<float>, ...]}
  }
}
```
