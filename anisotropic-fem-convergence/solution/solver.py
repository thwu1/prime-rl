#!/usr/bin/env python3
"""
Finite element solver for the anisotropic Helmholtz equation.

Implements P1 and P2 Lagrange elements on triangular meshes with
Duffy-transform quadrature, Vandermonde-based basis construction,
tensor-coefficient assembly, and L2 error convergence study.

"""
import numpy as np
from scipy.sparse import lil_matrix, csr_matrix
from scipy.sparse.linalg import spsolve
import json
import sys

sys.path.insert(0, '/app')
from mesh import unit_square_mesh, boundary_nodes
from problem_spec import diffusion_tensor, reaction, exact_solution, forcing


# ---------------------------------------------------------------------------
# Quadrature
# ---------------------------------------------------------------------------

def gauss_legendre_01(n):
    """n-point Gauss-Legendre quadrature on [0, 1]."""
    pts, wts = np.polynomial.legendre.leggauss(n)
    return (pts + 1.0) / 2.0, wts / 2.0


def triangle_quadrature(n_pts):
    """Quadrature on the reference triangle (0,0)-(1,0)-(0,1).

    Uses Duffy transform: (s, t) in [0,1]^2 -> (s*(1-t), t) in triangle.
    Jacobian of the Duffy transform is (1-t).

    Returns (points, weights) with n_pts^2 quadrature points.
    """
    s_pts, s_wts = gauss_legendre_01(n_pts)
    t_pts, t_wts = gauss_legendre_01(n_pts)

    nq = n_pts * n_pts
    points = np.zeros((nq, 2))
    weights = np.zeros(nq)

    idx = 0
    for i in range(n_pts):
        for j in range(n_pts):
            points[idx, 0] = s_pts[i] * (1.0 - t_pts[j])
            points[idx, 1] = t_pts[j]
            weights[idx] = s_wts[i] * t_wts[j] * (1.0 - t_pts[j])
            idx += 1

    return points, weights


# ---------------------------------------------------------------------------
# Lagrange element
# ---------------------------------------------------------------------------

def lagrange_nodes_triangle(degree):
    """Equispaced Lagrange nodes on the reference triangle.

    Ordering: for j = 0..degree, for i = 0..degree-j,
    node at (i/degree, j/degree).
    """
    nodes = []
    for j in range(degree + 1):
        for i in range(degree + 1 - j):
            nodes.append([float(i) / degree, float(j) / degree])
    return np.array(nodes)


def eval_monomials(degree, x, y):
    """Evaluate monomials up to total degree.

    Ordering: for d = 0..degree, for j = 0..d,
    monomial x^(d-j) * y^j.
    """
    vals = []
    for d in range(degree + 1):
        for j in range(d + 1):
            i = d - j
            vals.append(x**i * y**j)
    return np.array(vals, dtype=float)


def eval_monomial_grads(degree, x, y):
    """Evaluate gradients [d/dx, d/dy] of monomials up to total degree.

    Returns (n_monomials, 2) array.
    """
    grads = []
    for d in range(degree + 1):
        for j in range(d + 1):
            i = d - j
            dmdx = float(i) * x**(i - 1) * y**j if i > 0 else 0.0
            dmdy = x**i * float(j) * y**(j - 1) if j > 0 else 0.0
            grads.append([dmdx, dmdy])
    return np.array(grads, dtype=float)


class LagrangeElement:
    """Lagrange finite element on the reference triangle."""

    def __init__(self, degree):
        self.degree = degree
        self.nodes = lagrange_nodes_triangle(degree)
        self.n_dofs = len(self.nodes)

        # Vandermonde matrix: V[i, j] = monomial_j(node_i)
        n = self.n_dofs
        V = np.zeros((n, n))
        for k in range(n):
            V[k, :] = eval_monomials(degree, self.nodes[k, 0], self.nodes[k, 1])
        self.V_inv = np.linalg.inv(V)

    def tabulate(self, points):
        """Evaluate all basis functions at given points.

        Returns (n_points, n_dofs) array.
        """
        nq = len(points)
        vals = np.zeros((nq, self.n_dofs))
        for q in range(nq):
            m = eval_monomials(self.degree, points[q, 0], points[q, 1])
            vals[q, :] = m @ self.V_inv
        return vals

    def tabulate_grad(self, points):
        """Evaluate gradients of all basis functions at given points.

        Returns (n_points, n_dofs, 2) array.
        Each entry [q, i, :] = [d phi_i / d xi, d phi_i / d eta] at point q.
        """
        nq = len(points)
        grads = np.zeros((nq, self.n_dofs, 2))
        for q in range(nq):
            dm = eval_monomial_grads(self.degree, points[q, 0], points[q, 1])
            grads[q, :, :] = self.V_inv.T @ dm
        return grads


