# Eigenvalue Buckling Analysis — Mathematical Specification

## 1. Pipeline Overview

Linear eigenvalue buckling analysis predicts the critical load factor λ at which
a frame structure becomes unstable:

1. Assemble global elastic stiffness **K_e** and load vector **P**
2. Solve **K_e · u = P** for reference displacement state **u**
3. Recover element internal forces from **u**
4. Assemble global geometric stiffness **K_g** from those internal forces
5. Solve the generalized eigenproblem **K_e · φ = −λ · K_g · φ**
6. Return the smallest positive eigenvalue λ (critical load factor)
   and the corresponding buckling mode shape φ

The predicted buckling load is **P_cr = λ · P_ref**.

## 2. DOF Convention

Per node: `[u_x, u_y, u_z, θ_x, θ_y, θ_z]`

Local element DOFs (beam x-axis from node i to node j):

```
[u₁,  v₁,  w₁,  θx₁, θy₁, θz₁, u₂,  v₂,  w₂,  θx₂, θy₂, θz₂]
 0    1    2    3    4    5    6    7    8    9    10   11
```

- u: axial displacement (along beam)
- v: transverse displacement (bending about z)
- w: transverse displacement (bending about y)
- θx: torsional rotation
- θy: bending rotation about y
- θz: bending rotation about z

## 3. Coordinate Transformation

The transformation matrix **Γ** (12×12 block-diagonal of four 3×3 direction
cosine matrices γ) relates local and global coordinates.

The 3×3 matrix γ has rows `[ex, ey, ez]` — the local axes expressed in global
coordinates. Therefore:

- **u_local = Γ · u_global** (Γ maps global → local)
- **K_global = Γᵀ · K_local · Γ**

This distinction is critical for force recovery: to transform global
displacements into local coordinates, apply **Γ** (not Γᵀ).

## 4. Internal Force Recovery

Local element forces are computed from the reference displacement state:

```
u_local  = Γ · u_e_global
f_local  = k_e_local · u_local
```

The 12-component local force vector contains:

```
[Fx₁, Fy₁, Fz₁, Mx₁, My₁, Mz₁, Fx₂, Fy₂, Fz₂, Mx₂, My₂, Mz₂]
 0    1    2    3    4    5    6    7    8    9    10   11
```

The geometric stiffness matrix uses the following internal forces:

| Symbol | Index | Description                              |
|--------|-------|------------------------------------------|
| Fx₂    | 6     | Axial force at node 2 (tension positive) |
| Mx₂    | 9     | Torsional moment at node 2               |
| My₁    | 4     | Bending moment at node 1, y-axis         |
| Mz₁    | 5     | Bending moment at node 1, z-axis         |
| My₂    | 10    | Bending moment at node 2, y-axis         |
| Mz₂    | 11    | Bending moment at node 2, z-axis         |

## 5. Geometric Stiffness Matrix

The 12×12 local geometric stiffness matrix **K_g** captures second-order
(initial stress) effects. It is symmetric and zero when all internal forces
are zero.

### 5.1 Hermite Cubic Shape Functions

Bending uses Hermite cubic interpolation. In terms of ξ = x/L ∈ [0, 1]:

```
N₁(ξ) = 1 − 3ξ² + 2ξ³           (displacement at node 1)
N₂(ξ) = L · ξ(1 − ξ)²           (rotation at node 1, dimension L)
N₃(ξ) = 3ξ² − 2ξ³               (displacement at node 2)
N₄(ξ) = L · ξ²(ξ − 1)           (rotation at node 2, dimension L)
```

### 5.2 Bending Displacement Interpolation

**Bending about z** (y-displacement v, DOFs 1, 5, 7, 11):

```
v(ξ) = v₁·N₁ + θz₁·N₂ + v₂·N₃ + θz₂·N₄
```

**Bending about y** (z-displacement w, DOFs 2, 4, 8, 10) — note the sign
convention for θy due to the right-hand rule:

```
w(ξ) = w₁·N₁ − θy₁·N₂ + w₂·N₃ − θy₂·N₄
```

The negative signs on θy terms affect the sign of cross-coupling geometric
stiffness entries for the y-bending DOFs.

### 5.3 P-Δ Terms (Axial Force Effects)

The P-Δ contribution to the geometric stiffness for transverse DOFs comes
from integrating products of shape function derivatives:

```
k_g[i,j]_PΔ = Fx₂ · ∫₀ᴸ (dΦᵢ/dx)(dΦⱼ/dx) dx
```

where **Φᵢ** is the shape function assigned to DOF i, incorporating the sign
convention from §5.2 (positive for v-plane, negative for θy in w-plane).

**Axial DOFs** (u₁, u₂):
```
k_g[0,0] = k_g[6,6] = Fx₂/L
k_g[0,6] = −Fx₂/L
```

**Torsional-axial coupling** (θx₁, θx₂):
```
k_g[3,3] = k_g[9,9] = Fx₂ · I_ρ / (A · L)
k_g[3,9] = −Fx₂ · I_ρ / (A · L)
```

### 5.4 Torsion-Bending Coupling

Torsional moment Mx₂ couples transverse displacement and rotation DOFs across
the two bending planes. The coupling terms have magnitudes proportional to
**Mx₂/L** (for displacement-rotation pairs) and **Mx₂/2** (for cross-plane
rotation-rotation pairs between nodes).

### 5.5 Moment Coupling

End bending moments (My₁, Mz₁, My₂, Mz₂) couple with torsional DOFs (θx):

- **Moment-displacement**: terms proportional to **M/L** couple transverse
  displacements (v, w) with torsional rotation (θx) at both nodes
- **Moment-rotation**: terms involving linear combinations of end moments
  (weighted by 1/6) couple bending rotations (θy, θz) with torsional
  rotation (θx)

### 5.6 Matrix Properties

- Symmetric: K_g = K_gᵀ
- Zero when Fx₂ = Mx₂ = My₁ = Mz₁ = My₂ = Mz₂ = 0
- Diagonal P-Δ terms scale linearly with Fx₂
- Tension (Fx₂ > 0) stiffens; compression (Fx₂ < 0) softens

## 6. Eigenvalue Problem

On the **free** (unconstrained) DOFs:

1. Extract sub-matrices K_e_ff and K_g_ff
2. Enforce symmetry: K = ½(K + Kᵀ)
3. Check condition numbers (must be finite and < 10¹⁶)
4. Solve: **K_e_ff · φ = −λ · K_g_ff · φ** (note the minus sign on K_g)
5. Handle complex eigenvalues: if the maximum imaginary part relative to the
   maximum magnitude is negligible (< ~10³ε_machine), de-phase the
   eigenvectors and take real parts; otherwise reject
6. Select the **smallest positive** real eigenvalue λ, using a threshold that
   accounts for numerical noise
7. Embed the mode shape into the full global DOF vector (constrained DOFs = 0)

## 7. Global Geometric Stiffness Assembly

For each element:

1. Extract the 12 element DOFs from the global displacement vector
2. Recover local internal forces (§4)
3. Build the local geometric stiffness matrix (§5) from those forces
4. Transform to global coordinates: **K_g_global = Γᵀ · K_g_local · Γ**
5. Add to the global geometric stiffness matrix at the element DOF positions
