
"""
Tests for the ISLES segmentation evaluation pipeline.

Generates synthetic NIfTI file pairs with analytically derivable metric values,
runs the evaluation tool, and verifies the output against expected results.
"""

import json
import math
import os
import shutil
import subprocess

import nibabel as nib
import numpy as np
import pytest

GT_DIR = "/tmp/isles_eval_test_gt"
PRED_DIR = "/tmp/isles_eval_test_pred"
OUTPUT_FILE = "/tmp/isles_eval_test_output.json"
TOOL_PATH = "/app/evaluate.py"

NUM_CASES = 13


def _make_nifti(data, voxel_sizes=(1.0, 1.0, 1.0), affine=None, dtype=np.uint8):
    """Create a NIfTI image from a numpy array."""
    if affine is None:
        affine = np.diag(list(voxel_sizes) + [1.0])
    img = nib.Nifti1Image(data.astype(dtype), affine)
    return img


def _save_pair(gt_data, pred_data, name, voxel_sizes=(1.0, 1.0, 1.0),
               affine=None, pred_dtype=np.uint8):
    """Save a ground truth / prediction pair as NIfTI files."""
    gt_img = _make_nifti(gt_data, voxel_sizes, affine, dtype=np.uint8)
    pred_img = _make_nifti(pred_data, voxel_sizes, affine, dtype=pred_dtype)
    nib.save(gt_img, os.path.join(GT_DIR, f"{name}.nii.gz"))
    nib.save(pred_img, os.path.join(PRED_DIR, f"{name}.nii.gz"))


