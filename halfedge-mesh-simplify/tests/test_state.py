"""
Outcome-based tests for mesh decimation pipeline.

Tests invoke /app/simplify.py as a subprocess, verify output meshes,
check Makefile pipeline and validate.sh integration.

"""

import sys
sys.path.insert(0, "/app")

import subprocess
import os
import json
import numpy as np
import pytest
from halfedge import HalfedgeMesh
from obj_io import read_obj


def run_simplify(input_path, target, output_path):
    """Run the simplification tool and return the loaded output mesh."""
    result = subprocess.run(
        ["python3", "/app/simplify.py", input_path, str(target), output_path],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"simplify.py exited with code {result.returncode}\n"
        f"stderr: {result.stderr[:500]}\nstdout: {result.stdout[:500]}"
    )
    assert os.path.exists(output_path), f"Output {output_path} not created"
    return read_obj(output_path)


# -----------------------------------------------------------------------
# Octahedron  (8 faces -> target 4)
# -----------------------------------------------------------------------

class TestOctahedron:
    def test_validity(self):
        mesh = run_simplify("/app/meshes/octahedron.obj", 4, "/tmp/oct_v.obj")
        assert mesh.validate() == []

    def test_face_count(self):
        mesh = run_simplify("/app/meshes/octahedron.obj", 4, "/tmp/oct_fc.obj")
        assert 4 <= mesh.n_faces() <= 6

    def test_euler(self):
        mesh = run_simplify("/app/meshes/octahedron.obj", 4, "/tmp/oct_eu.obj")
        V, E, F = mesh.n_vertices(), mesh.n_edges(), mesh.n_faces()
        assert V - E + F == 2, f"chi = {V}-{E}+{F} = {V - E + F}"


# -----------------------------------------------------------------------
# Icosahedron  (20 faces -> target 8)
# -----------------------------------------------------------------------

class TestIcosahedron:
    def test_validity(self):
        mesh = run_simplify("/app/meshes/icosahedron.obj", 8, "/tmp/ico_v.obj")
        assert mesh.validate() == []

    def test_face_count(self):
        mesh = run_simplify("/app/meshes/icosahedron.obj", 8, "/tmp/ico_fc.obj")
        assert 4 <= mesh.n_faces() <= 12

    def test_euler(self):
        mesh = run_simplify("/app/meshes/icosahedron.obj", 8, "/tmp/ico_eu.obj")
        V, E, F = mesh.n_vertices(), mesh.n_edges(), mesh.n_faces()
        assert V - E + F == 2


# -----------------------------------------------------------------------
# Subdivided octahedron / sphere32  (32 faces -> target 8)
# -----------------------------------------------------------------------

class TestSphere32:
    def test_validity(self):
        mesh = run_simplify("/app/meshes/sphere32.obj", 8, "/tmp/sp_v.obj")
        assert mesh.validate() == []

    def test_face_count(self):
        mesh = run_simplify("/app/meshes/sphere32.obj", 8, "/tmp/sp_fc.obj")
        assert 4 <= mesh.n_faces() <= 12

    def test_euler(self):
        mesh = run_simplify("/app/meshes/sphere32.obj", 8, "/tmp/sp_eu.obj")
        V, E, F = mesh.n_vertices(), mesh.n_edges(), mesh.n_faces()
        assert V - E + F == 2


# -----------------------------------------------------------------------
# Tetrahedron  (4 faces -> target 2 -- already minimal)
# -----------------------------------------------------------------------

class TestTetrahedron:
    def test_stays_at_four(self):
        mesh = run_simplify("/app/meshes/tetrahedron.obj", 2, "/tmp/tet_s.obj")
        assert mesh.n_faces() == 4

    def test_validity(self):
        mesh = run_simplify("/app/meshes/tetrahedron.obj", 2, "/tmp/tet_v.obj")
        assert mesh.validate() == []


