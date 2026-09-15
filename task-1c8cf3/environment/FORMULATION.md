# Affine-Depth Relative Pose Estimation: Mathematical Formulation

## Problem Statement

Given N >= 3 point correspondences between two camera views where the monocular depth
predictions are subject to unknown per-view affine transformations, recover:
1. The affine correction parameters (scale and shift) for each view
2. The relative camera pose (rotation R and translation t)

## Mathematical Model

### Bearing Vectors and Depths

Each point j in view k has:
- A **bearing vector** `x_k[j]` in R^3 with `x_k[j][2] = 1` (normalized image coords)
- A **predicted depth** `d_k[j]`

The true depth satisfies: `d_k_true[j] = a_k * d_k[j] + b_k`

where `(a_k, b_k)` are unknown per-view scale and shift parameters.

### 3D Point Reconstruction

The 3D point in view k's coordinate frame: `P_k[j] = d_k_true[j] * x_k[j]`

### Rigid Scene Constraint

For points in the same rigid scene observed from two views related by pose (R, t):
`P_2[j] = R @ P_1[j] + t`

In particular, interpoint distances are preserved:
`||P_1[i] - P_1[j]||^2 = ||P_2[i] - P_2[j]||^2`

## Variable Substitution

Without loss of generality, normalize `a_1 = 1` (fixing the global depth scale).

Define the solver unknowns as:
- **alpha = a_2^2** (squared relative scale)
- **beta = b_2 / a_2** (normalized view-2 shift)
- **b_1** (view-1 shift, unchanged)

Under this substitution:
- `P_1[j] = (d_1[j] + b_1) * x_1[j]`
- `P_2[j] = a_2 * (d_2[j] + beta) * x_2[j]`

And the squared distance in view 2 factors as:
```
||P_2[i] - P_2[j]||^2 = alpha * ||(d_2[i] + beta)*x_2[i] - (d_2[j] + beta)*x_2[j]||^2
```

## Polynomial Constraint Equations

For each pair (i, j), the constraint `||P_1||^2 = ||P_2||^2` expands to a
polynomial equation in the three unknowns (alpha, beta, b_1):

```
c_0 * alpha * beta^2 + c_1 * b_1^2 + c_2 * alpha * beta + c_3 * alpha + c_4 * b_1 + c_5 = 0
```

where the six coefficients depend on the bearing vectors and predicted depths:

```
c_0 = 2*(x_2[i] . x_2[j]) - (x_2[i] . x_2[i]) - (x_2[j] . x_2[j])
c_1 = (x_1[i] . x_1[i]) + (x_1[j] . x_1[j]) - 2*(x_1[i] . x_1[j])
c_2 = 2*(d_2[i]+d_2[j])*(x_2[i] . x_2[j]) - 2*d_2[i]*(x_2[i] . x_2[i]) - 2*d_2[j]*(x_2[j] . x_2[j])
c_3 = 2*d_2[i]*d_2[j]*(x_2[i] . x_2[j]) - d_2[i]^2*(x_2[i] . x_2[i]) - d_2[j]^2*(x_2[j] . x_2[j])
c_4 = 2*d_1[i]*(x_1[i] . x_1[i]) + 2*d_1[j]*(x_1[j] . x_1[j]) - 2*(d_1[i]+d_1[j])*(x_1[i] . x_1[j])
c_5 = d_1[i]^2*(x_1[i] . x_1[i]) + d_1[j]^2*(x_1[j] . x_1[j]) - 2*d_1[i]*d_1[j]*(x_1[i] . x_1[j])
```

With 3 point correspondences, the three pairs (0,1), (0,2), (1,2) yield 3 equations
and 18 coefficients total. The coefficients should be stored as a flat array of 18
values: indices [0..5] for pair (0,1), [6..11] for pair (0,2), [12..17] for pair (1,2).

## System Properties

The system of 3 polynomial equations in 3 unknowns (alpha, beta, b_1) generically has
exactly **4 solutions** (counting multiplicities in the complex numbers).

Physically meaningful solutions require **alpha > 0** (since alpha = a_2^2 >= 0).

After solving, recover the original parameters:
```
a_1 = 1.0
b_1 = b_1          (directly from the solution)
a_2 = sqrt(alpha)  (positive root)
b_2 = beta * a_2   (recover original shift)
```

## Pose Recovery

Given affine correction parameters (a_1=1, b_1, a_2, b_2), correct the depths:
```
d_1_corrected = d_1 + b_1
d_2_corrected = a_2 * d_2 + b_2
```

Reconstruct 3D points in each view's frame:
```
X_1[j] = d_1_corrected[j] * x_1[j]
X_2[j] = d_2_corrected[j] * x_2[j]
```

Recover rotation R and translation t satisfying `X_2 = R @ X_1 + t` from the
reconstructed point correspondences.

**Note:** since a_1 is normalized to 1.0, the recovered translation is scaled
by 1/a_1_true relative to the actual translation. Only the translation
direction `t / ||t||` is geometrically meaningful.
