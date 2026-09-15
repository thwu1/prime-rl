
import json
import math
import os
import pytest
import numpy as np

RESULTS_PATH = "/app/output/results.json"
STEP_DIR = "/app/output/step"
MESH_DIR = "/app/output/mesh"

SURFACE_IDS = ["flat_plane", "dome", "nurbs_quarter_cyl", "freeform_bspline"]


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Output file {RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def vec_close(a, b, atol=1e-4):
    """Check two 3-vectors are close."""
    assert len(a) == 3 and len(b) == 3
    for i in range(3):
        assert abs(a[i] - b[i]) < atol, f"Component {i}: {a[i]} vs {b[i]}, diff={abs(a[i]-b[i])}"


def is_unit(v, tol=0.02):
    """Check vector is approximately unit length."""
    mag = math.sqrt(sum(x * x for x in v))
    assert abs(mag - 1.0) < tol, f"Normal not unit length: |n|={mag}"


# ==============================================================
# FLAT PLANE tests
# ==============================================================

class TestFlatPlane:
    """3x5 rectangle in the xy-plane. All curvatures zero, area=15."""

    def test_exists(self, results):
        assert "flat_plane" in results

    def test_points(self, results):
        pts = results["flat_plane"]["points"]
        assert len(pts) == 4
        vec_close(pts[0], [0.0, 0.0, 0.0])
        vec_close(pts[1], [1.5, 2.5, 0.0])
        vec_close(pts[2], [3.0, 5.0, 0.0])
        vec_close(pts[3], [0.75, 3.75, 0.0])

    def test_normals(self, results):
        normals = results["flat_plane"]["normals"]
        for n in normals:
            is_unit(n)
            assert abs(abs(n[2]) - 1.0) < 0.01, f"Plane normal z-component should be ±1, got {n[2]}"

    def test_gaussian_curvature(self, results):
        Ks = results["flat_plane"]["gaussian_curvature"]
        for K in Ks:
            assert abs(K) < 1e-4, f"Flat plane K should be 0, got {K}"

    def test_mean_curvature(self, results):
        Hs = results["flat_plane"]["mean_curvature"]
        for H in Hs:
            assert abs(H) < 1e-4, f"Flat plane H should be 0, got {H}"

    def test_area(self, results):
        area = results["flat_plane"]["area"]
        assert abs(area - 15.0) / 15.0 < 0.005, f"Flat plane area should be 15.0, got {area}"

    def test_projection(self, results):
        proj = results["flat_plane"]["projections"]
        assert len(proj) >= 1
        p = proj[0]
        vec_close(p["point"], [1.5, 2.5, 0.0], atol=0.01)
        assert abs(p["distance"] - 0.1) < 0.01


# ==============================================================
# DOME tests (biquadratic Bezier with raised center)
# ==============================================================

class TestDome:
    def test_exists(self, results):
        assert "dome" in results

    def test_point_center(self, results):
        pts = results["dome"]["points"]
        vec_close(pts[0], [1.0, 1.0, 0.5])

    def test_point_corner(self, results):
        pts = results["dome"]["points"]
        vec_close(pts[1], [0.0, 0.0, 0.0])
        vec_close(pts[2], [2.0, 0.0, 0.0])

    def test_point_quarter(self, results):
        pts = results["dome"]["points"]
        vec_close(pts[3], [0.5, 1.0, 0.375])

    def test_normal_center(self, results):
        n = results["dome"]["normals"][0]
        is_unit(n)
        assert abs(n[2]) > 0.99, f"Dome center normal z should be ~1, got {n[2]}"

    def test_gaussian_curvature_center(self, results):
        K = results["dome"]["gaussian_curvature"][0]
        assert abs(K - 1.0) < 0.1, f"Dome center K should be ~1.0, got {K}"

    def test_mean_curvature_center(self, results):
        H = results["dome"]["mean_curvature"][0]
        assert abs(abs(H) - 1.0) < 0.1, f"Dome center |H| should be ~1.0, got {H}"

    def test_gaussian_curvature_corner(self, results):
        K = results["dome"]["gaussian_curvature"][1]
        assert abs(K - (-4.0)) < 0.5, f"Dome corner K should be ~-4.0, got {K}"

    def test_curvature_quarter(self, results):
        K = results["dome"]["gaussian_curvature"][3]
        assert abs(K - 0.48) < 0.1, f"Dome (0.25,0.5) K should be ~0.48, got {K}"

    def test_area(self, results):
        area = results["dome"]["area"]
        assert abs(area - 4.6425) / 4.6425 < 0.01, f"Dome area should be ~4.6425, got {area}"

    def test_projection(self, results):
        proj = results["dome"]["projections"]
        assert len(proj) >= 1
        p = proj[0]
        assert abs(p["distance"] - 0.3) < 0.05, f"Dome projection dist should be ~0.3, got {p['distance']}"


# ==============================================================
# NURBS QUARTER CYLINDER tests
# ==============================================================

class TestNurbsCylinder:
    def test_exists(self, results):
        assert "nurbs_quarter_cyl" in results

    def test_point_start(self, results):
        pts = results["nurbs_quarter_cyl"]["points"]
        vec_close(pts[0], [1.0, 0.0, 0.0])

    def test_point_mid(self, results):
        pts = results["nurbs_quarter_cyl"]["points"]
        s2 = 1.0 / math.sqrt(2.0)
        vec_close(pts[1], [s2, s2, 1.5])

    def test_point_end(self, results):
        pts = results["nurbs_quarter_cyl"]["points"]
        vec_close(pts[2], [0.0, 1.0, 0.0])

    def test_normal_mid(self, results):
        n = results["nurbs_quarter_cyl"]["normals"][1]
        is_unit(n)
        s2 = 1.0 / math.sqrt(2.0)
        assert abs(abs(n[0]) - s2) < 0.02
        assert abs(abs(n[1]) - s2) < 0.02
        assert abs(n[2]) < 0.02

    def test_gaussian_curvature_mid(self, results):
        K = results["nurbs_quarter_cyl"]["gaussian_curvature"][1]
        assert abs(K) < 0.05, f"Cylinder K should be ~0, got {K}"

    def test_mean_curvature_mid(self, results):
        H = results["nurbs_quarter_cyl"]["mean_curvature"][1]
        assert abs(abs(H) - 0.5) < 0.1, f"Cylinder |H| should be ~0.5, got {H}"

    def test_area(self, results):
        expected = 3.0 * math.pi / 2.0
        area = results["nurbs_quarter_cyl"]["area"]
        assert abs(area - expected) / expected < 0.01, f"Cylinder area should be ~{expected:.4f}, got {area}"

    def test_projection(self, results):
        proj = results["nurbs_quarter_cyl"]["projections"]
        assert len(proj) >= 1
        p = proj[0]
        assert abs(p["distance"] - 0.1314) < 0.02, f"Cylinder projection dist should be ~0.131, got {p['distance']}"


# ==============================================================
# FREEFORM B-SPLINE tests
# ==============================================================

class TestFreeformBspline:
    def test_exists(self, results):
        assert "freeform_bspline" in results

    def test_num_points(self, results):
        pts = results["freeform_bspline"]["points"]
        assert len(pts) == 5

    def test_corner_origin(self, results):
        pts = results["freeform_bspline"]["points"]
        vec_close(pts[0], [0.0, 0.0, 0.0])

    def test_corner_end(self, results):
        pts = results["freeform_bspline"]["points"]
        vec_close(pts[4], [4.0, 3.0, -0.1])

    def test_interior_point_1(self, results):
        pts = results["freeform_bspline"]["points"]
        vec_close(pts[1], [1.1875, 1.5, 0.7223], atol=0.01)

    def test_interior_point_2(self, results):
        pts = results["freeform_bspline"]["points"]
        vec_close(pts[2], [2.0, 1.5, 0.7156], atol=0.01)

    def test_interior_point_3(self, results):
        pts = results["freeform_bspline"]["points"]
        vec_close(pts[3], [2.8125, 0.75, 0.2533], atol=0.01)

    def test_normals_unit(self, results):
        normals = results["freeform_bspline"]["normals"]
        for n in normals:
            is_unit(n)

    def test_area(self, results):
        area = results["freeform_bspline"]["area"]
        assert abs(area - 13.266) / 13.266 < 0.01, f"Freeform area should be ~13.266, got {area}"

    def test_curvature_signs(self, results):
        Ks = results["freeform_bspline"]["gaussian_curvature"]
        Hs = results["freeform_bspline"]["mean_curvature"]
        for K in Ks:
            assert abs(K) < 10.0, f"Freeform K seems unreasonable: {K}"
        for H in Hs:
            assert abs(H) < 10.0, f"Freeform H seems unreasonable: {H}"

    def test_interior_curvatures(self, results):
        Ks = results["freeform_bspline"]["gaussian_curvature"]
        assert abs(Ks[1] - 0.202) < 0.15, f"Freeform K at (0.25,0.5) should be ~0.2, got {Ks[1]}"
        assert abs(Ks[2] - 0.201) < 0.15, f"Freeform K at (0.5,0.5) should be ~0.2, got {Ks[2]}"

    def test_projection(self, results):
        proj = results["freeform_bspline"]["projections"]
        assert len(proj) >= 1
        p = proj[0]
        assert p["distance"] < 0.15, f"Freeform projection dist should be small, got {p['distance']}"
        assert 0.3 < p["u"] < 0.7, f"Projected u should be ~0.5, got {p['u']}"
        assert 0.3 < p["v"] < 0.7, f"Projected v should be ~0.5, got {p['v']}"


# ==============================================================
# Cross-surface structural tests
# ==============================================================

class TestStructure:
    def test_all_surfaces_present(self, results):
        for sid in SURFACE_IDS:
            assert sid in results, f"Missing surface {sid}"

    def test_required_keys(self, results):
        required = ["points", "normals", "gaussian_curvature", "mean_curvature", "area", "projections"]
        for sid in results:
            for key in required:
                assert key in results[sid], f"Surface {sid} missing key {key}"

    def test_areas_positive(self, results):
        for sid in results:
            assert results[sid]["area"] > 0, f"Surface {sid} area should be positive"

    def test_projection_distances_positive(self, results):
        for sid in results:
            for p in results[sid]["projections"]:
                assert p["distance"] >= 0, f"Projection distance should be non-negative"


# ==============================================================
# STEP file export tests
# ==============================================================

class TestStepExport:
    """Verify STEP files are valid ISO 10303-21."""

    def test_step_files_exist(self):
        for sid in SURFACE_IDS:
            path = os.path.join(STEP_DIR, f"{sid}.step")
            assert os.path.exists(path), f"STEP file missing: {path}"
            assert os.path.getsize(path) > 100, f"STEP file too small: {path}"

    def test_step_iso_header(self):
        for sid in SURFACE_IDS:
            path = os.path.join(STEP_DIR, f"{sid}.step")
            with open(path, "r", errors="replace") as f:
                content = f.read()
            assert "ISO-10303-21" in content, f"STEP file {sid} missing ISO-10303-21 header"

    def test_step_has_data_section(self):
        for sid in SURFACE_IDS:
            path = os.path.join(STEP_DIR, f"{sid}.step")
            with open(path, "r", errors="replace") as f:
                content = f.read().upper()
            assert "DATA" in content, f"STEP file {sid} missing DATA section"
            assert "ENDSEC" in content, f"STEP file {sid} missing ENDSEC"

    def test_step_has_geometry_entities(self):
        for sid in SURFACE_IDS:
            path = os.path.join(STEP_DIR, f"{sid}.step")
            with open(path, "r", errors="replace") as f:
                content = f.read().upper()
            has_surface = (
                "B_SPLINE_SURFACE" in content
                or "BOUNDED_SURFACE" in content
                or "SURFACE" in content
            )
            assert has_surface, f"STEP file {sid} missing surface geometry entity"


# ==============================================================
# Mesh file tests
# ==============================================================

class TestMeshFiles:
    """Verify mesh files exist and meet quality requirements."""

    def test_mesh_files_exist(self):
        for sid in SURFACE_IDS:
            path = os.path.join(MESH_DIR, f"{sid}.msh")
            assert os.path.exists(path), f"Mesh file missing: {path}"
            assert os.path.getsize(path) > 100, f"Mesh file too small: {path}"

    def test_mesh_readable(self):
        import meshio
        for sid in SURFACE_IDS:
            path = os.path.join(MESH_DIR, f"{sid}.msh")
            mesh = meshio.read(path)
            assert mesh.points is not None, f"Mesh {sid} has no points"
            assert len(mesh.points) > 0, f"Mesh {sid} has 0 points"

    def test_mesh_triangle_count(self):
        import meshio
        for sid in SURFACE_IDS:
            path = os.path.join(MESH_DIR, f"{sid}.msh")
            mesh = meshio.read(path)
            tri_count = 0
            for cell_block in mesh.cells:
                if cell_block.type == "triangle":
                    tri_count += len(cell_block.data)
            assert tri_count >= 200, (
                f"Mesh {sid} has {tri_count} triangles, need at least 200"
            )

    def test_mesh_aspect_ratio(self):
        import meshio
        for sid in SURFACE_IDS:
            path = os.path.join(MESH_DIR, f"{sid}.msh")
            mesh = meshio.read(path)
            worst_ar = 0.0
            for cell_block in mesh.cells:
                if cell_block.type == "triangle":
                    for tri in cell_block.data:
                        p1 = mesh.points[tri[0]]
                        p2 = mesh.points[tri[1]]
                        p3 = mesh.points[tri[2]]
                        e1 = np.linalg.norm(p2 - p1)
                        e2 = np.linalg.norm(p3 - p2)
                        e3 = np.linalg.norm(p1 - p3)
                        min_e = min(e1, e2, e3)
                        max_e = max(e1, e2, e3)
                        ar = max_e / min_e if min_e > 1e-12 else float("inf")
                        if ar > worst_ar:
                            worst_ar = ar
            assert worst_ar < 10.0, (
                f"Mesh {sid} worst aspect ratio {worst_ar:.2f} exceeds 10.0"
            )

    def test_mesh_spatial_bounds(self):
        """Verify mesh nodes are within plausible bounds for each surface."""
        import meshio
        bounds = {
            "flat_plane": {"x": (-0.5, 3.5), "y": (-0.5, 5.5), "z": (-0.5, 0.5)},
            "dome": {"x": (-0.5, 2.5), "y": (-0.5, 2.5), "z": (-0.5, 2.5)},
            "nurbs_quarter_cyl": {"x": (-0.5, 1.5), "y": (-0.5, 1.5), "z": (-0.5, 3.5)},
            "freeform_bspline": {"x": (-0.5, 4.5), "y": (-0.5, 3.5), "z": (-2.5, 3.5)},
        }
        for sid in SURFACE_IDS:
            path = os.path.join(MESH_DIR, f"{sid}.msh")
            mesh = meshio.read(path)
            pts = mesh.points
            b = bounds[sid]
            assert pts[:, 0].min() >= b["x"][0], f"Mesh {sid} x min out of bounds"
            assert pts[:, 0].max() <= b["x"][1], f"Mesh {sid} x max out of bounds"
            assert pts[:, 1].min() >= b["y"][0], f"Mesh {sid} y min out of bounds"
            assert pts[:, 1].max() <= b["y"][1], f"Mesh {sid} y max out of bounds"
            assert pts[:, 2].min() >= b["z"][0], f"Mesh {sid} z min out of bounds"
            assert pts[:, 2].max() <= b["z"][1], f"Mesh {sid} z max out of bounds"