# -----------------------------------------------------------------------
# Geometric fidelity
# -----------------------------------------------------------------------

class TestGeometry:
    def test_icosahedron_vertex_bounds(self):
        mesh = run_simplify("/app/meshes/icosahedron.obj", 8, "/tmp/geo_ico.obj")
        for vid in mesh.vertices:
            d = np.linalg.norm(mesh.vertices[vid].position)
            assert d < 5.0, f"V{vid} distance {d} exceeds bound"
            assert d > 0.05, f"V{vid} collapsed to origin"

    def test_octahedron_vertex_bounds(self):
        mesh = run_simplify("/app/meshes/octahedron.obj", 4, "/tmp/geo_oct.obj")
        for vid in mesh.vertices:
            d = np.linalg.norm(mesh.vertices[vid].position)
            assert d < 3.0, f"V{vid} distance {d} exceeds bound"
            assert d > 0.05, f"V{vid} collapsed to origin"

    def test_sphere32_vertex_bounds(self):
        mesh = run_simplify("/app/meshes/sphere32.obj", 8, "/tmp/geo_sp.obj")
        for vid in mesh.vertices:
            d = np.linalg.norm(mesh.vertices[vid].position)
            assert d < 3.0, f"V{vid} distance {d} exceeds bound"
            assert d > 0.01, f"V{vid} collapsed to origin"


# -----------------------------------------------------------------------
# Tool integration -- mesh_stats.py interoperability
# -----------------------------------------------------------------------

class TestToolIntegration:
    def test_mesh_stats_valid_output(self):
        run_simplify("/app/meshes/octahedron.obj", 4, "/tmp/ti_oct.obj")
        result = subprocess.run(
            ["python3", "/app/mesh_stats.py", "/tmp/ti_oct.obj"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"mesh_stats.py failed: {result.stderr}"
        stats = json.loads(result.stdout)
        assert stats["is_valid"] is True
        assert 4 <= stats["face_count"] <= 6
        assert stats["euler_characteristic"] == 2


# -----------------------------------------------------------------------
# Pipeline tooling -- Makefile and validate.sh existence and jq usage
# -----------------------------------------------------------------------

class TestPipelineTools:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Missing /app/Makefile"

    def test_validate_exists(self):
        assert os.path.exists("/app/validate.sh"), "Missing /app/validate.sh"

    def test_makefile_uses_jq(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "jq" in content, "Makefile must use jq for JSON processing"

    def test_validate_uses_jq(self):
        with open("/app/validate.sh") as f:
            content = f.read()
        assert "jq" in content, "validate.sh must use jq for JSON processing"


# -----------------------------------------------------------------------
# Pipeline end-to-end -- make all + validate.sh
# -----------------------------------------------------------------------

class TestPipeline:
    def test_make_all(self):
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )

    def test_output_files_exist(self):
        subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=180,
        )
        for name in ["octahedron.obj", "icosahedron.obj", "sphere32.obj",
                      "tetrahedron.obj"]:
            path = f"/app/output/{name}"
            assert os.path.exists(path), f"Missing output: {path}"

    def test_validate_passes(self):
        subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=180,
        )
        result = subprocess.run(
            ["bash", "/app/validate.sh"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"validate.sh failed:\n{result.stdout[:500]}\n{result.stderr[:500]}"
        )

    def test_pipeline_output_validity(self):
        subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=180,
        )
        for name in ["octahedron.obj", "icosahedron.obj", "sphere32.obj",
                      "tetrahedron.obj"]:
            path = f"/app/output/{name}"
            if os.path.exists(path):
                mesh = read_obj(path)
                errors = mesh.validate()
                assert errors == [], f"{name} invalid: {errors[:3]}"
                V, E, F = mesh.n_vertices(), mesh.n_edges(), mesh.n_faces()
                assert V - E + F == 2, f"{name} chi={V - E + F}"
                assert mesh.n_faces() >= 4, f"{name} too few faces"
