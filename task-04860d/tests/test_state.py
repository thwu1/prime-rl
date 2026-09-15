
import json
import math
import os
import pytest

RESULT_PATH = "/app/result.json"


@pytest.fixture(scope="module")
def result():
    assert os.path.exists(RESULT_PATH), f"Result file not found at {RESULT_PATH}"
    with open(RESULT_PATH) as f:
        data = json.load(f)
    return data


class TestStructure:
    def test_all_scenes_present(self, result):
        for scene in ["sphere", "torus", "csg"]:
            assert scene in result, f"Missing scene '{scene}' in result"

    def test_required_fields(self, result):
        required = [
            "num_vertices", "num_faces", "euler_characteristic",
            "is_manifold", "genus", "surface_area", "centroid",
            "mean_edge_length", "edge_length_std", "smoothed_edge_length_std",
        ]
        for scene in ["sphere", "torus", "csg"]:
            for field in required:
                assert field in result[scene], f"Missing '{field}' in '{scene}'"

    def test_centroid_is_list_of_three(self, result):
        for scene in ["sphere", "torus", "csg"]:
            c = result[scene]["centroid"]
            assert isinstance(c, list) and len(c) == 3, (
                f"centroid in '{scene}' must be a list of 3 floats"
            )


class TestSphere:
    def test_euler_characteristic(self, result):
        assert result["sphere"]["euler_characteristic"] == 2

    def test_genus(self, result):
        assert result["sphere"]["genus"] == 0

    def test_is_manifold(self, result):
        assert result["sphere"]["is_manifold"] is True

    def test_mesh_size_vertices(self, result):
        assert result["sphere"]["num_vertices"] > 500

    def test_mesh_size_faces(self, result):
        assert result["sphere"]["num_faces"] > 1000

    def test_surface_area(self, result):
        expected = 4.0 * math.pi * 0.6 ** 2  # ~4.524
        actual = result["sphere"]["surface_area"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.15, (
            f"Sphere surface area {actual:.4f} deviates >{15}% from expected {expected:.4f}"
        )

    def test_centroid_near_origin(self, result):
        cx, cy, cz = result["sphere"]["centroid"]
        assert abs(cx) < 0.02 and abs(cy) < 0.02 and abs(cz) < 0.02, (
            f"Sphere centroid ({cx},{cy},{cz}) not near origin"
        )

    def test_smoothing_reduces_variance(self, result):
        s = result["sphere"]
        assert s["smoothed_edge_length_std"] < s["edge_length_std"], (
            "Laplacian smoothing should reduce edge length std for sphere"
        )

    def test_edge_length_positive(self, result):
        assert result["sphere"]["mean_edge_length"] > 0
        assert result["sphere"]["edge_length_std"] > 0


class TestTorus:
    def test_euler_characteristic(self, result):
        assert result["torus"]["euler_characteristic"] == 0

    def test_genus(self, result):
        assert result["torus"]["genus"] == 1

    def test_is_manifold(self, result):
        assert result["torus"]["is_manifold"] is True

    def test_mesh_size_vertices(self, result):
        assert result["torus"]["num_vertices"] > 500

    def test_mesh_size_faces(self, result):
        assert result["torus"]["num_faces"] > 1000

    def test_surface_area(self, result):
        expected = 4.0 * math.pi ** 2 * 0.5 * 0.2  # ~3.948
        actual = result["torus"]["surface_area"]
        rel_err = abs(actual - expected) / expected
        assert rel_err < 0.20, (
            f"Torus surface area {actual:.4f} deviates >{20}% from expected {expected:.4f}"
        )

    def test_centroid_near_origin(self, result):
        cx, cy, cz = result["torus"]["centroid"]
        assert abs(cx) < 0.05 and abs(cy) < 0.05 and abs(cz) < 0.05, (
            f"Torus centroid ({cx},{cy},{cz}) not near origin"
        )

    def test_smoothing_reduces_variance(self, result):
        t = result["torus"]
        assert t["smoothed_edge_length_std"] < t["edge_length_std"], (
            "Laplacian smoothing should reduce edge length std for torus"
        )

    def test_edge_length_positive(self, result):
        assert result["torus"]["mean_edge_length"] > 0
        assert result["torus"]["edge_length_std"] > 0


class TestCSG:
    def test_euler_characteristic(self, result):
        assert result["csg"]["euler_characteristic"] == 0

    def test_genus(self, result):
        assert result["csg"]["genus"] == 1

    def test_is_manifold(self, result):
        assert result["csg"]["is_manifold"] is True

    def test_mesh_size_vertices(self, result):
        assert result["csg"]["num_vertices"] > 500

    def test_mesh_size_faces(self, result):
        assert result["csg"]["num_faces"] > 1000

    def test_centroid_near_origin(self, result):
        cx, cy, cz = result["csg"]["centroid"]
        assert abs(cx) < 0.05 and abs(cy) < 0.05 and abs(cz) < 0.05, (
            f"CSG centroid ({cx},{cy},{cz}) not near origin"
        )

    def test_smoothing_reduces_variance(self, result):
        c = result["csg"]
        assert c["smoothed_edge_length_std"] < c["edge_length_std"], (
            "Laplacian smoothing should reduce edge length std for CSG"
        )

    def test_edge_length_positive(self, result):
        assert result["csg"]["mean_edge_length"] > 0
        assert result["csg"]["edge_length_std"] > 0

    def test_surface_area_positive(self, result):
        # CSG surface area should be substantial (sphere shell + cylinder interior)
        assert result["csg"]["surface_area"] > 3.0
