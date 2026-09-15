"""
Tests for the medical image registration pipeline.

Validates transform correctness, pipeline configuration, and the pipeline validator.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, '/app')
from transforms import (
    extract_spacing, extract_direction, extract_origin, build_affine,
    get_axcodes, resample, resample_to_spacing, reorient_to_axcodes,
    compose_transforms, invert_resample,
    register_landmarks, evaluate_alignment
)


# ---- Transform correctness -------------------------------------------------

class TestSpacingExtraction:
    def test_axis_aligned(self):
        affine = np.load('/app/data/affine_ras.npy')
        spacing = extract_spacing(affine)
        np.testing.assert_allclose(spacing, [1.0, 0.8, 1.5], atol=1e-10)

    def test_oblique(self):
        affine = np.load('/app/data/affine_oblique.npy')
        spacing = extract_spacing(affine)
        np.testing.assert_allclose(spacing, [1.0, 0.8, 1.5], atol=1e-10)

    def test_scaled_identity(self):
        affine = np.diag([2.0, 3.0, 4.0, 1.0])
        spacing = extract_spacing(affine)
        np.testing.assert_allclose(spacing, [2.0, 3.0, 4.0], atol=1e-10)


class TestAffineRoundTrip:
    def test_ras(self):
        affine = np.load('/app/data/affine_ras.npy')
        rebuilt = build_affine(
            extract_spacing(affine), extract_direction(affine), extract_origin(affine)
        )
        np.testing.assert_allclose(rebuilt, affine, atol=1e-10)

    def test_oblique(self):
        affine = np.load('/app/data/affine_oblique.npy')
        rebuilt = build_affine(
            extract_spacing(affine), extract_direction(affine), extract_origin(affine)
        )
        np.testing.assert_allclose(rebuilt, affine, atol=1e-10)


class TestAxisCodes:
    def test_ras(self):
        affine = np.load('/app/data/affine_ras.npy')
        assert get_axcodes(affine) == 'RAS'

    def test_lps(self):
        affine = np.diag([-1.0, -0.8, 1.5, 1.0])
        assert get_axcodes(affine) == 'LPS'

    def test_oblique(self):
        affine = np.load('/app/data/affine_oblique.npy')
        assert get_axcodes(affine) == 'RAS'


class TestResample:
    def test_identity(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        result = resample(volume, affine, affine, volume.shape, order=1)
        np.testing.assert_allclose(result, volume, atol=1e-10)

    def test_translation(self):
        data = np.zeros((10, 12, 8), dtype=np.float64)
        data[5, 6, 4] = 1.0
        src = np.eye(4)
        tgt = np.eye(4)
        tgt[0, 3] = 1.0
        result = resample(data, src, tgt, (10, 12, 8), order=0)
        assert result[4, 6, 4] == 1.0
        assert result[5, 6, 4] == 0.0


class TestResampleToSpacing:
    def test_2mm_shape(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        result, _ = resample_to_spacing(volume, affine, [2.0, 2.0, 2.0])
        assert result.shape == (16, 16, 21), f"Expected (16, 16, 21), got {result.shape}"

    def test_fractional_shape(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        result, _ = resample_to_spacing(volume, affine, [1.2, 1.2, 1.2])
        assert result.shape == (27, 27, 35), f"Expected (27, 27, 35), got {result.shape}"

    def test_origin_preserved(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        _, new_aff = resample_to_spacing(volume, affine, [2.0, 2.0, 2.0])
        np.testing.assert_allclose(new_aff[:3, 3], affine[:3, 3], atol=1e-10)

    def test_new_spacing_in_affine(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        _, new_aff = resample_to_spacing(volume, affine, [2.0, 2.0, 2.0])
        np.testing.assert_allclose(extract_spacing(new_aff), [2.0, 2.0, 2.0], atol=1e-10)


class TestReorient:
    def test_ras_to_lps_world_coords(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        _, new_aff = reorient_to_axcodes(volume, affine, 'LPS')
        ras_world = affine @ [0, 0, 0, 1]
        lps_world = new_aff @ [31, 39, 0, 1]
        np.testing.assert_allclose(ras_world, lps_world, atol=1e-10)

    def test_ras_to_lps_data(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        result, _ = reorient_to_axcodes(volume, affine, 'LPS')
        assert result.shape == (32, 40, 28)
        assert result[31, 39, 0] == volume[0, 0, 0]
        assert result[0, 0, 0] == volume[31, 39, 0]

    def test_ras_to_sar(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        result, new_aff = reorient_to_axcodes(volume, affine, 'SAR')
        assert result.shape == (28, 40, 32)
        assert result[10, 5, 3] == volume[3, 5, 10]
        sar_world = new_aff @ [10, 5, 3, 1]
        ras_world = affine @ [3, 5, 10, 1]
        np.testing.assert_allclose(sar_world, ras_world, atol=1e-10)


class TestInvert:
    def test_round_trip(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        resampled, new_aff = resample_to_spacing(volume, affine, [2.0, 2.0, 2.0])
        recovered = invert_resample(resampled, new_aff, volume.shape, affine, order=1)
        error = np.mean(np.abs(recovered - volume))
        assert error < 0.02, f"Round-trip error too large: {error}"

    def test_identity(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        recovered = invert_resample(volume, affine, volume.shape, affine, order=1)
        np.testing.assert_allclose(recovered, volume, atol=1e-10)

    def test_invert_matches_manual(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        resampled, new_aff = resample_to_spacing(volume, affine, [2.0, 2.0, 2.0])
        manual = resample(resampled, new_aff, affine, volume.shape, order=1)
        auto = invert_resample(resampled, new_aff, volume.shape, affine, order=1)
        np.testing.assert_allclose(auto, manual, atol=1e-10)


# ---- Registration -----------------------------------------------------------

class TestRegistration:
    @staticmethod
    def _landmarks():
        return (np.load('/app/data/src_landmarks.npy'),
                np.load('/app/data/tgt_landmarks.npy'))

    def test_mapping_accuracy(self):
        src, tgt = self._landmarks()
        M = register_landmarks(src, tgt)
        for i in range(len(src)):
            mapped = M[:3, :3] @ src[i] + M[:3, 3]
            np.testing.assert_allclose(mapped, tgt[i], atol=1e-8,
                                       err_msg=f"Landmark {i} mapping error")

    def test_proper_rotation(self):
        src, tgt = self._landmarks()
        M = register_landmarks(src, tgt)
        np.testing.assert_allclose(np.linalg.det(M[:3, :3]), 1.0, atol=1e-8,
                                   err_msg="Must be proper rotation (det=+1)")

    def test_identity(self):
        src, _ = self._landmarks()
        M = register_landmarks(src, src)
        np.testing.assert_allclose(M, np.eye(4), atol=1e-6)


class TestAlignment:
    def test_ncc_identical(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        ncc = evaluate_alignment(volume, affine, volume, affine, metric='ncc')
        np.testing.assert_allclose(ncc, 1.0, atol=1e-10)

    def test_mse_identical(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        mse = evaluate_alignment(volume, affine, volume, affine, metric='mse')
        np.testing.assert_allclose(mse, 0.0, atol=1e-10)

    def test_ncc_shifted(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        shifted = affine.copy()
        shifted[0, 3] += 3.0
        ncc = evaluate_alignment(volume, affine, volume, shifted, metric='ncc')
        assert 0.0 < ncc < 1.0, f"NCC of shifted volumes should be in (0,1), got {ncc}"

    def test_mse_shifted(self):
        volume = np.load('/app/data/volume.npy')
        affine = np.load('/app/data/affine_ras.npy')
        shifted = affine.copy()
        shifted[0, 3] += 3.0
        mse = evaluate_alignment(volume, affine, volume, shifted, metric='mse')
        assert mse > 1e-4, f"MSE of shifted volumes should be positive, got {mse}"


# ---- Pipeline configuration -------------------------------------------------

class TestPipelineConfig:
    def test_spacing_ref_resolves_to_target(self):
        """Pipeline resample step must reference the 2mm isotropic target spacing."""
        with open('/app/configs/pipeline.json') as f:
            pipeline = json.load(f)
        with open('/app/configs/settings.json') as f:
            settings = json.load(f)
        resample_step = next(s for s in pipeline['steps'] if s['name'] == 'resample')
        key = resample_step['params']['spacing_ref']
        actual = settings.get(key)
        assert actual == [2.0, 2.0, 2.0], \
            f"spacing_ref '{key}' resolves to {actual}, expected [2.0, 2.0, 2.0]"

    def test_ordering_satisfies_db_constraints(self):
        """Step ordering must satisfy all constraints in metadata.db."""
        with open('/app/configs/pipeline.json') as f:
            pipeline = json.load(f)
        step_names = [s['name'] for s in pipeline['steps']]
        conn = sqlite3.connect('/app/metadata.db')
        constraints = conn.execute(
            'SELECT step_before, step_after, reason FROM transform_constraints'
        ).fetchall()
        conn.close()
        for before, after, reason in constraints:
            if before in step_names and after in step_names:
                assert step_names.index(before) < step_names.index(after), \
                    f"Constraint violated: '{before}' must precede '{after}' — {reason}"


# ---- Pipeline validator (must be created by solver) -------------------------

class TestPipelineValidator:
    def test_validator_script_exists(self):
        assert os.path.isfile('/app/validate_pipeline.py'), \
            "/app/validate_pipeline.py must be created"

    def test_valid_pipeline_passes(self):
        result = subprocess.run(
            ['python3', '/app/validate_pipeline.py', '/app/configs/pipeline.json'],
            capture_output=True, text=True, cwd='/app'
        )
        assert result.returncode == 0, \
            f"Validator rejected correct pipeline: stdout={result.stdout} stderr={result.stderr}"
        assert 'VALID' in result.stdout.upper(), \
            "Validator must print VALID for a correct pipeline"

    def test_detects_orient_after_resample(self):
        bad = {
            "name": "bad_ordering",
            "steps": [
                {"name": "resample", "transform": "x", "params": {}},
                {"name": "orient", "transform": "x", "params": {}}
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, dir='/tmp'
        ) as f:
            json.dump(bad, f)
            path = f.name
        try:
            result = subprocess.run(
                ['python3', '/app/validate_pipeline.py', path],
                capture_output=True, text=True, cwd='/app'
            )
            assert result.returncode != 0, \
                "Validator should reject pipeline with orient after resample"
        finally:
            os.unlink(path)

    def test_detects_normalize_before_orient(self):
        bad = {
            "name": "bad_normalize_first",
            "steps": [
                {"name": "normalize", "transform": "x", "params": {}},
                {"name": "orient", "transform": "x", "params": {}},
                {"name": "resample", "transform": "x", "params": {}}
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, dir='/tmp'
        ) as f:
            json.dump(bad, f)
            path = f.name
        try:
            result = subprocess.run(
                ['python3', '/app/validate_pipeline.py', path],
                capture_output=True, text=True, cwd='/app'
            )
            assert result.returncode != 0, \
                "Validator should reject pipeline with normalize before orient"
        finally:
            os.unlink(path)