def _generate_test_data():
    """Generate all synthetic test scenarios."""

    # --- Scenario 1: perfect_match ---
    # Two clearly separated cube lesions, prediction = ground truth
    shape = (30, 30, 30)
    gt = np.zeros(shape, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1   # 1000 voxels
    gt[20:25, 20:25, 20:25] = 1  # 125 voxels
    _save_pair(gt, gt.copy(), "perfect_match")

    # --- Scenario 2: partial_overlap ---
    # Single lesion with 50% Dice overlap
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[10:20, 10:20, 10:20] = 1    # 1000 voxels
    pred[15:25, 10:20, 10:20] = 1   # 1000 voxels, intersection = 500
    _save_pair(gt, pred, "partial_overlap")

    # --- Scenario 3: missed_lesion ---
    # GT has 2 lesions, prediction only detects 1
    shape2 = (40, 40, 40)
    gt = np.zeros(shape2, dtype=np.uint8)
    pred = np.zeros(shape2, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1     # lesion A: 1000 voxels
    gt[25:35, 25:35, 25:35] = 1   # lesion B: 1000 voxels
    pred[5:15, 5:15, 5:15] = 1    # only detects lesion A
    _save_pair(gt, pred, "missed_lesion")

    # --- Scenario 4: false_positive ---
    # GT has 1 lesion, prediction has that lesion + 1 spurious lesion
    gt = np.zeros(shape2, dtype=np.uint8)
    pred = np.zeros(shape2, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1       # 1000 voxels
    pred[5:15, 5:15, 5:15] = 1     # correct detection
    pred[25:35, 25:35, 25:35] = 1   # false positive: 1000 voxels
    _save_pair(gt, pred, "false_positive")

    # --- Scenario 5: empty_pred ---
    # GT has lesions, prediction is empty
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1    # 1000 voxels
    gt[20:25, 20:25, 20:25] = 1  # 125 voxels, total = 1125
    _save_pair(gt, pred, "empty_pred")

    # --- Scenario 6: both_empty ---
    # Both masks are entirely empty
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    _save_pair(gt, pred, "both_empty")

    # --- Scenario 7: anisotropic ---
    # Non-isotropic voxel sizes (0.5 x 0.5 x 3.0 mm)
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1     # 1000 voxels
    pred[5:15, 5:15, 5:13] = 1    # 800 voxels (subset of GT)
    _save_pair(gt, pred, "anisotropic", voxel_sizes=(0.5, 0.5, 3.0))

    # --- Scenario 8: below_threshold ---
    # Both have 1 lesion but IoU < 0.2 threshold — should NOT match
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[0:10, 0:10, 0:10] = 1      # 1000 voxels
    pred[9:20, 0:10, 0:10] = 1     # 1100 voxels, intersection = 100
    # IoU = 100 / (1000 + 1100 - 100) = 100/2000 = 0.05 < 0.2
    _save_pair(gt, pred, "below_threshold")

    # --- Scenario 9: sheared_affine ---
    # Affine matrix with shear — det(M) != product of column norms.
    # Tests that volume computation uses the affine determinant.
    # M = [[1, 0.5, 0], [0, 1, 0], [0, 0, 2]]
    # det(M) = 2.0 mm³ → voxel_vol = 0.002 mL
    shear_affine = np.array([
        [1.0, 0.5, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 2.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1     # 1000 voxels → 2.0 mL
    pred[5:15, 5:15, 5:10] = 1    # 500 voxels → 1.0 mL (subset of GT)
    _save_pair(gt, pred, "sheared_affine", affine=shear_affine)

    # --- Scenario 10: float_prediction ---
    # Prediction stored as float probabilities. Sub-threshold values (0.3)
    # must NOT be counted as positive. Only values > 0.5 are lesion.
    gt = np.zeros(shape, dtype=np.uint8)
    gt[5:15, 5:15, 5:15] = 1    # 1000 voxels

    pred_float = np.zeros(shape, dtype=np.float32)
    pred_float[5:15, 5:15, 5:15] = 0.8    # above 0.5 → positive
    pred_float[5:15, 5:15, 15:20] = 0.3   # below 0.5 → must be excluded
    _save_pair(gt, pred_float, "float_prediction", pred_dtype=np.float32)

    # --- Scenario 11: parallel_slabs ---
    # Two 1-voxel-thick slabs at z=5 and z=10, isotropic 1mm voxels.
    # Tests basic surface distance computation.
    # All directed distances = 5.0mm → ASSD = 5.0, HD95 = 5.0
    slab_shape = (20, 20, 20)
    gt = np.zeros(slab_shape, dtype=np.uint8)
    pred = np.zeros(slab_shape, dtype=np.uint8)
    gt[:, :, 5] = 1    # 400 voxels
    pred[:, :, 10] = 1  # 400 voxels
    _save_pair(gt, pred, "parallel_slabs")

    # --- Scenario 12: aniso_distance ---
    # Slabs at z=5 and z=8 with anisotropic voxels (1x1x3mm).
    # Physical z-distance = 3 voxels × 3mm = 9mm.
    # Tests that surface distances use physical coordinates, not voxel indices.
    aniso_shape = (10, 10, 20)
    gt = np.zeros(aniso_shape, dtype=np.uint8)
    pred = np.zeros(aniso_shape, dtype=np.uint8)
    gt[:, :, 5] = 1    # 100 voxels
    pred[:, :, 8] = 1   # 100 voxels
    _save_pair(gt, pred, "aniso_distance", voxel_sizes=(1.0, 1.0, 3.0))

    # --- Scenario 13: sheared_distance ---
    # Single-voxel masks with combined x+y offset under a sheared affine.
    # Discriminates correct (full affine transform) from incorrect
    # (column-norm scaling) physical distance computation.
    #
    # GT at (5,5,5), Pred at (8,8,5).
    # Affine M = [[1, 0.5, 0], [0, 1, 0], [0, 0, 2]]
    # Physical GT:   M@(5,5,5) = (7.5, 5, 10)
    # Physical Pred: M@(8,8,5) = (12,  8, 10)
    # Correct distance:  sqrt(4.5² + 3²) = sqrt(29.25) ≈ 5.408
    # Naive zoom-based:  sqrt(3² + (3·√1.25)²) = sqrt(9+11.25) = sqrt(20.25) = 4.5
    shear_dist_affine = np.array([
        [1.0, 0.5, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 2.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    gt = np.zeros(shape, dtype=np.uint8)
    pred = np.zeros(shape, dtype=np.uint8)
    gt[5, 5, 5] = 1
    pred[8, 8, 5] = 1
    _save_pair(gt, pred, "sheared_distance", affine=shear_dist_affine)


@pytest.fixture(scope="session")
def evaluation_results():
    """Generate test data, run evaluation tool, return parsed JSON results."""
    # Clean up previous runs
    for d in [GT_DIR, PRED_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)

    _generate_test_data()

    # Verify the tool exists
    assert os.path.isfile(TOOL_PATH), (
        f"Evaluation tool not found at {TOOL_PATH}. "
        "The agent must create this file."
    )

    # Run the evaluation tool
    result = subprocess.run(
        [
            "python3", TOOL_PATH,
            "--gt", GT_DIR,
            "--pred", PRED_DIR,
            "--output", OUTPUT_FILE,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Evaluation tool exited with code {result.returncode}.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    assert os.path.isfile(OUTPUT_FILE), f"Output file not created at {OUTPUT_FILE}"

    with open(OUTPUT_FILE) as f:
        data = json.load(f)

    return data


# ──────────────────────────────────────────────────────────────
# Output structure tests
# ──────────────────────────────────────────────────────────────

def test_output_structure(evaluation_results):
    """Verify the JSON output has the required top-level keys and per-case fields."""
    assert "per_case" in evaluation_results, "Missing 'per_case' key"
    assert "aggregate" in evaluation_results, "Missing 'aggregate' key"
    assert len(evaluation_results["per_case"]) == NUM_CASES, (
        f"Expected {NUM_CASES} cases, got {len(evaluation_results['per_case'])}: "
        f"{list(evaluation_results['per_case'].keys())}"
    )

    required_fields = [
        "dice", "avd_ml", "assd_mm", "hd95_mm",
        "lesion_f1", "panoptic_quality",
        "instance_count_diff", "num_gt_instances", "num_pred_instances",
    ]
    for case_name, metrics in evaluation_results["per_case"].items():
        for field in required_fields:
            assert field in metrics, f"Missing '{field}' in case '{case_name}'"


# ──────────────────────────────────────────────────────────────
# Per-case metric tests
# ──────────────────────────────────────────────────────────────

def test_perfect_match(evaluation_results):
    r = evaluation_results["per_case"]["perfect_match"]
    assert np.isclose(r["dice"], 1.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], 0.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], 0.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 1.0, atol=1e-6), f"pq: {r['panoptic_quality']}"
    assert r["instance_count_diff"] == 0, f"icd: {r['instance_count_diff']}"
    assert r["num_gt_instances"] == 2, f"num_gt: {r['num_gt_instances']}"
    assert r["num_pred_instances"] == 2, f"num_pred: {r['num_pred_instances']}"


def test_partial_overlap(evaluation_results):
    """Single lesion pair with 50% Dice, IoU=1/3, F1=1.0, PQ=1/3."""
    r = evaluation_results["per_case"]["partial_overlap"]
    assert np.isclose(r["dice"], 0.5, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 1.0 / 3.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_missed_lesion(evaluation_results):
    """2 GT lesions, 1 pred. TP=1, FN=1, FP=0 → F1=2/3."""
    r = evaluation_results["per_case"]["missed_lesion"]
    assert np.isclose(r["dice"], 2.0 / 3.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 1.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 2.0 / 3.0, atol=1e-6), (
        f"lesion_f1: {r['lesion_f1']}"
    )
    assert np.isclose(r["panoptic_quality"], 2.0 / 3.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 1
    assert r["num_gt_instances"] == 2
    assert r["num_pred_instances"] == 1


def test_false_positive(evaluation_results):
    """1 GT lesion, 2 pred. TP=1, FP=1, FN=0 → F1=2/3."""
    r = evaluation_results["per_case"]["false_positive"]
    assert np.isclose(r["dice"], 2.0 / 3.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 1.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 2.0 / 3.0, atol=1e-6), (
        f"lesion_f1: {r['lesion_f1']}"
    )
    assert np.isclose(r["panoptic_quality"], 2.0 / 3.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 1
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 2


def test_empty_pred(evaluation_results):
    """GT has 2 lesions (1125 voxels), pred empty. Dice=0, F1=0, surface=-1."""
    r = evaluation_results["per_case"]["empty_pred"]
    assert np.isclose(r["dice"], 0.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 1.125, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], -1.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], -1.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 0.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 2
    assert r["num_gt_instances"] == 2
    assert r["num_pred_instances"] == 0


def test_both_empty(evaluation_results):
    """Both masks empty → all metrics at ideal values."""
    r = evaluation_results["per_case"]["both_empty"]
    assert np.isclose(r["dice"], 1.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], 0.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], 0.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 1.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 0
    assert r["num_pred_instances"] == 0


def test_anisotropic_voxels(evaluation_results):
    """Anisotropic voxels (0.5x0.5x3.0 mm). Voxel vol = 0.75 mm^3.
    GT: 1000 vox → 0.75 mL, Pred: 800 vox → 0.6 mL.
    Dice = 1600/1800 = 8/9. IoU = 800/1000 = 0.8. AVD = 0.15 mL.
    """
    r = evaluation_results["per_case"]["anisotropic"]
    assert np.isclose(r["dice"], 8.0 / 9.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.15, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.8, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_below_threshold(evaluation_results):
    """Both have 1 lesion but IoU=0.05 < threshold 0.2 → no match.
    F1=0 even though binary Dice > 0. This distinguishes voxel-level
    from instance-level metrics.
    """
    r = evaluation_results["per_case"]["below_threshold"]
    expected_dice = 200.0 / 2100.0  # 2*100 / (1000 + 1100)
    assert np.isclose(r["dice"], expected_dice, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.1, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 0.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_sheared_affine(evaluation_results):
    """Sheared affine where det(M) != product of column norms.
    M = [[1, 0.5, 0], [0, 1, 0], [0, 0, 2]]
    det(M) = 2.0 mm^3 → voxel_vol = 0.002 mL

    GT: 1000 voxels → 2.0 mL.  Pred: 500 voxels → 1.0 mL.
    AVD = 1.0 mL.  Dice = 2*500/(1000+500) = 2/3.
    IoU = 500/1000 = 0.5 → matched. F1=1, SQ=0.5, PQ=0.5.
    """
    r = evaluation_results["per_case"]["sheared_affine"]
    assert np.isclose(r["dice"], 2.0 / 3.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 1.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert r["assd_mm"] > 0, f"assd_mm should be > 0: {r['assd_mm']}"
    assert r["hd95_mm"] > 0, f"hd95_mm should be > 0: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.5, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_float_prediction(evaluation_results):
    """Prediction stored as float probabilities. Sub-threshold voxels
    (value 0.3 <= 0.5) must be excluded. Only voxels > 0.5 are positive.
    """
    r = evaluation_results["per_case"]["float_prediction"]
    assert np.isclose(r["dice"], 1.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], 0.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], 0.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 1.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 1.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_parallel_slabs(evaluation_results):
    """Two 1-voxel-thick parallel slabs at z=5 and z=10, isotropic 1mm.
    All 800 directed surface distances are exactly 5.0mm.
    No overlap → Dice=0, F1=0.
    """
    r = evaluation_results["per_case"]["parallel_slabs"]
    assert np.isclose(r["dice"], 0.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], 5.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], 5.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 0.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_aniso_distance(evaluation_results):
    """Slabs at z=5 and z=8 with anisotropic voxels (1×1×3 mm).
    Physical z-distance = 3 voxels × 3mm = 9mm.
    Tests that surface distances use physical coordinates.
    """
    r = evaluation_results["per_case"]["aniso_distance"]
    assert np.isclose(r["dice"], 0.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], 9.0, atol=1e-6), f"assd_mm: {r['assd_mm']}"
    assert np.isclose(r["hd95_mm"], 9.0, atol=1e-6), f"hd95_mm: {r['hd95_mm']}"
    assert np.isclose(r["lesion_f1"], 0.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


def test_sheared_distance(evaluation_results):
    """Single-voxel masks with sheared affine. Tests that surface distance
    computation uses the full affine transformation, not column-norm scaling.

    GT at voxel (5,5,5) → physical (7.5, 5, 10)
    Pred at voxel (8,8,5) → physical (12, 8, 10)
    Correct distance: sqrt(4.5² + 3²) = sqrt(29.25) ≈ 5.408
    Naive zoom-based distance: sqrt(3² + (3·√1.25)²) = 4.5 (WRONG)
    """
    r = evaluation_results["per_case"]["sheared_distance"]
    expected_dist = math.sqrt(29.25)
    assert np.isclose(r["dice"], 0.0, atol=1e-6), f"dice: {r['dice']}"
    assert np.isclose(r["avd_ml"], 0.0, atol=1e-6), f"avd_ml: {r['avd_ml']}"
    assert np.isclose(r["assd_mm"], expected_dist, atol=1e-4), (
        f"assd_mm: {r['assd_mm']} (expected {expected_dist})"
    )
    assert np.isclose(r["hd95_mm"], expected_dist, atol=1e-4), (
        f"hd95_mm: {r['hd95_mm']} (expected {expected_dist})"
    )
    # Verify it is NOT the naive zoom-based answer (4.5)
    assert abs(r["assd_mm"] - 4.5) > 0.5, (
        f"assd_mm={r['assd_mm']} is suspiciously close to naive zoom-based 4.5"
    )
    assert np.isclose(r["lesion_f1"], 0.0, atol=1e-6), f"lesion_f1: {r['lesion_f1']}"
    assert np.isclose(r["panoptic_quality"], 0.0, atol=1e-6), (
        f"pq: {r['panoptic_quality']}"
    )
    assert r["instance_count_diff"] == 0
    assert r["num_gt_instances"] == 1
    assert r["num_pred_instances"] == 1


# ──────────────────────────────────────────────────────────────
# Aggregate metric tests
# ──────────────────────────────────────────────────────────────

def test_aggregate_keys(evaluation_results):
    """Verify aggregate section has the required fields."""
    agg = evaluation_results["aggregate"]
    for key in [
        "mean_dice", "mean_avd_ml", "mean_assd_mm", "mean_hd95_mm",
        "mean_lesion_f1", "mean_panoptic_quality", "mean_instance_count_diff",
    ]:
        assert key in agg, f"Missing aggregate key '{key}'"


def test_aggregate_mean_dice(evaluation_results):
    """Verify mean_dice equals arithmetic mean of per-case Dice values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    expected = np.mean([v["dice"] for v in per_case.values()])
    assert np.isclose(agg["mean_dice"], expected, atol=1e-6), (
        f"mean_dice: {agg['mean_dice']} != {expected}"
    )


def test_aggregate_mean_f1(evaluation_results):
    """Verify mean_lesion_f1 equals arithmetic mean of per-case F1 values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    expected = np.mean([v["lesion_f1"] for v in per_case.values()])
    assert np.isclose(agg["mean_lesion_f1"], expected, atol=1e-6), (
        f"mean_lesion_f1: {agg['mean_lesion_f1']} != {expected}"
    )


def test_aggregate_mean_avd(evaluation_results):
    """Verify mean_avd_ml equals arithmetic mean of per-case AVD values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    expected = np.mean([v["avd_ml"] for v in per_case.values()])
    assert np.isclose(agg["mean_avd_ml"], expected, atol=1e-6), (
        f"mean_avd_ml: {agg['mean_avd_ml']} != {expected}"
    )


def test_aggregate_mean_pq(evaluation_results):
    """Verify mean_panoptic_quality equals arithmetic mean of per-case PQ values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    expected = np.mean([v["panoptic_quality"] for v in per_case.values()])
    assert np.isclose(agg["mean_panoptic_quality"], expected, atol=1e-6), (
        f"mean_panoptic_quality: {agg['mean_panoptic_quality']} != {expected}"
    )


def test_aggregate_mean_assd(evaluation_results):
    """Verify mean_assd_mm equals arithmetic mean of valid (non -1.0) ASSD values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    valid = [v["assd_mm"] for v in per_case.values()
             if not np.isclose(v["assd_mm"], -1.0, atol=1e-6)]
    assert len(valid) > 0, "No valid ASSD values found"
    expected = np.mean(valid)
    assert np.isclose(agg["mean_assd_mm"], expected, atol=1e-6), (
        f"mean_assd_mm: {agg['mean_assd_mm']} != {expected}"
    )


def test_aggregate_mean_hd95(evaluation_results):
    """Verify mean_hd95_mm equals arithmetic mean of valid (non -1.0) HD95 values."""
    per_case = evaluation_results["per_case"]
    agg = evaluation_results["aggregate"]
    valid = [v["hd95_mm"] for v in per_case.values()
             if not np.isclose(v["hd95_mm"], -1.0, atol=1e-6)]
    assert len(valid) > 0, "No valid HD95 values found"
    expected = np.mean(valid)
    assert np.isclose(agg["mean_hd95_mm"], expected, atol=1e-6), (
        f"mean_hd95_mm: {agg['mean_hd95_mm']} != {expected}"
    )
