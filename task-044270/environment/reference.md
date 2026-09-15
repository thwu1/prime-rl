# 3D Beam Frame Buckling Analysis — Reference

## 1. DOF Convention

Each node has 6 degrees of freedom in the order:

    [u_x, u_y, u_z, theta_x, theta_y, theta_z]

For element DOFs (12 total), node i occupies indices 0-5 and node j
occupies indices 6-11. The local x-axis runs from node i to node j.

## 2. Geometric Stiffness Matrix K_g

K_g is a 12x12 symmetric matrix that represents second-order geometric
effects in a beam element. It depends on the element's internal forces
from the prebuckling (linear static) analysis:

| Symbol | Description                              | Index in f_local |
|--------|------------------------------------------|------------------|
| P      | Axial force at node j (+ = tension)      | f_local[6]       |
| T      | Torsional moment at node j about x-axis  | f_local[9]       |
| M_y1   | Bending moment at node i about y-axis    | f_local[4]       |
| M_z1   | Bending moment at node i about z-axis    | f_local[5]       |
| M_y2   | Bending moment at node j about y-axis    | f_local[10]      |
| M_z2   | Bending moment at node j about z-axis    | f_local[11]      |

Additional parameters: L (element length), A (cross-section area),
I_p (polar moment of inertia = I_y + I_z for a symmetric section).

The complete K_g formulation for 3D Euler-Bernoulli beam elements captures:

- **Axial force effects**: P-Delta (transverse displacement × axial force)
  and P-theta (rotational × axial force) interactions. These are the
  dominant terms and govern classical column buckling.
- **Torsion-bending coupling**: Torsional moment T interacting with
  lateral displacements and rotations about both y and z axes.
- **Moment-displacement coupling**: End bending moments (M_y, M_z)
  coupling with torsional and lateral DOFs at both nodes.

A simplified axial-force-only version (with T = M_y = M_z = 0) is
shown in `/app/octave_ref/verify_kg.m` (function `build_kg_axial`).
The complete formulation including all coupling terms is derived in:

- McGuire, Gallagher & Ziemian, "Matrix Structural Analysis", 2nd Ed., Ch. 13
- Yang & Kuo, "Theory of Beam-Columns", Vol. 2
- Przemieniecki, "Theory of Matrix Structural Analysis", Ch. 10

Assembly procedure: initialize as 12x12 zeros, fill upper triangle
(row < col), symmetrize via k_g = k_g + k_g^T, then set diagonal entries
(overwriting the zeros on the diagonal).

## 3. Internal Force Recovery

Given the global displacement vector u (from the linear solve),
element internal forces in local coordinates are obtained as:

    u_elem_global = u[element_dofs]       # 12-vector of global displacements
    u_elem_local  = Gamma @ u_elem_global # transform to local frame
    f_local       = K_e_local @ u_elem_local

where K_e_local is the local elastic stiffness matrix and Gamma is
the 12x12 transformation matrix.

## 4. Global Geometric Stiffness Assembly

Same procedure as elastic stiffness assembly:

    For each element:
        K_g_local  = local_geometric_stiffness(L, A, I_p, P, T, ...)
        K_g_global_elem = Gamma^T @ K_g_local @ Gamma
        K_g[dofs, dofs] += K_g_global_elem

## 5. Eigenvalue Buckling Problem

The linearized buckling eigenvalue problem on free DOFs:

    K_e_ff @ phi = -lambda * K_g_ff @ phi

where K_e_ff and K_g_ff are the free-free partitions of the elastic
and geometric stiffness matrices.

The smallest positive real eigenvalue lambda is the elastic critical
load factor. The critical buckling load is P_cr = lambda * P_ref.

### 5.1 Numerical Considerations

- Enforce symmetry before solving: K = 0.5*(K + K^T)
- Check matrix conditioning (reject if cond > 1e16)
- Eigenvalues may have small imaginary parts due to numerics;
  discard if relative imaginary part exceeds ~1e-10
- Select the smallest positive eigenvalue with a threshold of
  max(1e-12, eps_scale * max|eigenvalues|)
