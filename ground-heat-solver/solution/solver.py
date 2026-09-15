
"""
2D FEM Steady-State Ground Heat Transfer Solver

Uses gmsh Python API for geometry definition and mesh generation,
linear triangular finite elements for solving the heat equation,
and outputs to JSON + SQLite.
"""

import gmsh
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
import json
import sqlite3
import os

# Physical group tags for materials
PG_CONCRETE = 1
PG_INSULATION = 2
PG_SOIL = 3

# Physical group tags for boundaries
PG_SLAB_SURF = 10
PG_WALL_TOP = 11
PG_GROUND_SURF = 12
PG_FAR_FIELD = 13
PG_DEEP_GROUND = 14
PG_SYMMETRY = 15


def build_mesh(case_name, params, slab, wall, mesh_dir):
    """
    Build 2D triangular mesh using gmsh Python API.

    Creates geometry with separate surfaces for each material region,
    assigns physical groups for materials and boundaries, generates mesh,
    extracts mesh data, and saves .msh file.
    """
    a = params["slab_half_width_m"]
    far = params["far_field_distance_m"]
    D = params["deep_ground_depth_m"]
    t_s = slab["thickness_m"]
    w_w = wall["width_m"]
    k_slab = slab["conductivity_W_per_mK"]
    k_soil = params["soil_conductivity_W_per_mK"]
    ins = params.get("insulation")
    t_i = ins["thickness_m"] if ins else 0.0
    k_ins = ins["conductivity_W_per_mK"] if ins else None
    W = a + far

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(case_name)

    # Key grid coordinates
    xs = [0.0, a, a + w_w, W]
    if ins and t_i > 0:
        ys = [0.0, t_s, t_s + t_i, D]
    else:
        ys = [0.0, t_s, D]

    nx, ny = len(xs), len(ys)

    # Create points with graded mesh sizes
    pts = {}
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            near = x <= a + w_w + 0.5 and y <= (t_s + t_i + 0.5 if ins else t_s + 0.5)
            mid = x <= a + w_w + 5 or y <= 3.0
            lc = 0.04 if near else (0.4 if mid else 2.5)
            pts[(i, j)] = gmsh.model.geo.addPoint(x, y, 0, lc)

    # Horizontal lines (along x, at each y-level)
    hl = {}
    for j in range(ny):
        for i in range(nx - 1):
            hl[(i, j)] = gmsh.model.geo.addLine(pts[(i, j)], pts[(i + 1, j)])

    # Vertical lines (along y, at each x-level)
    vl = {}
    for i in range(nx):
        for j in range(ny - 1):
            vl[(i, j)] = gmsh.model.geo.addLine(pts[(i, j)], pts[(i, j + 1)])

    # Create rectangular surfaces for each grid cell
    surfs = {}
    for i in range(nx - 1):
        for j in range(ny - 1):
            cl = gmsh.model.geo.addCurveLoop([
                hl[(i, j)],        # top edge, left to right
                vl[(i + 1, j)],    # right edge, top to bottom
                -hl[(i, j + 1)],   # bottom edge, right to left
                -vl[(i, j)],       # left edge, bottom to top
            ])
            surfs[(i, j)] = gmsh.model.geo.addPlaneSurface([cl])

    gmsh.model.geo.synchronize()

    # Classify surfaces by material
    concrete_s, insulation_s, soil_s = [], [], []
    for i in range(nx - 1):
        for j in range(ny - 1):
            y_hi = ys[j + 1]
            x_hi = xs[i + 1]
            y_lo = ys[j]

            if y_hi <= t_s + 1e-9 and x_hi <= a + w_w + 1e-9:
                concrete_s.append(surfs[(i, j)])
            elif (ins and t_i > 0 and
                  y_lo >= t_s - 1e-9 and y_hi <= t_s + t_i + 1e-9 and
                  x_hi <= a + 1e-9):
                insulation_s.append(surfs[(i, j)])
            else:
                soil_s.append(surfs[(i, j)])

    # Material physical groups
    gmsh.model.addPhysicalGroup(2, concrete_s, PG_CONCRETE, "concrete")
    if insulation_s:
        gmsh.model.addPhysicalGroup(2, insulation_s, PG_INSULATION, "insulation")
    gmsh.model.addPhysicalGroup(2, soil_s, PG_SOIL, "soil")

    # Boundary physical groups
    gmsh.model.addPhysicalGroup(1, [hl[(0, 0)]], PG_SLAB_SURF, "slab_surface")
    gmsh.model.addPhysicalGroup(1, [hl[(1, 0)]], PG_WALL_TOP, "wall_top")
    gmsh.model.addPhysicalGroup(1, [hl[(2, 0)]], PG_GROUND_SURF, "ground_surface")
    gmsh.model.addPhysicalGroup(1, [vl[(nx - 1, j)] for j in range(ny - 1)],
                                PG_FAR_FIELD, "far_field")
    gmsh.model.addPhysicalGroup(1, [hl[(i, ny - 1)] for i in range(nx - 1)],
                                PG_DEEP_GROUND, "deep_ground")
    gmsh.model.addPhysicalGroup(1, [vl[(0, j)] for j in range(ny - 1)],
                                PG_SYMMETRY, "symmetry")

    # Generate 2D triangular mesh
    gmsh.model.mesh.generate(2)

    # --- Extract mesh data ---
    # Nodes
    node_tags, coords_flat, _ = gmsh.model.mesh.getNodes()
    coords = coords_flat.reshape(-1, 3)[:, :2]
    n_nodes = len(node_tags)
    tag2idx = {int(t): i for i, t in enumerate(node_tags)}

    # Elements per material physical group
    elements = []
    k_elems = []

    mat_groups = [(PG_CONCRETE, k_slab), (PG_SOIL, k_soil)]
    if k_ins is not None:
        mat_groups.append((PG_INSULATION, k_ins))

    for pg_tag, k_val in mat_groups:
        try:
            entities = gmsh.model.getEntitiesForPhysicalGroup(2, pg_tag)
        except Exception:
            continue
        for ent in entities:
            types, tags, ntags = gmsh.model.mesh.getElements(2, ent)
            for et, _, nt in zip(types, tags, ntags):
                if et == 2:  # 3-node triangle
                    nt = nt.reshape(-1, 3)
                    for row in nt:
                        elements.append([tag2idx[int(n)] for n in row])
                        k_elems.append(k_val)

    elements = np.array(elements, dtype=int)
    k_elems = np.array(k_elems, dtype=np.float64)
    n_elements = len(elements)

    # Boundary node sets
    def boundary_nodes(pg_tag):
        nodes = set()
        try:
            ents = gmsh.model.getEntitiesForPhysicalGroup(1, pg_tag)
            for ent in ents:
                t, _, _ = gmsh.model.mesh.getNodes(1, ent, includeBoundary=True)
                nodes.update(tag2idx[int(x)] for x in t)
        except Exception:
            pass
        return nodes

    slab_nodes = boundary_nodes(PG_SLAB_SURF)
    ground_nodes = boundary_nodes(PG_GROUND_SURF)
    far_nodes = boundary_nodes(PG_FAR_FIELD)
    deep_nodes = boundary_nodes(PG_DEEP_GROUND)

    # Save mesh file
    os.makedirs(mesh_dir, exist_ok=True)
    mesh_path = os.path.join(mesh_dir, f"{case_name}.msh")
    gmsh.write(mesh_path)

    gmsh.finalize()

    return {
        "coords": coords,
        "elements": elements,
        "k_elems": k_elems,
        "n_nodes": n_nodes,
        "n_elements": n_elements,
        "slab_nodes": slab_nodes,
        "ground_nodes": ground_nodes,
        "far_nodes": far_nodes,
        "deep_nodes": deep_nodes,
    }


