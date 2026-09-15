
"""Tests for the mesh validation pipeline."""

import json
import os
import subprocess

import numpy as np
import pytest
import trimesh
import yaml

TOOL_PATH = "/app/mesh_validator.py"


def _create_config(tmpdir, **overrides):
    """Create a config YAML with defaults and optional overrides."""
    config = {
        "expected_components": 1,
        "bbox_tolerance_mm": 1.0,
        "volume_threshold_percent": 2.0,
        "chamfer_threshold_mm": 1.0,
        "hausdorff_threshold_mm": 1.0,
    }
    config.update(overrides)
    path = os.path.join(tmpdir, "config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


def _save_stl(mesh, path):
    """Export a trimesh mesh to STL."""
    mesh.export(path, file_type="stl")


def _run_tool(gen_path, ref_path, config_path, timeout=120):
    """Run mesh_validator.py and return parsed JSON output."""
    result = subprocess.run(
        ["python3", TOOL_PATH, gen_path, ref_path, config_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"mesh_validator.py failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout)


class TestIdenticalMeshes:
    """Identical meshes should pass all checks with near-zero distances."""

    def test_all_checks_pass(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(box, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["watertight"] is True
        assert result["checks"]["component_count"] is True
        assert result["checks"]["bounding_box"] is True
        assert result["checks"]["volume"] is True
        assert result["all_passed"] is True

    def test_small_chamfer(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(box, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["metrics"]["chamfer_distance"] is not None
        assert result["metrics"]["chamfer_distance"] < 0.5
        assert result["metrics"]["hausdorff_95p"] is not None
        assert result["metrics"]["hausdorff_95p"] < 1.0


class TestAlignment:
    """Registration should correctly align translated meshes."""

    def test_translated_mesh_aligned(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        translated = box.copy()
        translated.apply_translation([100, 100, 100])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(translated, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["metrics"]["chamfer_distance"] is not None
        assert result["metrics"]["chamfer_distance"] < 0.5, (
            f"Chamfer {result['metrics']['chamfer_distance']:.3f} too large "
            f"for translated identical boxes"
        )
        assert result["checks"]["bounding_box"] is True


class TestWatertightDetection:
    """Non-manifold meshes should be detected as non-watertight."""

    def test_non_manifold_detected(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        faces = box.faces[:-4]
        broken = trimesh.Trimesh(vertices=box.vertices, faces=faces)
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(broken, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["watertight"] is False
        assert result["all_passed"] is False


class TestWatertightCleaning:
    """Meshes that are geometrically watertight but have duplicate triangles
    should pass the watertight check after proper cleaning."""

    def test_duplicate_triangles_still_watertight(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        dup_faces = np.vstack([box.faces, box.faces[:2]])
        dup_mesh = trimesh.Trimesh(
            vertices=box.vertices, faces=dup_faces, process=False
        )
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(dup_mesh, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["watertight"] is True, (
            "Mesh with duplicate triangles should be watertight after cleaning"
        )


class TestVolumeComparison:
    """Volume comparison should be correct and handle edge cases."""

    def test_volume_mismatch_detected(self, tmp_path):
        gen = trimesh.creation.box(extents=[10, 10, 15])
        ref = trimesh.creation.box(extents=[10, 10, 10])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(gen, gen_p)
        _save_stl(ref, ref_p)
        cfg = _create_config(str(tmp_path), volume_threshold_percent=2.0)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["volume"] is False
        ratio = result["metrics"]["volume_ratio"]
        assert ratio is not None
        assert 1.45 < ratio < 1.55, f"Expected ratio ~1.5, got {ratio}"

    def test_volume_within_threshold_passes(self, tmp_path):
        gen = trimesh.creation.box(extents=[10, 10, 10.1])
        ref = trimesh.creation.box(extents=[10, 10, 10])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(gen, gen_p)
        _save_stl(ref, ref_p)
        cfg = _create_config(str(tmp_path), volume_threshold_percent=2.0)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["volume"] is True

    def test_non_watertight_volume_must_fail(self, tmp_path):
        """Volume check must fail for non-watertight meshes even when the
        computed volume happens to be within threshold."""
        box = trimesh.creation.box(extents=[20, 20, 20])
        # Remove 1 triangle: computed volume is ~92% of true value
        faces = box.faces[:-1]
        broken = trimesh.Trimesh(
            vertices=box.vertices, faces=faces, process=False
        )
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(broken, gen_p)
        _save_stl(box, ref_p)
        # 15% threshold: garbage volume within range, but mesh is non-watertight
        cfg = _create_config(str(tmp_path), volume_threshold_percent=15.0)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["volume"] is False, (
            "Volume check should fail for non-watertight meshes"
        )


class TestComponentCount:
    """Component counting should be accurate."""

    def test_multiple_components_fails(self, tmp_path):
        box1 = trimesh.creation.box(extents=[10, 10, 10])
        box2 = trimesh.creation.box(extents=[10, 10, 10])
        box2.apply_translation([50, 0, 0])
        combined = trimesh.util.concatenate([box1, box2])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(combined, gen_p)
        _save_stl(box1, ref_p)
        cfg = _create_config(str(tmp_path), expected_components=1)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["component_count"] is False

    def test_expected_two_components_passes(self, tmp_path):
        box1 = trimesh.creation.box(extents=[10, 10, 10])
        box2 = trimesh.creation.box(extents=[10, 10, 10])
        box2.apply_translation([50, 0, 0])
        combined = trimesh.util.concatenate([box1, box2])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(combined, gen_p)
        _save_stl(box1, ref_p)
        cfg = _create_config(str(tmp_path), expected_components=2)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["component_count"] is True


class TestChamferBidirectional:
    """Chamfer distance must be bidirectional (symmetric for swapped inputs)."""

    def test_chamfer_approximately_symmetric(self, tmp_path):
        """Chamfer distance should be approximately the same when
        generated and reference meshes are swapped."""
        elongated = trimesh.creation.box(extents=[40, 5, 5])
        cube = trimesh.creation.box(extents=[10, 10, 10])

        gen_p1 = str(tmp_path / "gen1.stl")
        ref_p1 = str(tmp_path / "ref1.stl")
        _save_stl(elongated, gen_p1)
        _save_stl(cube, ref_p1)
        cfg = _create_config(
            str(tmp_path),
            chamfer_threshold_mm=50.0,
            hausdorff_threshold_mm=50.0,
        )

        result1 = _run_tool(gen_p1, ref_p1, cfg)

        gen_p2 = str(tmp_path / "gen2.stl")
        ref_p2 = str(tmp_path / "ref2.stl")
        _save_stl(cube, gen_p2)
        _save_stl(elongated, ref_p2)

        result2 = _run_tool(gen_p2, ref_p2, cfg)

        cd1 = result1["metrics"]["chamfer_distance"]
        cd2 = result2["metrics"]["chamfer_distance"]
        assert cd1 is not None and cd2 is not None
        assert abs(cd1 - cd2) < 3.0, (
            f"Chamfer not symmetric: {cd1:.3f} vs {cd2:.3f} "
            f"(diff={abs(cd1 - cd2):.3f}). "
            f"Likely unidirectional computation."
        )


class TestBoundingBox:
    """Bounding box comparison should detect dimension mismatches."""

    def test_bbox_mismatch_detected(self, tmp_path):
        gen = trimesh.creation.box(extents=[25, 20, 20])
        ref = trimesh.creation.box(extents=[20, 20, 20])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(gen, gen_p)
        _save_stl(ref, ref_p)
        cfg = _create_config(str(tmp_path), bbox_tolerance_mm=1.0)

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["bounding_box"] is False


class TestDifferentShapes:
    """Very different shapes should produce failures."""

    def test_box_vs_sphere_fails(self, tmp_path):
        sphere = trimesh.creation.icosphere(subdivisions=3, radius=10)
        box = trimesh.creation.box(extents=[20, 20, 20])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(sphere, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert result["checks"]["volume"] is False
        assert result["all_passed"] is False


class TestJsonOutputFormat:
    """Output JSON must contain all required fields."""

    def test_all_fields_present(self, tmp_path):
        box = trimesh.creation.box(extents=[20, 20, 20])
        gen_p = str(tmp_path / "gen.stl")
        ref_p = str(tmp_path / "ref.stl")
        _save_stl(box, gen_p)
        _save_stl(box, ref_p)
        cfg = _create_config(str(tmp_path))

        result = _run_tool(gen_p, ref_p, cfg)

        assert "checks" in result
        assert "metrics" in result
        assert "all_passed" in result

        for key in [
            "watertight", "component_count", "bounding_box",
            "volume", "chamfer", "hausdorff",
        ]:
            assert key in result["checks"], f"Missing check: {key}"
            assert isinstance(result["checks"][key], bool)

        for key in [
            "chamfer_distance", "hausdorff_95p", "hausdorff_99p",
            "icp_fitness", "volume_ratio",
            "generated_volume", "reference_volume",
        ]:
            assert key in result["metrics"], f"Missing metric: {key}"

        assert isinstance(result["all_passed"], bool)
