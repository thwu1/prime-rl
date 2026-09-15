"""
Tests for the Conway polyhedron operator pipeline.

Verifies topological invariants, mesh quality, OBJ export structure,
material grouping, and rendered image properties for all four target polyhedra.

"""
import json
import math
import os
import pytest


# Expected topological invariants for each target polyhedron
EXPECTED = {
    'dodecahedron': {
        'V': 20, 'E': 30, 'F': 12,
        'census': {'5': 12},
    },
    'icosidodecahedron': {
        'V': 30, 'E': 60, 'F': 32,
        'census': {'3': 20, '5': 12},
    },
    'truncated_icosahedron': {
        'V': 60, 'E': 90, 'F': 32,
        'census': {'5': 12, '6': 20},
    },
    'pentakis_dodecahedron': {
        'V': 32, 'E': 90, 'F': 60,
        'census': {'3': 60},
    },
}

POLYHEDRON_NAMES = list(EXPECTED.keys())


@pytest.fixture(scope="module")
def analysis():
    """Load the analysis JSON produced by the pipeline."""
    path = '/app/output/analysis.json'
    assert os.path.exists(path), f"analysis.json not found at {path}"
    with open(path) as f:
        return json.load(f)


def parse_obj(filepath):
    """Parse an OBJ file and return vertex lines, face lines, and material groups."""
    assert os.path.exists(filepath), f"OBJ file not found: {filepath}"
    with open(filepath) as f:
        lines = f.readlines()
    vertices = [l for l in lines if l.startswith('v ')]
    face_lines = [l for l in lines if l.startswith('f ')]

    # Parse face vertex counts
    faces = []
    for line in face_lines:
        parts = line.strip().split()
        num_verts = len(parts) - 1  # first part is 'f'
        faces.append(num_verts)

    # Parse material groups
    current_mat = None
    mat_faces = {}
    for line in lines:
        s = line.strip()
        if s.startswith('usemtl '):
            current_mat = s.split(' ', 1)[1]
            if current_mat not in mat_faces:
                mat_faces[current_mat] = []
        elif s.startswith('f ') and current_mat is not None:
            parts = s.split()
            mat_faces[current_mat].append(len(parts) - 1)

    return {
        'vertex_count': len(vertices),
        'face_count': len(face_lines),
        'face_sizes': faces,
        'material_groups': mat_faces,
    }


# ──────────────────────────────────────────────
# Analysis JSON existence and structure
# ──────────────────────────────────────────────

class TestAnalysisStructure:
    """Verify analysis.json exists and has all required entries."""

    def test_has_all_polyhedra(self, analysis):
        for name in POLYHEDRON_NAMES:
            assert name in analysis, f"Missing entry for '{name}' in analysis.json"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_has_required_fields(self, analysis, name):
        entry = analysis[name]
        required = [
            'vertex_count', 'edge_count', 'face_count',
            'euler_characteristic', 'is_manifold', 'face_type_census',
            'surface_area', 'volume', 'edge_length_std_dev',
            'max_face_planarity_error',
        ]
        for field in required:
            assert field in entry, f"{name}: missing field '{field}'"


# ──────────────────────────────────────────────
# Topological invariants from analysis.json
# ──────────────────────────────────────────────

class TestTopology:
    """Verify exact topological invariants for each polyhedron."""

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_vertex_count(self, analysis, name):
        got = analysis[name]['vertex_count']
        want = EXPECTED[name]['V']
        assert got == want, f"{name}: vertex_count {got} != {want}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_edge_count(self, analysis, name):
        got = analysis[name]['edge_count']
        want = EXPECTED[name]['E']
        assert got == want, f"{name}: edge_count {got} != {want}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_face_count(self, analysis, name):
        got = analysis[name]['face_count']
        want = EXPECTED[name]['F']
        assert got == want, f"{name}: face_count {got} != {want}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_euler_characteristic(self, analysis, name):
        euler = analysis[name]['euler_characteristic']
        assert euler == 2, f"{name}: Euler characteristic {euler} != 2"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_face_type_census(self, analysis, name):
        got = analysis[name]['face_type_census']
        want = EXPECTED[name]['census']
        # Normalize keys to strings for comparison
        got_norm = {str(k): v for k, v in got.items()}
        want_norm = {str(k): v for k, v in want.items()}
        assert got_norm == want_norm, \
            f"{name}: face_type_census {got_norm} != {want_norm}"


