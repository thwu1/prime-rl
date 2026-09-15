
import pytest
import numpy as np
import json
import os
import sys

sys.path.insert(0, '/app')


# === Chamfer Distance Tests ===

class TestChamferDistance:
    def test_identical_points(self):
        from cad_eval import chamfer_distance
        np.random.seed(99)
        points = np.random.rand(200, 3)
        cd = chamfer_distance(points, points)
        assert cd == pytest.approx(0.0, abs=1e-10)

    def test_known_single_point(self):
        """CD of (0,0,0) vs (1,0,0): each direction squared dist 1.0, total=2.0"""
        from cad_eval import chamfer_distance
        a = np.array([[0.0, 0.0, 0.0]])
        b = np.array([[1.0, 0.0, 0.0]])
        cd = chamfer_distance(a, b)
        assert cd == pytest.approx(2.0, abs=1e-6)

    def test_asymmetric(self):
        """A={(0,0,0),(3,0,0)}, B={(1,0,0)}.
        A->B: sq dists [1,4], mean=2.5
        B->A: sq dist [1], mean=1.0
        CD = 3.5"""
        from cad_eval import chamfer_distance
        a = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
        b = np.array([[1.0, 0.0, 0.0]])
        cd = chamfer_distance(a, b)
        assert cd == pytest.approx(3.5, abs=1e-6)

    def test_positive_for_different(self):
        from cad_eval import chamfer_distance
        a = np.zeros((50, 3))
        b = np.ones((50, 3))
        cd = chamfer_distance(a, b)
        assert cd > 0


# === F1 Score Tests ===

class TestF1Score:
    def test_identical_points(self):
        from cad_eval import f1_score_metric
        np.random.seed(42)
        points = np.random.rand(200, 3)
        f1 = f1_score_metric(points, points, threshold=0.02)
        assert f1 == pytest.approx(1.0, abs=1e-10)

    def test_distant_points(self):
        from cad_eval import f1_score_metric
        a = np.zeros((100, 3))
        b = np.ones((100, 3)) * 10.0
        f1 = f1_score_metric(a, b, threshold=0.02)
        assert f1 == pytest.approx(0.0, abs=1e-10)

    def test_threshold_boundary(self):
        """Points at distance 0.05 with threshold 0.02 must give F1=0.
        Distance 0.05 > threshold 0.02, so no matches."""
        from cad_eval import f1_score_metric
        a = np.array([[0.0, 0.0, 0.0]])
        b = np.array([[0.05, 0.0, 0.0]])
        f1 = f1_score_metric(a, b, threshold=0.02)
        assert f1 == pytest.approx(0.0, abs=1e-6)


# === Normalization Tests ===

class TestNormalization:
    def test_vertices_in_unit_cube(self):
        import trimesh
        from cad_eval import normalize_mesh
        box = trimesh.creation.box(extents=[4.0, 2.0, 6.0])
        box.apply_translation([10.0, 20.0, 30.0])
        normalized = normalize_mesh(box)
        assert normalized.vertices.min() >= -0.01
        assert normalized.vertices.max() <= 1.01

    def test_max_extent_spans_unit(self):
        """The largest dimension should span close to [0, 1]."""
        import trimesh
        from cad_eval import normalize_mesh
        box = trimesh.creation.box(extents=[2.0, 4.0, 8.0])
        normalized = normalize_mesh(box)
        extents = normalized.vertices.max(axis=0) - normalized.vertices.min(axis=0)
        assert max(extents) == pytest.approx(1.0, abs=0.01)

    def test_aspect_ratio_preserved(self):
        """A 2:1:1 box should remain 2:1:1 after normalization."""
        import trimesh
        from cad_eval import normalize_mesh
        box = trimesh.creation.box(extents=[4.0, 2.0, 2.0])
        normalized = normalize_mesh(box)
        extents = normalized.vertices.max(axis=0) - normalized.vertices.min(axis=0)
        sorted_ext = sorted(extents, reverse=True)
        assert sorted_ext[0] / sorted_ext[1] == pytest.approx(2.0, abs=0.05)


# === Surface Sampling Tests ===

class TestSurfaceSampling:
    def test_output_shape(self):
        import trimesh
        from cad_eval import uniform_surface_sample
        box = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
        points = uniform_surface_sample(box, 5000)
        assert points.shape == (5000, 3)

    def test_area_weighted(self):
        """Mesh with one tiny face and one huge face.
        Area-weighted sampling should place nearly all samples on the large face.
        Uniform face sampling would place ~50% on each."""
        import trimesh
        from cad_eval import uniform_surface_sample
        vertices = np.array([
            [0.0, 0.0, 0.0],
            [0.001, 0.0, 0.0],
            [0.0, 0.001, 0.0],
            [10.0, 0.0, 0.0],
            [0.0, 10.0, 0.0],
        ])
        faces = np.array([[0, 1, 2], [0, 3, 4]])
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        points = uniform_surface_sample(mesh, 10000)
        far_from_origin = np.max(np.abs(points), axis=1) > 0.01
        pct_on_large = np.mean(far_from_origin)
        assert pct_on_large > 0.9


# === Volumetric IoU Tests ===

