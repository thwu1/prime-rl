#!/usr/bin/env python3
"""
NAFEMS LE1 Benchmark: Plane stress elliptic membrane — mesh convergence study.

Domain: first-quadrant annulus between two concentric ellipses.
  Inner ellipse semi-axes: (2.0, 1.0) m
  Outer ellipse semi-axes: (3.25, 2.75) m
Material: E = 210 GPa, nu = 0.3
Load: 10 MPa outward pressure on outer ellipse (edge BC)
BCs: u_x = 0 on x = 0 (edge AB), u_y = 0 on y = 0 (edge CD)
     Inner ellipse (edge DA) is traction-free.
Target: sigma_yy at D = (2.0, 0.0)

"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
import json
import os

# --------------- problem constants ---------------
A_IN, B_IN = 2.0, 1.0          # inner ellipse semi-axes (m)
A_OUT, B_OUT = 3.25, 2.75      # outer ellipse semi-axes (m)
E_PA = 210.0e9                  # Young modulus (Pa)
NU = 0.3                        # Poisson ratio
P_PA = 10.0e6                   # pressure on outer boundary (Pa)
D_XY = np.array([2.0, 0.0])    # evaluation point D


# --------------- mesh generation (gmsh) ---------------
def create_mesh(lc, mesh_path=None):
    """Return mesh data dict for a given characteristic length *lc*.
    If *mesh_path* is given, save the mesh in Gmsh .msh format."""
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("LE1")

    # Geometry via Boolean: (outer disk - inner disk) intersect first-quadrant rect
    od = gmsh.model.occ.addDisk(0, 0, 0, A_OUT, B_OUT)
    iid = gmsh.model.occ.addDisk(0, 0, 0, A_IN, B_IN)
    ann = gmsh.model.occ.cut([(2, od)], [(2, iid)])
    gmsh.model.occ.synchronize()
    ann_tags = [s[1] for s in ann[0] if s[0] == 2]

    rect = gmsh.model.occ.addRectangle(0, 0, 0, A_OUT + 1.0, B_OUT + 1.0)
    res = gmsh.model.occ.intersect([(2, t) for t in ann_tags], [(2, rect)])
    gmsh.model.occ.synchronize()

    surf_tags = [s[1] for s in res[0] if s[0] == 2]
    if not surf_tags:
        gmsh.finalize()
        raise RuntimeError("Geometry creation failed — no surfaces")

    # Classify boundary curves by sampling
    curves = gmsh.model.getEntities(dim=1)
    left_c, bottom_c, outer_c, inner_c = [], [], [], []

    for _, tag in curves:
        bb = gmsh.model.getParametrizationBounds(1, tag)
        ts = np.linspace(bb[0][0], bb[1][0], 50)
        pts = np.array([gmsh.model.getValue(1, tag, [t])[:2] for t in ts])
        xs, ys = pts[:, 0], pts[:, 1]

        if np.allclose(xs, 0, atol=1e-6) and np.max(ys) > 0.5:
            left_c.append(tag)
        elif np.allclose(ys, 0, atol=1e-6) and np.max(xs) > 0.5:
            bottom_c.append(tag)
        else:
            r_out = np.mean(np.abs((xs / A_OUT) ** 2 + (ys / B_OUT) ** 2 - 1))
            r_in = np.mean(np.abs((xs / A_IN) ** 2 + (ys / B_IN) ** 2 - 1))
            if r_out < 0.03:
                outer_c.append(tag)
            elif r_in < 0.03:
                inner_c.append(tag)

    for tags, gid, nm in [
        (left_c, 1, "left"),
        (bottom_c, 2, "bottom"),
        (outer_c, 3, "outer"),
        (inner_c, 4, "inner"),
    ]:
        if tags:
            gmsh.model.addPhysicalGroup(1, tags, tag=gid, name=nm)
    gmsh.model.addPhysicalGroup(2, surf_tags, tag=10, name="domain")

    # Mesh
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", lc)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", lc * 0.25)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.model.mesh.generate(2)

    # Save mesh file if requested
    if mesh_path:
        os.makedirs(os.path.dirname(mesh_path), exist_ok=True)
        gmsh.write(mesh_path)

    # --- extract nodes ---
    ntags, ncoords, _ = gmsh.model.mesh.getNodes()
    nn = len(ntags)
    coords = np.zeros((nn, 2))
    t2i = {}
    for i, t in enumerate(ntags):
        t2i[int(t)] = i
        coords[i] = [ncoords[3 * i], ncoords[3 * i + 1]]

    # --- extract T6 elements (gmsh type 9) ---
    etags, entags = gmsh.model.mesh.getElementsByType(9)
    ne = len(etags)
    elems = np.zeros((ne, 6), dtype=np.int32)
    for i in range(ne):
        for j in range(6):
            elems[i, j] = t2i[int(entags[i * 6 + j])]

    # --- boundary node sets ---
    def _nodes(curve_list):
        s = set()
        for c in curve_list:
            nt, _, _ = gmsh.model.mesh.getNodes(1, c, True)
            s.update(t2i[int(t)] for t in nt)
        return s

    left_n = _nodes(left_c)
    bottom_n = _nodes(bottom_c)

    # --- 3-node line elements on outer boundary (gmsh type 8) ---
    outer_lines = []
    for c in outer_c:
        et, en = gmsh.model.mesh.getElementsByType(8, tag=c)
        for i in range(len(et)):
            outer_lines.append([t2i[int(en[i * 3 + j])] for j in range(3)])

    gmsh.finalize()
    return dict(
        coords=coords,
        elems=elems,
        nn=nn,
        ne=ne,
        left_n=left_n,
        bottom_n=bottom_n,
        outer_lines=outer_lines,
    )


# --------------- T6 shape functions ---------------
def _t6(xi, eta):
    """Return (N, dN/dxi, dN/deta) for 6-node triangle."""
    L1 = 1 - xi - eta
    L2 = xi
    L3 = eta
    N = np.array(
        [
            L1 * (2 * L1 - 1),
            L2 * (2 * L2 - 1),
            L3 * (2 * L3 - 1),
            4 * L1 * L2,
            4 * L2 * L3,
            4 * L3 * L1,
        ]
    )
    dxi = np.array(
        [
            4 * xi + 4 * eta - 3,
            4 * xi - 1,
            0.0,
            4 - 8 * xi - 4 * eta,
            4 * eta,
            -4 * eta,
        ]
    )
    deta = np.array(
        [
            4 * xi + 4 * eta - 3,
            0.0,
            4 * eta - 1,
            -4 * xi,
            4 * xi,
            4 - 4 * xi - 8 * eta,
        ]
    )
    return N, dxi, deta


# 3-point Gauss rule for the unit triangle (area = 1/2)
_TRI_GP = [(1.0 / 6, 1.0 / 6, 1.0 / 6),
           (2.0 / 3, 1.0 / 6, 1.0 / 6),
           (1.0 / 6, 2.0 / 3, 1.0 / 6)]

# Plane stress constitutive matrix (constant)
_D = (E_PA / (1 - NU ** 2)) * np.array(
    [[1.0, NU, 0.0], [NU, 1.0, 0.0], [0.0, 0.0, (1 - NU) / 2]]
)


# --------------- element stiffness ---------------
def _ke(xy6):
    """12x12 stiffness matrix for one T6 plane-stress element."""
    ke = np.zeros((12, 12))
    for xi, eta, w in _TRI_GP:
        _, dxi, deta = _t6(xi, eta)
        J = np.array(
            [
                [dxi @ xy6[:, 0], dxi @ xy6[:, 1]],
                [deta @ xy6[:, 0], deta @ xy6[:, 1]],
            ]
        )
        detJ = J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0]
        Ji = np.array([[J[1, 1], -J[0, 1]], [-J[1, 0], J[0, 0]]]) / detJ

        dNdx = Ji[0, 0] * dxi + Ji[0, 1] * deta
        dNdy = Ji[1, 0] * dxi + Ji[1, 1] * deta

        B = np.zeros((3, 12))
        for k in range(6):
            B[0, 2 * k] = dNdx[k]
            B[1, 2 * k + 1] = dNdy[k]
            B[2, 2 * k] = dNdy[k]
            B[2, 2 * k + 1] = dNdx[k]

        ke += (B.T @ _D @ B) * (detJ * w)
    return ke


# --------------- pressure load on outer boundary ---------------
def _pressure_load(coords, outer_lines, p):
    """Equivalent nodal forces from outward pressure *p* on outer-boundary line elements."""
    ndof = 2 * len(coords)
    f = np.zeros(ndof)

    # 3-point Gauss on [-1, 1] for higher accuracy on curved edges
    gp = [(-np.sqrt(3.0 / 5), 5.0 / 9),
          (0.0, 8.0 / 9),
          (np.sqrt(3.0 / 5), 5.0 / 9)]

    for ln in outer_lines:
        xy = coords[ln]  # (3, 2): corner0, corner1, midside

        for xi_g, w in gp:
            # 3-node line shape functions  (xi in [-1, 1])
            Nl = np.array(
                [xi_g * (xi_g - 1) / 2, xi_g * (xi_g + 1) / 2, 1 - xi_g ** 2]
            )
            dNl = np.array([xi_g - 0.5, xi_g + 0.5, -2 * xi_g])

            x = Nl @ xy[:, 0]
            y = Nl @ xy[:, 1]
            dx = dNl @ xy[:, 0]
            dy = dNl @ xy[:, 1]

            # Right normal of tangent = (dy, -dx); may need flip
            nx, ny = dy, -dx
            # Outward = away from origin (outer ellipse is origin-centered)
            if nx * x + ny * y < 0:
                nx, ny = -nx, -ny

            # (nx, ny) already includes the Jacobian (magnitude = ds/dxi)
            for k in range(3):
                f[2 * ln[k]] += p * nx * Nl[k] * w
                f[2 * ln[k] + 1] += p * ny * Nl[k] * w

    return f


# --------------- stress at a point ---------------
# Natural coords of each T6 local node
_NAT = np.array(
    [(0, 0), (1, 0), (0, 1), (0.5, 0), (0.5, 0.5), (0, 0.5)], dtype=float
)


def _stress_at_node(coords, elems, u_global, node_id):
    """Average stress vector [sigma_xx, sigma_yy, sigma_xy] at *node_id*
    over all incident elements. Returns stress in Pa."""
    stress_list = []
    for e in range(len(elems)):
        en = elems[e]
        loc = -1
        for k in range(6):
            if en[k] == node_id:
                loc = k
                break
        if loc < 0:
            continue

        xy6 = coords[en]
        ue = np.zeros(12)
        for k in range(6):
            ue[2 * k] = u_global[2 * en[k]]
            ue[2 * k + 1] = u_global[2 * en[k] + 1]

        xi, eta = _NAT[loc]
        _, dxi, deta = _t6(xi, eta)

        J = np.array(
            [
                [dxi @ xy6[:, 0], dxi @ xy6[:, 1]],
                [deta @ xy6[:, 0], deta @ xy6[:, 1]],
            ]
        )
        detJ = J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0]
        Ji = np.array([[J[1, 1], -J[0, 1]], [-J[1, 0], J[0, 0]]]) / detJ

        dNdx = Ji[0, 0] * dxi + Ji[0, 1] * deta
        dNdy = Ji[1, 0] * dxi + Ji[1, 1] * deta

        B = np.zeros((3, 12))
        for k in range(6):
            B[0, 2 * k] = dNdx[k]
            B[1, 2 * k + 1] = dNdy[k]
            B[2, 2 * k] = dNdy[k]
            B[2, 2 * k + 1] = dNdx[k]

        stress = _D @ B @ ue  # [sigma_xx, sigma_yy, sigma_xy] in Pa
        stress_list.append(stress)

    if not stress_list:
        return np.zeros(3)
    return np.mean(stress_list, axis=0)


# --------------- FEM solve ---------------
def solve(mesh):
    coords = mesh["coords"]
    elems = mesh["elems"]
    nn = mesh["nn"]
    ndof = 2 * nn

    # ---- global assembly ----
    ne = len(elems)
    sz = ne * 144
    rows = np.zeros(sz, dtype=np.int32)
    cols = np.zeros(sz, dtype=np.int32)
    vals = np.zeros(sz)
    ptr = 0

    for e in range(ne):
        en = elems[e]
        ke = _ke(coords[en])
        dofs = np.empty(12, dtype=np.int32)
        for k in range(6):
            dofs[2 * k] = 2 * en[k]
            dofs[2 * k + 1] = 2 * en[k] + 1

        for i in range(12):
            rows[ptr: ptr + 12] = dofs[i]
            cols[ptr: ptr + 12] = dofs
            vals[ptr: ptr + 12] = ke[i]
            ptr += 12

    K = sparse.coo_matrix((vals, (rows, cols)), shape=(ndof, ndof)).tocsc()

    # ---- load ----
    f = _pressure_load(coords, mesh["outer_lines"], P_PA)

    # ---- boundary conditions (direct elimination) ----
    bc = set()
    for n in mesh["left_n"]:
        bc.add(2 * n)          # u_x = 0
    for n in mesh["bottom_n"]:
        bc.add(2 * n + 1)      # u_y = 0
    free = np.array(sorted(set(range(ndof)) - bc), dtype=np.int32)

    u_free = spsolve(K[np.ix_(free, free)], f[free])
    u = np.zeros(ndof)
    u[free] = u_free

    # ---- stress at D ----
    nearest = int(np.argmin(np.linalg.norm(coords - D_XY, axis=1)))
    stress_pa = _stress_at_node(coords, elems, u, nearest)

    # ---- max displacement magnitude ----
    ux = u[::2]
    uy = u[1::2]
    disp_mag = np.sqrt(ux**2 + uy**2)
    max_disp_m = float(np.max(disp_mag))

    return {
        "sigma_yy_MPa": float(stress_pa[1]) / 1e6,
        "sigma_xx_MPa": float(stress_pa[0]) / 1e6,
        "max_displacement_mm": max_disp_m * 1e3,
    }


# --------------- main: convergence study ---------------
def main():
    mesh_sizes = [0.50, 0.20, 0.10, 0.05]

    os.makedirs("/app/meshes", exist_ok=True)

    results = {
        "benchmark": "NAFEMS_LE1",
        "convergence_study": [],
    }

    for i, lc in enumerate(mesh_sizes):
        level = i + 1
        mesh_path = f"/app/meshes/level_{level}.msh"
        print(f"[{level}/{len(mesh_sizes)}] lc = {lc} m ... ", end="", flush=True)
        try:
            m = create_mesh(lc, mesh_path=mesh_path)
            res = solve(m)
        except Exception as exc:
            print(f"FAILED: {exc}")
            continue

        syy = res["sigma_yy_MPa"]
        sxx = res["sigma_xx_MPa"]
        disp = res["max_displacement_mm"]
        print(
            f"ne={m['ne']}, nn={m['nn']}, "
            f"sigma_yy={syy:.2f} MPa, sigma_xx={sxx:.2f} MPa, "
            f"max_disp={disp:.4f} mm"
        )
        results["convergence_study"].append(
            {
                "level": level,
                "mesh_size": lc,
                "num_elements": int(m["ne"]),
                "num_nodes": int(m["nn"]),
                "sigma_yy_MPa": round(syy, 2),
                "sigma_xx_MPa": round(sxx, 2),
                "max_displacement_mm": round(disp, 6),
            }
        )

    with open("/app/results.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
