# CEC 2026-Style Benchmark Function Suite Specification

## Overview

- **Dimension**: D = 10
- **Search bounds**: [-100, 100]^D
- **Functions**: 12 total (F1-F8 basic, F9-F10 hybrid, F11-F12 composition)
- **Constraints**: 3 constraint functions (on F1, F3, F9)

## Data Files (in `/app/data/`)

| File | Shape | Description |
|------|-------|-------------|
| `shifts.npy` | (10, D) | Shift vectors o_i for F1-F10 |
| `rotations.npy` | (10, D, D) | Orthogonal rotation matrices M_i for F1-F10 |
| `shuffle_f9.npy` | (D,) | Dimension permutation for F9 |
| `shuffle_f10.npy` | (D,) | Dimension permutation for F10 |
| `comp_optima_11.npy` | (3, D) | Component optima for F11 |
| `comp_optima_12.npy` | (5, D) | Component optima for F12 |
| `comp_rotations_11.npy` | (3, D, D) | Component rotation matrices for F11 |
| `comp_rotations_12.npy` | (5, D, D) | Component rotation matrices for F12 |
| `test_points.npy` | (5, D) | Evaluation points |

## Base Functions

All base functions take a vector z of arbitrary dimension n and return a scalar.

### 1. Sphere
```
sphere(z) = sum_{i=0}^{n-1} z_i^2
```
Optimum: z = 0, f* = 0

### 2. High Conditioned Elliptic
```
elliptic(z) = sum_{i=0}^{n-1} 10^(6*i/(n-1)) * z_i^2
```
When n=1, the exponent is 0. Optimum: z = 0, f* = 0

### 3. Bent Cigar
```
bent_cigar(z) = z_0^2 + 10^6 * sum_{i=1}^{n-1} z_i^2
```
Optimum: z = 0, f* = 0

### 4. Discus (Tablet)
```
discus(z) = 10^6 * z_0^2 + sum_{i=1}^{n-1} z_i^2
```
Optimum: z = 0, f* = 0

### 5. Rosenbrock
```
rosenbrock(z) = sum_{i=0}^{n-2} [100 * (z_i^2 - z_{i+1})^2 + (z_i - 1)^2]
```
Optimum: z = (1, 1, ..., 1), f* = 0

**Important**: For shifted/rotated usage in F5, apply z_hat = z + 1 before evaluation so the optimum aligns with z = 0.

### 6. Ackley
```
ackley(z) = -20 * exp(-0.2 * sqrt(sum(z_i^2) / n)) - exp(sum(cos(2*pi*z_i)) / n) + 20 + e
```
where e = exp(1). Optimum: z = 0, f* = 0

### 7. Griewank
```
griewank(z) = sum(z_i^2) / 4000 - prod_{i=0}^{n-1} cos(z_i / sqrt(i+1)) + 1
```
Note: the denominator inside cos is sqrt(i+1) using 0-based indexing (i.e., sqrt(1), sqrt(2), ..., sqrt(n)).
Optimum: z = 0, f* = 0

### 8. Rastrigin
```
rastrigin(z) = sum_{i=0}^{n-1} [z_i^2 - 10*cos(2*pi*z_i) + 10]
```
Optimum: z = 0, f* = 0

## Shifted & Rotated Functions (F1-F8)

For function F_k (k = 1, ..., 8):

1. Compute shifted vector: y = x - o_{k-1}  (using shifts[k-1])
2. Compute rotated vector: z = M_{k-1} @ y  (using rotations[k-1])
3. Apply base function with bias:

| Function | Base | Additional Transform | Bias |
|----------|------|---------------------|------|
| F1 | sphere | none | 100 |
| F2 | elliptic | none | 200 |
| F3 | bent_cigar | none | 300 |
| F4 | discus | none | 400 |
| F5 | rosenbrock | z_hat = z + 1 before eval | 500 |
| F6 | ackley | none | 600 |
| F7 | rastrigin | none | 700 |
| F8 | griewank | none | 800 |

Formula: F_k(x) = base_k(transform(M_{k-1} @ (x - o_{k-1}))) + bias_k

The optimum of each F_k is at x* = o_{k-1}, with F_k(x*) = bias_k.

## Hybrid Functions (F9-F10)

Hybrid functions partition the rotated dimensions among multiple base functions.

### Construction:

1. Shift: y = x - o_i  (using shifts[i] where i=8 for F9, i=9 for F10)
2. Rotate: z = M_i @ y  (using rotations[i])
3. Shuffle: z_s = z[shuffle]  (using shuffle_f9 or shuffle_f10)
4. Partition z_s into groups according to the partition sizes
5. Evaluate each base function on its corresponding group
6. Sum results and add bias

