
import pytest
import os
import numpy as np

OUTPUT_PATH = "/app/rve.msh"
SCRIPT_PATH = "/app/mesh_rve.py"
MATRIX_NAME = "Matrix"
CENTER_NAME = "CenterInclusion"
CORNER_NAME = "CornerInclusion"
MIN_SICN = 0.05
MIN_ELEMENTS = 2000
MAX_ELEMENTS = 2_000_000

# Sphere definitions for size-grading distance computation: (cx, cy, cz, radius)
SPHERES = [
    (0.5, 0.5, 0.5, 0.2),
    (0.0, 0.0, 0.0, 0.25), (1.0, 0.0, 0.0, 0.25),
    (0.0, 1.0, 0.0, 0.25), (0.0, 0.0, 1.0, 0.25),
    (1.0, 1.0, 0.0, 0.25), (1.0, 0.0, 1.0, 0.25),
    (0.0, 1.0, 1.0, 0.25), (1.0, 1.0, 1.0, 0.25),
]


@pytest.fixture(scope="module")
def mesh_data():
    """Load the mesh and extract all data needed for verification."""
    import gmsh

    assert os.path.exists(OUTPUT_PATH), f"Mesh file {OUTPUT_PATH} not found"

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.open(OUTPUT_PATH)

    # --- Physical groups ---
    groups = {}
    for dim, tag in gmsh.model.getPhysicalGroups(3):
        name = gmsh.model.getPhysicalName(dim, tag)
        entities = list(gmsh.model.getEntitiesForPhysicalGroup(dim, tag))
        groups[name] = entities

    # --- All nodes ---
    node_tags, coords_flat, _ = gmsh.model.mesh.getNodes()
    coords = np.array(coords_flat).reshape(-1, 3)

    # Build fast coordinate lookup array indexed by node tag
    node_tags_int = node_tags.astype(int)
    max_tag = int(node_tags_int.max()) if len(node_tags_int) > 0 else 0
    node_coord_arr = np.zeros((max_tag + 1, 3))
    node_coord_arr[node_tags_int] = coords

    # --- 3D elements: types, centroids, edge lengths ---
    types_3d, tags_3d, node_tags_3d = gmsh.model.mesh.getElements(3)
    all_elem_tags = []
    elem_types_set = set()
    all_centroids = []
    all_max_edges = []

    for t_idx in range(len(types_3d)):
        elem_type = int(types_3d[t_idx])
        elem_types_set.add(elem_type)
        e_tags = tags_3d[t_idx]
        e_nodes = node_tags_3d[t_idx]
        _, _, _, n_per_elem, _, _ = gmsh.model.mesh.getElementProperties(elem_type)

        all_elem_tags.extend(e_tags.tolist())
        n = len(e_tags)

        if n > 0:
            nids = np.array(e_nodes, dtype=int).reshape(n, n_per_elem)
            pts = node_coord_arr[nids]  # (n, n_per_elem, 3)
            all_centroids.append(pts.mean(axis=1))

            max_edge = np.zeros(n)
            for a in range(n_per_elem):
                for b in range(a + 1, n_per_elem):
                    edge_len = np.linalg.norm(pts[:, a] - pts[:, b], axis=1)
                    max_edge = np.maximum(max_edge, edge_len)
            all_max_edges.append(max_edge)

    # --- SICN qualities ---
    qualities = []
    if all_elem_tags:
        qualities = list(gmsh.model.mesh.getElementQualities(all_elem_tags))

    # --- Conformal interface check: shared node IDs between groups ---
    incl_vols = groups.get(CENTER_NAME, []) + groups.get(CORNER_NAME, [])
    matrix_vols = groups.get(MATRIX_NAME, [])

    incl_elem_nodes = set()
    for v in incl_vols:
        _, _, nl = gmsh.model.mesh.getElements(3, v)
        for arr in nl:
            incl_elem_nodes.update(int(x) for x in arr)

    matrix_elem_nodes = set()
    for v in matrix_vols:
        _, _, nl = gmsh.model.mesh.getElements(3, v)
        for arr in nl:
            matrix_elem_nodes.update(int(x) for x in arr)

    shared_nodes = len(incl_elem_nodes & matrix_elem_nodes)

    gmsh.finalize()

    # --- Size grading: classify elements by distance to inclusion surfaces ---
    if all_centroids:
        elem_centroids = np.concatenate(all_centroids, axis=0)
        elem_max_edges = np.concatenate(all_max_edges)
    else:
        elem_centroids = np.zeros((0, 3))
        elem_max_edges = np.array([])

    near_sizes = np.array([])
    far_sizes = np.array([])
    if len(elem_centroids) > 0:
        min_surf_dist = np.full(len(elem_centroids), np.inf)
        for cx, cy, cz, r in SPHERES:
            center = np.array([cx, cy, cz])
            dists = np.abs(np.linalg.norm(elem_centroids - center, axis=1) - r)
            min_surf_dist = np.minimum(min_surf_dist, dists)

        near_mask = min_surf_dist < 0.05
        far_mask = min_surf_dist > 0.25
        if near_mask.any():
            near_sizes = elem_max_edges[near_mask]
        if far_mask.any():
            far_sizes = elem_max_edges[far_mask]

    return {
        "groups": groups,
        "coords": coords,
        "n_elements": len(all_elem_tags),
        "qualities": qualities,
        "min_quality": min(qualities) if qualities else 0.0,
        "element_types": elem_types_set,
        "shared_interface_nodes": shared_nodes,
        "near_interface_sizes": near_sizes,
        "far_interface_sizes": far_sizes,
    }


