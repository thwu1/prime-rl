#!/usr/bin/env python3
"""Verify that the multi-terrain adaptive cloud detection pipeline works correctly.

Tests cover: pipeline execution via make, score structure/quality, per-terrain
accuracy, prediction format, and metric edge-case correctness.
"""


import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Terrain mapping (deterministic from data generation)
TERRAIN_MAP = {
    'chip_0000': 'vegetation', 'chip_0001': 'vegetation',
    'chip_0002': 'vegetation', 'chip_0003': 'vegetation',
    'chip_0004': 'water', 'chip_0005': 'water',
    'chip_0006': 'water', 'chip_0007': 'water',
    'chip_0008': 'urban', 'chip_0009': 'urban',
    'chip_0010': 'urban', 'chip_0011': 'urban',
}

_make_result = None


def setup_module():
    """Run the full pipeline via make to verify end-to-end reproducibility."""
    global _make_result
    assert shutil.which('make'), "make not found in PATH"

    # Clean any prior results
    subprocess.run(
        ['make', '-C', '/app', 'clean'],
        capture_output=True, text=True, timeout=30
    )

    # Run the full pipeline
    _make_result = subprocess.run(
        ['make', '-C', '/app', 'score'],
        capture_output=True, text=True, timeout=180
    )


class TestPipelineExecution:
    """Verify that make score executes successfully."""

    def test_make_score_succeeds(self):
        assert _make_result is not None, "setup_module did not run"
        assert _make_result.returncode == 0, (
            f"make score failed (exit {_make_result.returncode}):\n"
            f"STDOUT:\n{_make_result.stdout[-3000:]}\n"
            f"STDERR:\n{_make_result.stderr[-3000:]}"
        )

    def test_score_json_produced(self):
        assert os.path.exists('/app/results/score.json'), \
            "make score did not produce /app/results/score.json"


class TestScoreStructure:
    """Verify score.json has the required structure."""

    def setup_method(self):
        if not os.path.exists('/app/results/score.json'):
            pytest.skip("score.json not found")
        with open('/app/results/score.json') as f:
            self.data = json.load(f)

    def test_has_overall_iou(self):
        assert 'overall_iou' in self.data, "Missing 'overall_iou'"

    def test_has_overall_dice(self):
        assert 'overall_dice' in self.data, "Missing 'overall_dice'"

    def test_has_composite_score(self):
        assert 'composite_score' in self.data, "Missing 'composite_score'"

    def test_has_num_chips(self):
        assert 'num_chips' in self.data, "Missing 'num_chips'"

    def test_has_per_chip(self):
        assert 'per_chip' in self.data, "Missing 'per_chip'"

    def test_num_chips_is_12(self):
        assert self.data['num_chips'] == 12, \
            f"Expected 12 chips, got {self.data['num_chips']}"

    def test_per_chip_count(self):
        assert len(self.data['per_chip']) == 12, \
            f"Expected 12 per-chip entries, got {len(self.data['per_chip'])}"

    def test_per_chip_has_iou_and_dice(self):
        for chip_id, metrics in self.data['per_chip'].items():
            assert 'iou' in metrics, f"{chip_id} missing 'iou'"
            assert 'dice' in metrics, f"{chip_id} missing 'dice'"


class TestScoreQuality:
    """Verify the pipeline achieves required accuracy thresholds."""

    def setup_method(self):
        if not os.path.exists('/app/results/score.json'):
            pytest.skip("score.json not found")
        with open('/app/results/score.json') as f:
            self.data = json.load(f)

    def test_overall_iou_above_threshold(self):
        iou = self.data['overall_iou']
        assert not math.isnan(iou), "overall_iou is NaN"
        assert iou > 0.85, f"Overall IoU {iou:.4f} below 0.85"

    def test_overall_dice_above_threshold(self):
        dice = self.data['overall_dice']
        assert not math.isnan(dice), "overall_dice is NaN"
        assert dice > 0.85, f"Overall Dice {dice:.4f} below 0.85"

    def test_composite_score_valid(self):
        cs = self.data['composite_score']
        assert not math.isnan(cs), "composite_score is NaN"
        assert 0.0 < cs <= 1.0, \
            f"composite_score {cs:.4f} outside (0.0, 1.0]"

    def test_per_chip_iou_all_above_threshold(self):
        for chip_id, metrics in self.data['per_chip'].items():
            iou = metrics['iou']
            assert not math.isnan(iou), f"{chip_id} IoU is NaN"
            assert iou > 0.70, \
                f"{chip_id} IoU {iou:.4f} below 0.70"

    def test_per_chip_dice_not_nan(self):
        for chip_id, metrics in self.data['per_chip'].items():
            assert not math.isnan(metrics['dice']), \
                f"{chip_id} Dice is NaN"


