#!/usr/bin/env python3
"""
2D Stokes Lid-Driven Cavity Solver
MAC staggered grid with block Schur complement preconditioning.

Reads configuration from scattered files in /app/config/.

Staggered grid layout on [0,Lx] x [0,Ly] with nx x ny cells:
  - Pressure p: cell centers at ((i+0.5)*dx, (j+0.5)*dy)
  - u-velocity: vertical cell faces at (i*dx, (j+0.5)*dy)
  - v-velocity: horizontal cell faces at ((i+0.5)*dx, j*dy)

Interior unknowns:
  - u: faces i=1..nx-1, j=0..ny-1  ->  nu = (nx-1)*ny
  - v: faces i=0..nx-1, j=1..ny-1  ->  nv = nx*(ny-1)
  - p: cells i=0..nx-1, j=0..ny-1  ->  np_ = nx*ny
"""
import numpy as np
import json
import os
from scipy import sparse
from scipy.sparse.linalg import gmres, LinearOperator, splu


def load_config():
    """Load all configuration files from /app/config/."""
    config = {}
    for name in ['domain', 'mesh', 'physics', 'boundary_conditions',
                 'solver_settings', 'output_spec']:
        with open(f'/app/config/{name}.json') as f:
            config[name] = json.load(f)
    return config


def build_viscous_u(nx, ny, dx, dy, mu, U_lid):
    """Build viscous Laplacian for u-faces and RHS from boundary conditions."""
    nu = (nx - 1) * ny
    rows, cols, vals = [], [], []
    rhs = np.zeros(nu)

    for i in range(1, nx):
        for j in range(ny):
            k = (i - 1) * ny + j
            diag = 0.0

            for ni in [i - 1, i + 1]:
                if 1 <= ni <= nx - 1:
                    rows.append(k)
                    cols.append((ni - 1) * ny + j)
                    vals.append(-mu / dx**2)
                    diag += mu / dx**2
                else:
                    diag += mu / dx**2

            for nj in [j - 1, j + 1]:
                if 0 <= nj <= ny - 1:
                    rows.append(k)
                    cols.append((i - 1) * ny + nj)
                    vals.append(-mu / dy**2)
                    diag += mu / dy**2
                else:
                    u_wall = U_lid if nj >= ny else 0.0
                    diag += 2 * mu / dy**2
                    rhs[k] += 2 * mu / dy**2 * u_wall

            rows.append(k)
            cols.append(k)
            vals.append(diag)

    Au = sparse.coo_matrix((vals, (rows, cols)), shape=(nu, nu)).tocsr()
    return Au, rhs


def build_viscous_v(nx, ny, dx, dy, mu):
    """Build viscous Laplacian for v-faces and RHS from boundary conditions."""
    nv = nx * (ny - 1)
    rows, cols, vals = [], [], []
    rhs = np.zeros(nv)

    for i in range(nx):
        for j in range(1, ny):
            k = i * (ny - 1) + (j - 1)
            diag = 0.0

            for ni in [i - 1, i + 1]:
                if 0 <= ni <= nx - 1:
                    rows.append(k)
                    cols.append(ni * (ny - 1) + (j - 1))
                    vals.append(-mu / dx**2)
                    diag += mu / dx**2
                else:
                    diag += 2 * mu / dx**2

            for nj in [j - 1, j + 1]:
                if 1 <= nj <= ny - 1:
                    rows.append(k)
                    cols.append(i * (ny - 1) + (nj - 1))
                    vals.append(-mu / dy**2)
                    diag += mu / dy**2
                else:
                    diag += mu / dy**2

            rows.append(k)
            cols.append(k)
            vals.append(diag)

    Av = sparse.coo_matrix((vals, (rows, cols)), shape=(nv, nv)).tocsr()
    return Av, rhs


def build_gradient_operators(nx, ny, dx, dy):
    """Build pressure gradient operators Gx and Gy."""
    nu = (nx - 1) * ny
    nv = nx * (ny - 1)
    np_ = nx * ny

    gx_r, gx_c, gx_v = [], [], []
    for i in range(1, nx):
        for j in range(ny):
            k = (i - 1) * ny + j
            gx_r.append(k); gx_c.append(i * ny + j); gx_v.append(1.0 / dx)
            gx_r.append(k); gx_c.append((i - 1) * ny + j); gx_v.append(-1.0 / dx)
    Gx = sparse.coo_matrix((gx_v, (gx_r, gx_c)), shape=(nu, np_)).tocsr()

    gy_r, gy_c, gy_v = [], [], []
    for i in range(nx):
        for j in range(1, ny):
            k = i * (ny - 1) + (j - 1)
            gy_r.append(k); gy_c.append(i * ny + j); gy_v.append(1.0 / dy)
            gy_r.append(k); gy_c.append(i * ny + (j - 1)); gy_v.append(-1.0 / dy)
    Gy = sparse.coo_matrix((gy_v, (gy_r, gy_c)), shape=(nv, np_)).tocsr()

    return Gx, Gy