# ===========================================================================
# File existence
# ===========================================================================

def test_mesh_file_exists():
    assert os.path.exists(OUTPUT_PATH), f"Mesh file {OUTPUT_PATH} not found"


def test_script_exists():
    assert os.path.exists(SCRIPT_PATH), f"Script {SCRIPT_PATH} not found"


# ===========================================================================
# Physical groups
# ===========================================================================

def test_matrix_group(mesh_data):
    assert MATRIX_NAME in mesh_data["groups"], \
        f"Missing '{MATRIX_NAME}'. Found: {list(mesh_data['groups'].keys())}"
    assert len(mesh_data["groups"][MATRIX_NAME]) >= 1, \
        f"Matrix should have >= 1 volume entity"


def test_center_inclusion_group(mesh_data):
    groups = mesh_data["groups"]
    assert CENTER_NAME in groups, \
        f"Missing '{CENTER_NAME}'. Found: {list(groups.keys())}"
    assert len(groups[CENTER_NAME]) == 1, \
        f"{CENTER_NAME} should have exactly 1 volume, got {len(groups[CENTER_NAME])}"


def test_corner_inclusion_group(mesh_data):
    groups = mesh_data["groups"]
    assert CORNER_NAME in groups, \
        f"Missing '{CORNER_NAME}'. Found: {list(groups.keys())}"
    assert len(groups[CORNER_NAME]) == 8, \
        f"{CORNER_NAME} should have exactly 8 volumes, got {len(groups[CORNER_NAME])}"


# ===========================================================================
# Element count
# ===========================================================================

def test_element_count(mesh_data):
    n = mesh_data["n_elements"]
    assert n > MIN_ELEMENTS, f"Too few 3D elements: {n}"
    assert n < MAX_ELEMENTS, f"Too many 3D elements: {n}"


# ===========================================================================
# Element type — only linear tetrahedra
# ===========================================================================

def test_linear_tet_only(mesh_data):
    assert mesh_data["element_types"] == {4}, \
        f"Expected only linear tetrahedra (gmsh type 4), found types: {mesh_data['element_types']}"


# ===========================================================================
# Mesh quality — SICN
# ===========================================================================

def test_min_sicn(mesh_data):
    assert mesh_data["min_quality"] > MIN_SICN, \
        f"Min SICN = {mesh_data['min_quality']:.6f}, required > {MIN_SICN}"


# ===========================================================================
# Conformal interfaces — shared nodes between matrix and inclusion elements
# ===========================================================================

def test_conformal_interfaces(mesh_data):
    n = mesh_data["shared_interface_nodes"]
    assert n > 50, \
        f"Only {n} nodes shared between matrix and inclusion element sets. " \
        "Interfaces are not conformal — volumes must share boundary nodes."


# ===========================================================================
# Size grading — elements near interfaces smaller than bulk
# ===========================================================================

def test_size_grading(mesh_data):
    near = mesh_data["near_interface_sizes"]
    far = mesh_data["far_interface_sizes"]
    assert len(near) > 10, \
        f"Too few elements near interfaces ({len(near)}) to verify size grading"
    assert len(far) > 10, \
        f"Too few elements far from interfaces ({len(far)}) to verify size grading"
    avg_near = float(np.mean(near))
    avg_far = float(np.mean(far))
    assert avg_near < avg_far * 0.8, \
        f"Size grading not detected. Mean max-edge near interfaces: {avg_near:.4f}, " \
        f"far from interfaces: {avg_far:.4f}. Expected near < 0.8 * far."


# ===========================================================================
# Triple periodicity
# ===========================================================================

def _check_periodicity(coords, axis, label):
    """Verify nodes on opposite faces match after unit translation."""
    eps = 1e-4
    tol = 1e-3

    min_mask = coords[:, axis] < eps
    max_mask = coords[:, axis] > 1.0 - eps

    min_pts = coords[min_mask].copy()
    max_pts = coords[max_mask].copy()

    assert len(min_pts) > 20, \
        f"{label}: too few nodes on min face ({len(min_pts)})"
    assert len(max_pts) > 20, \
        f"{label}: too few nodes on max face ({len(max_pts)})"
    assert len(min_pts) == len(max_pts), \
        f"{label}: node count mismatch — min={len(min_pts)}, max={len(max_pts)}. " \
        "Periodic constraints not enforced."

    other = [i for i in range(3) if i != axis]
    min_2d = min_pts[:, other]
    max_2d = max_pts[:, other]

    min_order = np.lexsort((min_2d[:, 1], min_2d[:, 0]))
    max_order = np.lexsort((max_2d[:, 1], max_2d[:, 0]))

    diffs = np.abs(min_2d[min_order] - max_2d[max_order])
    max_diff = np.max(diffs)
    assert max_diff < tol, \
        f"{label}: max coordinate diff = {max_diff:.6f} (tol={tol})"


def test_periodicity_x(mesh_data):
    _check_periodicity(mesh_data["coords"], 0, "X-axis")


def test_periodicity_y(mesh_data):
    _check_periodicity(mesh_data["coords"], 1, "Y-axis")


def test_periodicity_z(mesh_data):
    _check_periodicity(mesh_data["coords"], 2, "Z-axis")