class TestPerTerrainQuality:
    """Verify each terrain type achieves acceptable accuracy."""

    def setup_method(self):
        if not os.path.exists('/app/results/score.json'):
            pytest.skip("score.json not found")
        with open('/app/results/score.json') as f:
            self.data = json.load(f)

    def _terrain_mean_iou(self, terrain):
        ious = [
            self.data['per_chip'][cid]['iou']
            for cid, t in TERRAIN_MAP.items()
            if t == terrain and cid in self.data['per_chip']
        ]
        return sum(ious) / len(ious) if ious else 0.0

    def test_vegetation_terrain_iou(self):
        mean_iou = self._terrain_mean_iou('vegetation')
        assert mean_iou > 0.80, \
            f"Vegetation mean IoU {mean_iou:.4f} below 0.80"

    def test_water_terrain_iou(self):
        mean_iou = self._terrain_mean_iou('water')
        assert mean_iou > 0.80, \
            f"Water mean IoU {mean_iou:.4f} below 0.80"

    def test_urban_terrain_iou(self):
        mean_iou = self._terrain_mean_iou('urban')
        assert mean_iou > 0.80, \
            f"Urban mean IoU {mean_iou:.4f} below 0.80"


class TestPredictions:
    """Verify prediction files have correct format."""

    def test_predictions_dir_exists(self):
        assert Path('/app/predictions').is_dir(), \
            "/app/predictions directory not found"

    def test_prediction_count(self):
        tifs = list(Path('/app/predictions').glob('*.tif'))
        assert len(tifs) == 12, f"Expected 12 TIFs, found {len(tifs)}"

    def test_prediction_dimensions(self):
        for tif in sorted(Path('/app/predictions').glob('*.tif')):
            img = np.array(Image.open(tif))
            assert img.shape == (512, 512), \
                f"{tif.name} shape {img.shape} != (512, 512)"

    def test_prediction_values_binary(self):
        for tif in sorted(Path('/app/predictions').glob('*.tif')):
            img = np.array(Image.open(tif))
            assert set(np.unique(img)).issubset({0, 1}), \
                f"{tif.name} has non-binary values"