def solve_stokes():
    cfg = load_config()

    nx = cfg['mesh']['nx']
    ny = cfg['mesh']['ny']
    Lx = cfg['domain']['Lx']
    Ly = cfg['domain']['Ly']
    mu = cfg['physics']['mu']
    U_lid = cfg['boundary_conditions']['top']['velocity'][0]
    tol = cfg['solver_settings']['tolerance']
    maxiter = cfg['solver_settings']['max_iterations']
    output_dir = cfg['output_spec']['directory']

    dx = Lx / nx
    dy = Ly / ny

    nu = (nx - 1) * ny
    nv = nx * (ny - 1)
    np_ = nx * ny
    ntot = nu + nv + np_

    eps = 1e-8

    Au, fu = build_viscous_u(nx, ny, dx, dy, mu, U_lid)
    Av, fv = build_viscous_v(nx, ny, dx, dy, mu)
    Gx, Gy = build_gradient_operators(nx, ny, dx, dy)

    A_block = sparse.block_diag([Au, Av], format='csr')
    G_full = sparse.vstack([Gx, Gy], format='csr')
    D_full = -G_full.T.tocsr()

    P_reg = -eps * sparse.eye(np_, format='csr')

    K = sparse.bmat([
        [A_block, G_full],
        [D_full, P_reg]
    ], format='csr')

    rhs = np.concatenate([fu, fv, np.zeros(np_)])

    A_diag_inv = sparse.diags(1.0 / A_block.diagonal())
    S_a = P_reg - D_full @ A_diag_inv @ G_full
    S_a = S_a.tocsc()

    A_lu = splu(A_block.tocsc())
    S_lu = splu(S_a)

    def precond_matvec(r):
        r_vel = r[:nu + nv]
        r_p = r[nu + nv:]
        z_p = -S_lu.solve(r_p)
        z_vel = A_lu.solve(r_vel - G_full @ z_p)
        return np.concatenate([z_vel, z_p])

    M = LinearOperator((ntot, ntot), matvec=precond_matvec)

    iter_count = [0]
    res_history = []

    def callback(pr_norm):
        iter_count[0] += 1
        res_history.append(float(pr_norm))

    x, info = gmres(
        K, rhs, M=M,
        rtol=tol, atol=0.0,
        maxiter=10,
        restart=min(200, ntot),
        callback=callback,
        callback_type='pr_norm'
    )

    converged = (info == 0)

    u_int = x[:nu]
    v_int = x[nu:nu + nv]
    p_vec = x[nu + nv:]

    u_face = np.zeros((nx + 1, ny))
    u_face[1:nx, :] = u_int.reshape((nx - 1, ny))

    v_face = np.zeros((nx, ny + 1))
    v_face[:, 1:ny] = v_int.reshape((nx, ny - 1))

    u_cc = 0.5 * (u_face[:nx, :] + u_face[1:, :])
    v_cc = 0.5 * (v_face[:, :ny] + v_face[:, 1:])

    p_grid = p_vec.reshape((nx, ny))
    p_grid -= np.mean(p_grid)

    div_grid = ((u_face[1:, :] - u_face[:nx, :]) / dx
                + (v_face[:, 1:] - v_face[:, :ny]) / dy)

    os.makedirs(output_dir, exist_ok=True)

    np.savetxt(os.path.join(output_dir, 'velocity_u.csv'),
               u_cc.T, delimiter=',', fmt='%.12e')
    np.savetxt(os.path.join(output_dir, 'velocity_v.csv'),
               v_cc.T, delimiter=',', fmt='%.12e')
    np.savetxt(os.path.join(output_dir, 'pressure.csv'),
               p_grid.T, delimiter=',', fmt='%.12e')
    np.savetxt(os.path.join(output_dir, 'divergence.csv'),
               div_grid.T, delimiter=',', fmt='%.12e')

    solver_info = {
        'iterations': iter_count[0],
        'final_residual': res_history[-1] if res_history else None,
        'converged': converged,
    }
    with open(os.path.join(output_dir, 'solver_info.json'), 'w') as f:
        json.dump(solver_info, f, indent=2)

    print(f"Solver {'converged' if converged else 'FAILED'} "
          f"in {iter_count[0]} iterations")
    print(f"Final residual: "
          f"{res_history[-1]:.2e}" if res_history else "N/A")
    print(f"Max |divergence|: {np.max(np.abs(div_grid)):.2e}")
    print(f"Max speed: {np.max(np.sqrt(u_cc**2 + v_cc**2)):.4f}")


if __name__ == '__main__':
    solve_stokes()