# ──────────────────────────────────────────────
# Mesh quality from analysis.json
# ──────────────────────────────────────────────

class TestMeshQuality:
    """Verify mesh quality metrics."""

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_manifold(self, analysis, name):
        assert analysis[name]['is_manifold'] is True, \
            f"{name}: mesh is not manifold"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_surface_area_positive(self, analysis, name):
        sa = analysis[name]['surface_area']
        assert isinstance(sa, (int, float)), f"{name}: surface_area not numeric"
        assert sa > 0, f"{name}: surface_area {sa} not positive"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_volume_positive(self, analysis, name):
        vol = analysis[name]['volume']
        assert isinstance(vol, (int, float)), f"{name}: volume not numeric"
        assert vol > 0, f"{name}: volume {vol} not positive"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_edge_length_std_dev_finite(self, analysis, name):
        std = analysis[name]['edge_length_std_dev']
        assert isinstance(std, (int, float)), f"{name}: edge_length_std_dev not numeric"
        assert math.isfinite(std), f"{name}: edge_length_std_dev not finite"
        assert std >= 0, f"{name}: edge_length_std_dev {std} is negative"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_planarity_error_finite(self, analysis, name):
        err = analysis[name]['max_face_planarity_error']
        assert isinstance(err, (int, float)), f"{name}: max_face_planarity_error not numeric"
        assert math.isfinite(err), f"{name}: max_face_planarity_error not finite"
        assert err >= 0, f"{name}: max_face_planarity_error {err} is negative"


# ──────────────────────────────────────────────
# OBJ file verification
# ──────────────────────────────────────────────

class TestOBJExport:
    """Verify OBJ files preserve correct mesh topology and material grouping."""

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_obj_exists(self, name):
        path = f'/app/output/{name}.obj'
        assert os.path.exists(path), f"OBJ not found: {path}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_obj_vertex_count(self, name):
        obj = parse_obj(f'/app/output/{name}.obj')
        want = EXPECTED[name]['V']
        assert obj['vertex_count'] == want, \
            f"{name}.obj: {obj['vertex_count']} vertices, expected {want}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_obj_face_count(self, name):
        obj = parse_obj(f'/app/output/{name}.obj')
        want = EXPECTED[name]['F']
        assert obj['face_count'] == want, \
            f"{name}.obj: {obj['face_count']} faces (no triangulation), expected {want}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_obj_face_types(self, name):
        obj = parse_obj(f'/app/output/{name}.obj')
        census = {}
        for n in obj['face_sizes']:
            census[str(n)] = census.get(str(n), 0) + 1
        want = EXPECTED[name]['census']
        want_norm = {str(k): v for k, v in want.items()}
        assert census == want_norm, \
            f"{name}.obj: face type census {census} != {want_norm}"

    @pytest.mark.parametrize("name", POLYHEDRON_NAMES)
    def test_obj_has_material_groups(self, name):
        obj = parse_obj(f'/app/output/{name}.obj')
        census = EXPECTED[name]['census']
        num_face_types = len(census)
        groups = {m: f for m, f in obj['material_groups'].items() if f}
        assert len(groups) >= num_face_types, \
            f"{name}.obj: expected >= {num_face_types} material groups, found {len(groups)}"


# ──────────────────────────────────────────────
# Rendered image
# ──────────────────────────────────────────────

class TestRender:
    """Verify the rendered scene image."""

    def test_render_exists(self):
        assert os.path.exists('/app/output/scene_render.png'), \
            "Rendered image not found at /app/output/scene_render.png"

    def test_render_dimensions(self):
        from PIL import Image
        img = Image.open('/app/output/scene_render.png')
        assert img.size == (1280, 720), \
            f"Render must be 1280x720, got {img.size}"