class TestMetricCorrectness:
    """Verify the scoring metric handles edge cases correctly.
    These tests are independent of the make pipeline."""

    def test_empty_masks_iou_is_one(self):
        """IoU of two all-zero masks must be 1.0 (perfect agreement on empty)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred_dir = Path(tmpdir) / 'pred'
            label_dir = Path(tmpdir) / 'label'
            pred_dir.mkdir()
            label_dir.mkdir()

            empty = np.zeros((512, 512), dtype=np.uint8)
            Image.fromarray(empty).save(pred_dir / 'empty.tif')
            Image.fromarray(empty).save(label_dir / 'empty.tif')

            output = Path(tmpdir) / 'score.json'
            result = subprocess.run(
                ['python3', '/app/scoring/metric.py',
                 str(pred_dir), str(label_dir), str(output)],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, f"metric failed: {result.stderr}"

            with open(output) as f:
                data = json.load(f)

            assert data['per_chip']['empty']['iou'] == 1.0, \
                f"Empty masks IoU should be 1.0, got {data['per_chip']['empty']['iou']}"

    def test_empty_masks_dice_is_one(self):
        """Dice of two all-zero masks must be 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred_dir = Path(tmpdir) / 'pred'
            label_dir = Path(tmpdir) / 'label'
            pred_dir.mkdir()
            label_dir.mkdir()

            empty = np.zeros((512, 512), dtype=np.uint8)
            Image.fromarray(empty).save(pred_dir / 'empty.tif')
            Image.fromarray(empty).save(label_dir / 'empty.tif')

            output = Path(tmpdir) / 'score.json'
            result = subprocess.run(
                ['python3', '/app/scoring/metric.py',
                 str(pred_dir), str(label_dir), str(output)],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, f"metric failed: {result.stderr}"

            with open(output) as f:
                data = json.load(f)

            assert data['per_chip']['empty']['dice'] == 1.0, \
                f"Empty masks Dice should be 1.0, got {data['per_chip']['empty']['dice']}"

    def test_identical_masks_dice_is_one(self):
        """Dice of two identical non-empty masks must be 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred_dir = Path(tmpdir) / 'pred'
            label_dir = Path(tmpdir) / 'label'
            pred_dir.mkdir()
            label_dir.mkdir()

            mask = np.zeros((512, 512), dtype=np.uint8)
            mask[100:300, 150:400] = 1
            Image.fromarray(mask).save(pred_dir / 'match.tif')
            Image.fromarray(mask).save(label_dir / 'match.tif')

            output = Path(tmpdir) / 'score.json'
            result = subprocess.run(
                ['python3', '/app/scoring/metric.py',
                 str(pred_dir), str(label_dir), str(output)],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, f"metric failed: {result.stderr}"

            with open(output) as f:
                data = json.load(f)

            assert data['per_chip']['match']['dice'] == 1.0, \
                f"Identical masks Dice should be 1.0, got {data['per_chip']['match']['dice']}"

    def test_partial_overlap_dice_correct(self):
        """Dice for known partial overlap must match the analytical value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred_dir = Path(tmpdir) / 'pred'
            label_dir = Path(tmpdir) / 'label'
            pred_dir.mkdir()
            label_dir.mkdir()

            # pred: top half, gt: middle band
            pred = np.zeros((512, 512), dtype=np.uint8)
            pred[0:256, :] = 1  # 256*512 = 131072 pixels
            gt = np.zeros((512, 512), dtype=np.uint8)
            gt[128:384, :] = 1  # 256*512 = 131072 pixels
            # intersection: rows 128-255 = 128*512 = 65536
            # Dice = 2*65536 / (131072+131072) = 0.5

            Image.fromarray(pred).save(pred_dir / 'partial.tif')
            Image.fromarray(gt).save(label_dir / 'partial.tif')

            output = Path(tmpdir) / 'score.json'
            result = subprocess.run(
                ['python3', '/app/scoring/metric.py',
                 str(pred_dir), str(label_dir), str(output)],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, f"metric failed: {result.stderr}"

            with open(output) as f:
                data = json.load(f)

            dice = data['per_chip']['partial']['dice']
            assert abs(dice - 0.5) < 0.01, \
                f"Partial overlap Dice should be ~0.5, got {dice:.4f}"

    def test_composite_score_bounded(self):
        """Composite score must be in [0, 1] for perfect predictions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred_dir = Path(tmpdir) / 'pred'
            label_dir = Path(tmpdir) / 'label'
            pred_dir.mkdir()
            label_dir.mkdir()

            mask = np.zeros((512, 512), dtype=np.uint8)
            mask[100:300, 150:400] = 1
            Image.fromarray(mask).save(pred_dir / 'test.tif')
            Image.fromarray(mask).save(label_dir / 'test.tif')

            output = Path(tmpdir) / 'score.json'
            result = subprocess.run(
                ['python3', '/app/scoring/metric.py',
                 str(pred_dir), str(label_dir), str(output)],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, f"metric failed: {result.stderr}"

            with open(output) as f:
                data = json.load(f)

            cs = data['composite_score']
            assert 0.0 <= cs <= 1.0, \
                f"Composite score {cs:.4f} outside [0, 1]"