class TestVolumetricIoU:
    def test_identical_meshes(self):
        import trimesh
        from cad_eval import volumetric_iou
        box = trimesh.creation.box(extents=[0.5, 0.5, 0.5])
        box.apply_translation([0.5, 0.5, 0.5])
        iou = volumetric_iou(box, box, resolution=0.05)
        assert iou > 0.9

    def test_no_overlap(self):
        import trimesh
        from cad_eval import volumetric_iou
        box_a = trimesh.creation.box(extents=[0.2, 0.2, 0.2])
        box_a.apply_translation([0.1, 0.1, 0.1])
        box_b = trimesh.creation.box(extents=[0.2, 0.2, 0.2])
        box_b.apply_translation([0.9, 0.9, 0.9])
        iou = volumetric_iou(box_a, box_b, resolution=0.05)
        assert iou < 0.01

    def test_contained_box_uses_full_bounds(self):
        """Small box inside large box.  Correct IoU ~ small_vol/large_vol.
        Using only mesh_a's bounds would incorrectly give IoU ~ 1.0."""
        import trimesh
        from cad_eval import volumetric_iou
        small = trimesh.creation.box(extents=[0.2, 0.2, 0.2])
        small.apply_translation([0.5, 0.5, 0.5])
        large = trimesh.creation.box(extents=[0.8, 0.8, 0.8])
        large.apply_translation([0.5, 0.5, 0.5])
        iou = volumetric_iou(small, large, resolution=0.03)
        assert iou < 0.1


# === Script Execution Tests ===

class TestExecution:
    def test_execute_valid_script(self):
        import tempfile
        from cad_eval import execute_script
        script = (
            'import cadquery as cq\n'
            'result = cq.Workplane("XY").box(1.0, 1.0, 1.0)\n'
            'cq.exporters.export(result, \'output.stl\')\n'
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            script_path = f.name
        output_stl = tempfile.mktemp(suffix='.stl')
        try:
            success = execute_script(script_path, output_stl)
            assert success
            assert os.path.exists(output_stl)
            assert os.path.getsize(output_stl) > 0
        finally:
            os.unlink(script_path)
            if os.path.exists(output_stl):
                os.unlink(output_stl)


# === Repair Tests ===

class TestRepair:
    def test_adds_missing_import(self):
        from cad_eval import repair_script
        script = 'result = cq.Workplane("XY").box(1, 1, 1)\ncq.exporters.export(result, "out.stl")\n'
        repaired = repair_script(script)
        assert 'import cadquery' in repaired

    def test_modifies_three_point_arc(self):
        from cad_eval import repair_script
        script = (
            'import cadquery as cq\n'
            'sketch_scale = 0.02\n'
            'result = (\n'
            '    cq.Workplane("XY")\n'
            '    .lineTo(0.0208 * sketch_scale, 0.0)\n'
            '    .threePointArc((0.0104 * sketch_scale, 0.0104 * sketch_scale), '
            '(0.0, 0.0208 * sketch_scale))\n'
            '    .close()\n'
            '    .extrude(0.5)\n'
            ')\n'
            'cq.exporters.export(result, "output.stl")\n'
        )
        repaired = repair_script(script)
        assert repaired != script


# === Pipeline Output Tests ===

class TestPipeline:
    @pytest.fixture(autouse=True)
    def load_results(self):
        results_path = '/app/results.json'
        if os.path.exists(results_path):
            with open(results_path) as f:
                self.output = json.load(f)
        else:
            pytest.skip("results.json not found — pipeline did not run")

    def test_output_has_results_key(self):
        assert 'results' in self.output

    def test_output_has_summary_key(self):
        assert 'summary' in self.output

    def test_results_length(self):
        assert len(self.output['results']) == 5

    def test_each_result_has_id(self):
        for r in self.output['results']:
            assert 'id' in r

    def test_summary_total_pairs(self):
        assert self.output['summary']['total_pairs'] == 5

    def test_identical_boxes_low_cd(self):
        """pair_001: identical boxes should have near-zero Chamfer Distance."""
        pair = next((r for r in self.output['results'] if r['id'] == 'pair_001'), None)
        assert pair is not None
        assert pair['reference_executed'] is True
        assert pair['candidate_executed'] is True
        assert pair['metrics'] is not None
        assert pair['metrics']['chamfer_distance'] < 0.001

    def test_identical_boxes_high_f1(self):
        pair = next((r for r in self.output['results'] if r['id'] == 'pair_001'), None)
        assert pair is not None
        assert pair['metrics']['f1_score'] > 0.99

    def test_different_boxes_positive_cd(self):
        """pair_002: different boxes should have non-zero Chamfer Distance."""
        pair = next((r for r in self.output['results'] if r['id'] == 'pair_002'), None)
        assert pair is not None
        assert pair['metrics'] is not None
        assert pair['metrics']['chamfer_distance'] > 0.0

    def test_identical_cylinders_low_cd(self):
        """pair_003: identical cylinders should have near-zero Chamfer Distance."""
        pair = next((r for r in self.output['results'] if r['id'] == 'pair_003'), None)
        assert pair is not None
        assert pair['reference_executed'] is True
        assert pair['candidate_executed'] is True
        assert pair['metrics'] is not None
        assert pair['metrics']['chamfer_distance'] < 0.001

    def test_broken_script_reference_executes(self):
        """pair_004: reference (box with hole) should execute successfully."""
        pair = next((r for r in self.output['results'] if r['id'] == 'pair_004'), None)
        assert pair is not None
        assert pair['reference_executed'] is True

    def test_summary_has_valid_pairs(self):
        assert 'valid_pairs' in self.output['summary']
        assert self.output['summary']['valid_pairs'] >= 3