# ---------------------------------------------------------------------------
# P2 DOF map
# ---------------------------------------------------------------------------

def build_p2_dof_map(coords, cells):
    """Augment a P1 mesh with P2 edge midpoint DOFs.

    Local node ordering matches lagrange_nodes_triangle(2):
        0: (0,   0  ) -> vertex v0
        1: (0.5, 0  ) -> midpoint of edge v0-v1
        2: (1,   0  ) -> vertex v1
        3: (0,   0.5) -> midpoint of edge v0-v2
        4: (0.5, 0.5) -> midpoint of edge v1-v2
        5: (0,   1  ) -> vertex v2

    Returns (p2_coords, p2_dof_cells, n_dofs).
    """
    n_verts = len(coords)
    edge_map = {}
    edge_midpoints = []

    p2_cells = np.zeros((len(cells), 6), dtype=int)

    def get_edge_dof(va, vb):
        key = (min(va, vb), max(va, vb))
        if key not in edge_map:
            edge_map[key] = len(edge_midpoints)
            edge_midpoints.append((coords[va] + coords[vb]) / 2.0)
        return n_verts + edge_map[key]

    for c in range(len(cells)):
        v0, v1, v2 = cells[c]
        p2_cells[c, 0] = v0                    # local 0 -> vertex v0
        p2_cells[c, 1] = get_edge_dof(v0, v1)  # local 1 -> midpoint v0-v1
        p2_cells[c, 2] = v1                    # local 2 -> vertex v1
        p2_cells[c, 3] = get_edge_dof(v0, v2)  # local 3 -> midpoint v0-v2
        p2_cells[c, 4] = get_edge_dof(v1, v2)  # local 4 -> midpoint v1-v2
        p2_cells[c, 5] = v2                    # local 5 -> vertex v2

    p2_coords = np.vstack([coords, np.array(edge_midpoints)])
    return p2_coords, p2_cells, len(p2_coords)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble(coords, cells, dof_cells, n_dofs, element, n_quad):
    """Assemble global system for -div(K grad u) + c u = f.

    The bilinear form is:
        a(u, v) = int (grad v)^T K (grad u) + c u v  dx

    Uses Jacobian transform from reference to physical element:
        F(xi) = x0 + J xi,   J = [x1-x0 | x2-x0]
        grad_x phi = J^{-T} @ (grad_xi phi)
    """
    qpts, qwts = triangle_quadrature(n_quad)
    phi = element.tabulate(qpts)             # (nq, n_local)
    dphi_ref = element.tabulate_grad(qpts)   # (nq, n_local, 2)

    n_local = element.n_dofs
    nq = len(qpts)

    A = lil_matrix((n_dofs, n_dofs))
    b = np.zeros(n_dofs)

    for c in range(len(cells)):
        x0 = coords[cells[c, 0]]
        x1 = coords[cells[c, 1]]
        x2 = coords[cells[c, 2]]

        # Jacobian of affine map: F(xi, eta) = x0 + (x1-x0)*xi + (x2-x0)*eta
        J = np.column_stack([x1 - x0, x2 - x0])   # 2x2
        det_J = abs(np.linalg.det(J))
        J_inv = np.linalg.inv(J)

        Ae = np.zeros((n_local, n_local))
        be = np.zeros(n_local)

        for q in range(nq):
            # Physical coordinates at this quadrature point
            x_phys = x0 + J @ qpts[q]
            xp, yp = x_phys

            K = diffusion_tensor(xp, yp)
            c_val = reaction(xp, yp)
            f_val = forcing(xp, yp)

            # Transform reference gradients to physical:
            # grad_x phi_i = J^{-T} grad_xi phi_i
            # In row form: dphi_phys = dphi_ref[q] @ J_inv
            dphi_phys = dphi_ref[q] @ J_inv   # (n_local, 2)

            w = det_J * qwts[q]

            # Stiffness contribution: int (grad phi_i)^T K (grad phi_j) dx
            Ae += (dphi_phys @ K @ dphi_phys.T) * w

            # Mass contribution: int c phi_i phi_j dx
            Ae += c_val * np.outer(phi[q], phi[q]) * w

            # Load vector: int f phi_i dx
            be += f_val * phi[q] * w

        # Scatter into global system
        dofs = dof_cells[c]
        for i in range(n_local):
            b[dofs[i]] += be[i]
            for j in range(n_local):
                A[dofs[i], dofs[j]] += Ae[i, j]

    return csr_matrix(A), b


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

