
# BBOB Function Mathematical Reference

## Notation

- **D**: dimension of the search space
- **x** ∈ ℝᴰ: input vector
- **x_opt** ∈ [-4,4]ᴰ: optimal solution (hidden, instance-specific)
- **f_opt** ∈ ℝ: optimal function value (hidden, instance-specific, typically in [-100, 100])
- **R**: D×D orthogonal rotation matrix (hidden, instance-specific), generated via Gram-Schmidt orthonormalization of standard-normally distributed entries
- Indexing in formulas uses 1-based (i = 1, ..., D); implementations typically use 0-based

## Tosz Transformation: ℝⁿ → ℝⁿ (element-wise)

Applied independently to each scalar component x_i of the input vector:

```
If x_i = 0:
    Tosz(x_i) = 0

Otherwise:
    x̂ = ln|x_i|
    
    sign(x_i) = { -1  if x_i < 0
                {  0  if x_i = 0
                {  1  if x_i > 0
    
    c₁ = { 10.0  if x_i > 0
         {  5.5  if x_i ≤ 0
    
    c₂ = {  7.9  if x_i > 0
         {  3.1  if x_i ≤ 0
    
    Tosz(x_i) = sign(x_i) · exp( x̂ + 0.049 · (sin(c₁ · x̂) + sin(c₂ · x̂)) )
```

**Key property**: Tosz is approximately the identity (Tosz(x) ≈ x) with smooth oscillatory perturbations. It is NOT an odd function—the constants c₁, c₂ differ between positive and negative inputs, so Tosz(x) ≠ -Tosz(-x) in general.

## Function Definitions

### f1 — Sphere (separable, unimodal)

```
f₁(x) = ‖z‖² + f_opt

where z = x − x_opt
```

Properties: Rotationally invariant. Condition number = 1.

### f2 — Ellipsoidal, separable (unimodal)

```
f₂(x) = Σᵢ₌₁ᴰ 10^(6·(i-1)/(D-1)) · zᵢ² + f_opt

where z = Tosz(x − x_opt)
```

Properties: Separable, globally quadratic with smooth local irregularities from Tosz. Conditioning ≈ 10⁶. The conditioning matrix Λ has diagonal entries λᵢ = 10^(6·(i-1)/(D-1)) for i = 1, ..., D.

### f8 — Rosenbrock, original (moderate conditioning)

```
f₈(x) = Σᵢ₌₁ᴰ⁻¹ [ 100·(zᵢ² − zᵢ₊₁)² + (zᵢ − 1)² ] + f_opt

where z = max(1, √D / 8) · (x − x_opt) + 1
```

Properties: The "banana function" with a narrow curved valley. The optimal z is the all-ones vector (z* = 1). For D ≤ 64, the scale factor max(1, √D/8) = 1, so z = (x − x_opt) + 1 and the optimum is at x = x_opt.

### f10 — Ellipsoidal, rotated (non-separable, unimodal)

```
f₁₀(x) = Σᵢ₌₁ᴰ 10^(6·(i-1)/(D-1)) · zᵢ² + f_opt

where z = Tosz(R · (x − x_opt))
      R is a D×D orthogonal rotation matrix
```

Properties: Non-separable counterpart to f2. Same conditioning (≈ 10⁶) but the rotation R makes the function non-separable.