def solve_fem(mesh_data, params):
    """
    Assemble FEM system, apply BCs, solve, and compute slab heat flux.

    Returns (heat_loss_W_per_m, temperature_array).
    """
    coords = mesh_data["coords"]
    elements = mesh_data["elements"]
    k_elems = mesh_data["k_elems"]
    n = mesh_data["n_nodes"]

    T_in = params["T_indoor_C"]
    T_out = params["T_outdoor_C"]
    T_deep = params["T_deep_ground_C"]

    # Assemble global stiffness matrix (COO format)
    rows, cols, vals = [], [], []

    for e_idx in range(len(elements)):
        n0, n1, n2 = elements[e_idx]
        x0, y0 = coords[n0]
        x1, y1 = coords[n1]
        x2, y2 = coords[n2]

        # Signed 2*area
        A2 = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        A = abs(A2) / 2.0
        if A < 1e-15:
            continue

        # Shape function gradient coefficients
        b = np.array([y1 - y2, y2 - y0, y0 - y1])
        c = np.array([x2 - x1, x0 - x2, x1 - x0])

        # Element stiffness: Ke = k/(4A) * (b*b^T + c*c^T)
        k = k_elems[e_idx]
        Ke = (k / (4.0 * A)) * (np.outer(b, b) + np.outer(c, c))

        local = [n0, n1, n2]
        for i in range(3):
            for j in range(3):
                rows.append(local[i])
                cols.append(local[j])
                vals.append(Ke[i, j])

    K = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    f = np.zeros(n)

    # Dirichlet boundary conditions
    dirichlet = {}
    for idx in mesh_data["slab_nodes"]:
        dirichlet[idx] = T_in
    for idx in mesh_data["ground_nodes"] | mesh_data["far_nodes"]:
        dirichlet[idx] = T_out
    for idx in mesh_data["deep_nodes"]:
        dirichlet[idx] = T_deep

    # Modify system: zero out Dirichlet rows, set diagonal to 1
    K_mod = K.tolil()
    for idx, val in dirichlet.items():
        K_mod[idx, :] = 0
        K_mod[idx, idx] = 1.0
        f[idx] = val

    K_mod = K_mod.tocsr()
    T = spsolve(K_mod, f)

    # Compute heat flux at slab surface via element gradients
    slab_nodes = mesh_data["slab_nodes"]
    Q_half = 0.0

    for e_idx in range(len(elements)):
        tri = elements[e_idx]
        on_surf = [int(ni) in slab_nodes for ni in tri]
        if sum(on_surf) < 2:
            continue

        n0, n1, n2 = tri
        x0, y0 = coords[n0]
        x1, y1 = coords[n1]
        x2, y2 = coords[n2]

        A2 = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(A2) < 1e-15:
            continue

        # dT/dy = sum(c_i * T_i) / (2*A_signed)
        c_coeffs = np.array([x2 - x1, x0 - x2, x1 - x0])
        T_local = np.array([T[n0], T[n1], T[n2]])
        dTdy = np.dot(c_coeffs, T_local) / A2

        k_e = k_elems[e_idx]
        q_down = -k_e * dTdy  # positive = heat flows into soil

        # Length of the surface edge
        surf_ns = [tri[i] for i, flag in enumerate(on_surf) if flag]
        edge_len = abs(coords[surf_ns[0], 0] - coords[surf_ns[1], 0])
        Q_half += q_down * edge_len

    return 2.0 * Q_half, T


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    slab = config["slab"]
    wall = config["foundation_wall"]
    mesh_dir = "/app/meshes"

    results_json = {}
    db_rows = []

    for case_name, case_params in config["cases"].items():
        print(f"Case '{case_name}':", flush=True)

        mesh_data = build_mesh(case_name, case_params, slab, wall, mesh_dir)
        print(f"  mesh: {mesh_data['n_nodes']} nodes, {mesh_data['n_elements']} elems",
              flush=True)

        Q, _ = solve_fem(mesh_data, case_params)
        Q_rounded = round(Q, 4)
        results_json[case_name] = Q_rounded
        db_rows.append((case_name, Q_rounded,
                         mesh_data["n_nodes"], mesh_data["n_elements"]))
        print(f"  Q = {Q:.4f} W/m", flush=True)

    # Write JSON results
    with open("/app/results.json", "w") as f:
        json.dump(results_json, f, indent=2)

    # Write SQLite results
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE results (
            case_name TEXT PRIMARY KEY,
            heat_loss_W_per_m REAL NOT NULL,
            num_nodes INTEGER NOT NULL,
            num_elements INTEGER NOT NULL
        )
    """)
    cur.executemany("INSERT INTO results VALUES (?, ?, ?, ?)", db_rows)
    conn.commit()
    conn.close()

    print(f"\nOutputs: /app/results.json, /app/results.db, /app/meshes/")


if __name__ == "__main__":
    main()