def apply_dirichlet_bc(A, b, bc_nodes):
    """Apply homogeneous Dirichlet BCs by row elimination."""
    A = A.tolil()
    for node in bc_nodes:
        A[node, :] = 0
        A[node, node] = 1.0
        b[node] = 0.0
    return csr_matrix(A), b


# ---------------------------------------------------------------------------
# Error computation
# ---------------------------------------------------------------------------

def compute_l2_error(coords, cells, dof_cells, u_h, element, n_quad):
    """Compute L2 error ||u_exact - u_h|| via quadrature."""
    qpts, qwts = triangle_quadrature(n_quad)
    phi = element.tabulate(qpts)

    err_sq = 0.0
    for c in range(len(cells)):
        x0 = coords[cells[c, 0]]
        x1 = coords[cells[c, 1]]
        x2 = coords[cells[c, 2]]

        J = np.column_stack([x1 - x0, x2 - x0])
        det_J = abs(np.linalg.det(J))

        u_local = u_h[dof_cells[c]]

        for q in range(len(qpts)):
            x_phys = x0 + J @ qpts[q]
            u_ex = exact_solution(x_phys[0], x_phys[1])
            u_fe = phi[q] @ u_local
            err_sq += (u_ex - u_fe)**2 * det_J * qwts[q]

    return np.sqrt(err_sq)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_helmholtz(n, degree):
    """Solve on n x n mesh with Lagrange elements of given degree."""
    coords, cells = unit_square_mesh(n)
    element = LagrangeElement(degree)

    if degree == 1:
        all_coords = coords
        dof_cells = cells
        n_dofs = len(coords)
    elif degree == 2:
        all_coords, dof_cells, n_dofs = build_p2_dof_map(coords, cells)
    else:
        raise ValueError(f"Unsupported degree: {degree}")

    bc = boundary_nodes(all_coords)

    # Quadrature: degree+3 points per 1D direction gives sufficient accuracy
    n_quad = degree + 3

    A, b = assemble(coords, cells, dof_cells, n_dofs, element, n_quad)
    A, b = apply_dirichlet_bc(A, b, bc)
    u_h = spsolve(A, b)

    # Use higher quadrature for error to avoid under-integration
    err = compute_l2_error(coords, cells, dof_cells, u_h, element, n_quad + 2)
    return err


# ---------------------------------------------------------------------------
# Convergence study
# ---------------------------------------------------------------------------

def main():
    mesh_sizes = [4, 8, 16, 32]
    results = {}

    for degree, label in [(1, "p1"), (2, "p2")]:
        print(f"\n--- {label.upper()} elements ---")
        errors = []
        for n in mesh_sizes:
            e = solve_helmholtz(n, degree)
            errors.append(e)
            print(f"  n={n:3d}:  L2 error = {e:.6e}")

        # Convergence rates from consecutive refinements
        rates = []
        for i in range(len(errors) - 1):
            r = np.log(errors[i] / errors[i + 1]) / np.log(2.0)
            rates.append(r)
            print(f"  rate {mesh_sizes[i]}->{mesh_sizes[i+1]}: {r:.4f}")

        # Average of last two rates (asymptotic regime)
        avg_rate = float(np.mean(rates[-2:]))
        print(f"  average convergence rate: {avg_rate:.4f}")

        results[label] = {
            "mesh_sizes": mesh_sizes,
            "errors": [float(e) for e in errors],
            "convergence_rate": avg_rate
        }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