### F9 (bias = 900)
- Base functions: [bent_cigar, ackley, rastrigin]
- Partition sizes: [3, 3, 4]
- Shuffle: shuffle_f9
- Shift/rotation index: 8

Groups: z_s[0:3] -> bent_cigar, z_s[3:6] -> ackley, z_s[6:10] -> rastrigin

F9(x) = bent_cigar(z_s[0:3]) + ackley(z_s[3:6]) + rastrigin(z_s[6:10]) + 900

### F10 (bias = 1000)
- Base functions: [elliptic, sphere, griewank, rastrigin]
- Partition sizes: [3, 3, 2, 2]
- Shuffle: shuffle_f10
- Shift/rotation index: 9

Groups: z_s[0:3] -> elliptic, z_s[3:6] -> sphere, z_s[6:8] -> griewank, z_s[8:10] -> rastrigin

F10(x) = elliptic(z_s[0:3]) + sphere(z_s[3:6]) + griewank(z_s[6:8]) + rastrigin(z_s[8:10]) + 1000

## Composition Functions (F11-F12)

Composition functions are weighted combinations of multiple shifted/rotated base functions centered at different optima.

### Construction:

Given K components with optima o^(k), rotation matrices M^(k), scaling factors lambda_k, width parameters sigma_k, component biases c_k, and base functions f_k:

1. For each component k = 0, ..., K-1:
   - delta_k = x - o^(k)
   - dist_sq_k = sum(delta_k^2)
   - If dist_sq_k < 1e-30:
     - w_k = 1e100
   - Else:
     - w_k = (1 / sqrt(dist_sq_k)) * exp(-dist_sq_k / (2 * D * sigma_k^2))

2. Normalize weights:
   - W_k = w_k / sum(w_j)

3. Compute function value:
   - For each component k:
     - z_k = M^(k) @ delta_k
     - g_k = lambda_k * f_k(z_k) + c_k
   - F(x) = sum(W_k * g_k) + overall_bias

### F11 (overall_bias = 1100)

| Component k | Base function | sigma_k | lambda_k | c_k |
|-------------|---------------|---------|----------|-----|
| 0 | sphere | 10 | 1 | 0 |
| 1 | ackley | 20 | 10 | 100 |
| 2 | rastrigin | 30 | 1 | 200 |

- Optima: comp_optima_11 (shape 3 x D)
- Rotations: comp_rotations_11 (shape 3 x D x D)
- Global optimum: comp_optima_11[0], with F11* = 1100

### F12 (overall_bias = 1200)

| Component k | Base function | sigma_k | lambda_k | c_k |
|-------------|---------------|---------|----------|-----|
| 0 | elliptic | 10 | 10 | 0 |
| 1 | bent_cigar | 20 | 1 | 100 |
| 2 | discus | 30 | 10 | 200 |
| 3 | sphere | 40 | 1 | 300 |
| 4 | griewank | 50 | 1 | 400 |

- Optima: comp_optima_12 (shape 5 x D)
- Rotations: comp_rotations_12 (shape 5 x D x D)
- Global optimum: comp_optima_12[0], with F12* = 1200

## Constraint Functions

Three constraint functions are defined. The constraint violation for an inequality constraint g(x) <= 0 is:

```
violation(x) = max(0, g(x))
```

### Constraint on F1
```
g_1(x) = (1/D) * sum_{i=0}^{D-1} (x_i - o_0_i)^2 - 5000
```
where o_0 = shifts[0]. This defines a spherical feasible region centered at F1's optimum.

### Constraint on F3
```
g_2(x) = max_{i=0}^{D-1}(|x_i|) - 80
```
This defines a box feasible region [-80, 80]^D.

### Constraint on F9
```
g_3(x) = max_{i=0}^{D-1}(|x_i - o_8_i|) - 50
```
where o_8 = shifts[8]. This defines a box feasible region centered at F9's optimum with half-width 50.

## Output Format

The script must produce `/app/results.json` with this structure:

```json
{
  "F1": {
    "optimum": <float>,
    "test_points": [<float>, <float>, <float>, <float>, <float>]
  },
  ...
  "F12": { ... },
  "constraints": {
    "F1": {"violations": [<float>, <float>, <float>, <float>, <float>]},
    "F3": {"violations": [<float>, <float>, <float>, <float>, <float>]},
    "F9": {"violations": [<float>, <float>, <float>, <float>, <float>]}
  }
}
```

- `"optimum"`: Function value at the designated optimum (should equal the bias)
- `"test_points"`: Function values at the 5 test points from test_points.npy
- `"violations"`: Constraint violation values at the 5 test points
