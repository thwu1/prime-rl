"""
Complete implementation of SIMP topology optimization framework.
All seven functions fully implemented.
"""

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


def compute_element_stiffness(nu):
    """
    8x8 element stiffness matrix for a unit-square Q4 plane stress element
    with unit Young's modulus, via the closed-form from Sigmund (2001).
    """
    k = np.array([
        1.0 / 2 - nu / 6,
        1.0 / 8 + nu / 8,
        -1.0 / 4 - nu / 12,
        -1.0 / 8 + 3 * nu / 8,
        -1.0 / 4 + nu / 12,
        -1.0 / 8 - nu / 8,
        nu / 6,
        1.0 / 8 - 3 * nu / 8,
    ])
    KE = (
        1.0
        / (1.0 - nu ** 2)
        * np.array(
            [
                [k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7]],
                [k[1], k[0], k[7], k[6], k[5], k[4], k[3], k[2]],
                [k[2], k[7], k[0], k[5], k[6], k[3], k[4], k[1]],
                [k[3], k[6], k[5], k[0], k[7], k[2], k[1], k[4]],
                [k[4], k[5], k[6], k[7], k[0], k[1], k[2], k[3]],
                [k[5], k[4], k[3], k[2], k[1], k[0], k[7], k[6]],
                [k[6], k[3], k[4], k[1], k[2], k[7], k[0], k[5]],
                [k[7], k[2], k[1], k[4], k[3], k[6], k[5], k[0]],
            ]
        )
    )
    return KE


def get_dof_indices(nelx, nely, elx, ely):
    """Return the 8 global DOF indices for element (elx, ely)."""
    n1 = (nely + 1) * elx + ely
    n2 = (nely + 1) * (elx + 1) + ely
    return np.array(
        [
            2 * n1,
            2 * n1 + 1,
            2 * n2,
            2 * n2 + 1,
            2 * (n2 + 1),
            2 * (n2 + 1) + 1,
            2 * (n1 + 1),
            2 * (n1 + 1) + 1,
        ]
    )


def assemble_global_stiffness(nelx, nely, x, penal, KE, E0, Emin):
    """Assemble global stiffness matrix with SIMP penalization in COO format."""
    ndof = 2 * (nelx + 1) * (nely + 1)
    num_entries = nelx * nely * 64
    iK = np.zeros(num_entries, dtype=int)
    jK = np.zeros(num_entries, dtype=int)
    sK = np.zeros(num_entries)

    idx = 0
    for elx in range(nelx):
        for ely in range(nely):
            edof = get_dof_indices(nelx, nely, elx, ely)
            Ee = Emin + x[ely, elx] ** penal * (E0 - Emin)
            for i in range(8):
                for j in range(8):
                    iK[idx] = edof[i]
                    jK[idx] = edof[j]
                    sK[idx] = Ee * KE[i, j]
                    idx += 1

    K = coo_matrix((sK, (iK, jK)), shape=(ndof, ndof)).tocsc()
    return K


def apply_boundary_conditions_and_solve(K, F, fixed_dofs, ndof):
    """Eliminate fixed DOFs and solve KU=F with sparse direct solver."""
    all_dofs = np.arange(ndof)
    free_dofs = np.setdiff1d(all_dofs, fixed_dofs)
    K_ff = K[free_dofs, :][:, free_dofs]
    F_f = F[free_dofs]
    U = np.zeros(ndof)
    U[free_dofs] = spsolve(K_ff, F_f)
    return U


def compute_sensitivities(nelx, nely, x, U, KE, penal, E0, Emin):
    """Adjoint compliance sensitivities: dc/dx_e = -p*x^(p-1)*(E0-Emin)*ue'*KE*ue."""
    dc = np.zeros((nely, nelx))
    dv = np.ones((nely, nelx))

    for elx in range(nelx):
        for ely in range(nely):
            edof = get_dof_indices(nelx, nely, elx, ely)
            ue = U[edof]
            dc[ely, elx] = (
                -penal
                * x[ely, elx] ** (penal - 1)
                * (E0 - Emin)
                * float(ue @ KE @ ue)
            )

    return dc, dv


def apply_density_filter(nelx, nely, rmin, x, dc):
    """Sigmund's sensitivity filter with weighted neighbourhood averaging."""
    dc_filtered = np.zeros_like(dc)
    ceil_rmin = int(np.ceil(rmin))

    for i in range(nelx):
        for j in range(nely):
            sum_weight = 0.0
            for ii in range(max(i - ceil_rmin + 1, 0), min(i + ceil_rmin, nelx)):
                for jj in range(max(j - ceil_rmin + 1, 0), min(j + ceil_rmin, nely)):
                    dist = np.sqrt(float((i - ii) ** 2 + (j - jj) ** 2))
                    weight = max(0.0, rmin - dist)
                    dc_filtered[j, i] += weight * x[jj, ii] * dc[jj, ii]
                    sum_weight += weight
            dc_filtered[j, i] /= max(1e-3, x[j, i]) * sum_weight

    return dc_filtered


def optimality_criteria_update(nelx, nely, x, dc, dv, volfrac, move=0.2):
    """OC density update with bisection on the Lagrange multiplier."""
    l1 = 0.0
    l2 = 1e9

    while l2 - l1 > 1e-9:
        lmid = 0.5 * (l1 + l2)
        x_new = np.maximum(
            0.001,
            np.maximum(
                x - move,
                np.minimum(
                    1.0,
                    np.minimum(x + move, x * np.sqrt(-dc / dv / lmid)),
                ),
            ),
        )

        if x_new.sum() > volfrac * nelx * nely:
            l1 = lmid
        else:
            l2 = lmid

    return x_new
