"""Pore network transport simulator — reference implementation."""


import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.integrate import solve_ivp
from numpy.linalg import norm


def build_cubic_network(shape, spacing=1.0):
    """Build a cubic pore network with C-order pore indexing."""
    shape = tuple(shape)
    Nx, Ny, Nz = shape
    Np = Nx * Ny * Nz
    idx = np.arange(Np)
    ijk = np.array(np.unravel_index(idx, shape)).T  # (Np, 3)
    coords = ijk.astype(float) * spacing

    conns_parts = []
    for axis in range(3):
        mask = ijk[:, axis] < shape[axis] - 1
        src = idx[mask]
        dst_ijk = ijk[mask].copy()
        dst_ijk[:, axis] += 1
        dst = np.ravel_multi_index(dst_ijk.T, shape)
        conns_parts.append(np.column_stack([src, dst]))
    conns = np.vstack(conns_parts) if any(len(c) > 0 for c in conns_parts) \
        else np.empty((0, 2), dtype=int)

    return {
        'coords': coords, 'conns': conns,
        'Np': Np, 'Nt': len(conns),
        'left': ijk[:, 0] == 0,
        'right': ijk[:, 0] == Nx - 1,
        'front': ijk[:, 1] == 0,
        'back': ijk[:, 1] == Ny - 1,
        'bottom': ijk[:, 2] == 0,
        'top': ijk[:, 2] == Nz - 1,
    }


def assemble_coefficient_matrix(Np, conns, conductances):
    """Build symmetric graph Laplacian weighted by throat conductances."""
    g = np.broadcast_to(
        np.asarray(conductances, dtype=float), len(conns)
    ).copy()
    i0, i1 = conns[:, 0], conns[:, 1]
    row = np.concatenate([i0, i1, i0, i1])
    col = np.concatenate([i1, i0, i0, i1])
    data = np.concatenate([-g, -g, g, g])
    return sparse.coo_matrix((data, (row, col)), shape=(Np, Np)).tocsr()


def apply_value_bc(A, b, pore_indices, values):
    """Dirichlet BC elimination: returns (A_mod, b_mod)."""
    pore_indices = np.asarray(pore_indices, dtype=int)
    values = np.broadcast_to(
        np.asarray(values, dtype=float), pore_indices.shape
    ).copy()

    b = b.copy()
    A_csc = A.tocsc()
    bc_contrib = A_csc[:, pore_indices] @ values
    b -= np.asarray(bc_contrib).ravel()

    A_lil = A_csc.tolil()
    for p in pore_indices:
        A_lil[p, :] = 0
        A_lil[:, p] = 0
        A_lil[p, p] = 1.0
    b[pore_indices] = values

    return A_lil.tocsr(), b


def solve_diffusion(network, conductances, bc_specs):
    """Solve steady-state Fickian diffusion Ax = b."""
    Np = network['Np']
    A = assemble_coefficient_matrix(Np, network['conns'], conductances)
    b = np.zeros(Np)
    for pores, vals in bc_specs:
        A, b = apply_value_bc(A, b, np.asarray(pores), vals)
    return spsolve(A, b)


def solve_reactive_transport(network, conductances, bc_specs,
                              source_pores, prefactor, exponent,
                              max_iter=5000, f_rtol=1e-6, x_rtol=1e-6):
    """Newton-linearized nonlinear reactive transport solver."""
    Np = network['Np']
    conns = network['conns']
    source_pores = np.asarray(source_pores)

    all_bc_p, all_bc_v = [], []
    for pores, vals in bc_specs:
        p = np.asarray(pores)
        v = np.broadcast_to(np.asarray(vals, dtype=float), p.shape).copy()
        all_bc_p.append(p)
        all_bc_v.append(v)
    all_bc_p = np.concatenate(all_bc_p)
    all_bc_v = np.concatenate(all_bc_v)

    x = solve_diffusion(network, conductances, bc_specs)

    for iteration in range(max_iter):
        S1 = prefactor * exponent * x ** (exponent - 1)
        S2 = prefactor * (1 - exponent) * x ** exponent

        A = assemble_coefficient_matrix(Np, conns, conductances)
        b = np.zeros(Np)

        diag = A.diagonal().copy()
        diag[source_pores] -= S1[source_pores]
        A_lil = A.tolil()
        A_lil.setdiag(diag)
        A = A_lil.tocsr()
        b[source_pores] += S2[source_pores]

        A, b = apply_value_bc(A, b, all_bc_p, all_bc_v)
        x_new = spsolve(A, b)

        dx = x_new - x
        if iteration > 0 and norm(dx) < x_rtol * max(norm(x_new), 1.0):
            return {'concentration': x_new, 'converged': True,
                    'num_iter': iteration + 1}
        x = x_new

    return {'concentration': x, 'converged': False, 'num_iter': max_iter}


def solve_transient_diffusion(network, conductances, pore_volumes,
                               bc_specs, x0, tspan):
    """Transient Fickian diffusion via BDF ODE integration."""
    Np = network['Np']
    A = assemble_coefficient_matrix(Np, network['conns'], conductances)
    V = np.broadcast_to(np.asarray(pore_volumes, dtype=float), Np).copy()

    bc_p, bc_v = [], []
    for pores, vals in bc_specs:
        p = np.asarray(pores)
        v = np.broadcast_to(np.asarray(vals, dtype=float), p.shape).copy()
        bc_p.append(p)
        bc_v.append(v)
    bc_pores = np.concatenate(bc_p)
    bc_vals = np.concatenate(bc_v)

    interior = np.ones(Np, dtype=bool)
    interior[bc_pores] = False

    y0 = np.broadcast_to(np.asarray(x0, dtype=float), Np).copy()
    y0[bc_pores] = bc_vals

    def rhs(t, y):
        dy = np.zeros(Np)
        yc = y.copy()
        yc[bc_pores] = bc_vals
        flux_in = -(A @ yc)
        dy[interior] = flux_in[interior] / V[interior]
        return dy

    sol = solve_ivp(rhs, tspan, y0, method='BDF',
                    rtol=1e-8, atol=1e-10)
    result = sol.y[:, -1].copy()
    result[bc_pores] = bc_vals
    return result


def compute_rate(network, conductances, concentration, pores):
    """Net outward flux through specified pores (pre-BC matrix)."""
    A = assemble_coefficient_matrix(
        network['Np'], network['conns'], conductances
    )
    flux = np.asarray(A @ np.asarray(concentration, dtype=float)).ravel()
    return float(flux[pores].sum())


def compute_effective_diffusivity(network, conductances, concentration,
                                   inlet_pores, outlet_pores,
                                   domain_length, cross_section_area):
    """Effective diffusivity from solved concentration field."""
    rate = compute_rate(network, conductances, concentration, inlet_pores)
    c_in = concentration[inlet_pores].mean()
    c_out = concentration[outlet_pores].mean()
    dc = abs(c_out - c_in)
    return abs(rate) * domain_length / (cross_section_area * dc)
