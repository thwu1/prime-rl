#!/usr/bin/env python3
"""
Tests for multi-sensor ARIAC battery cell defect detection pipeline.
Regenerates ground truth from the same seeds used for data generation.
"""

import json
import os
import pytest
import numpy as np

SEED = 20250613
CELL_HEIGHT = 0.065
NUM_CELLS = 12

DEFECT_MAP = {
    0: [], 1: [], 2: [], 3: [],
    4: ['dent'], 5: ['dent'],
    6: ['bulge'], 7: ['bulge'],
    8: ['scratch'], 9: ['scratch'],
    10: ['dent', 'scratch'],
    11: ['bulge', 'dent'],
}

BIAS_A = (0.00078, -0.00052)
BIAS_B = (-0.00114, 0.00089)
BIAS_C = (0.00147, -0.00126)

TRUE_BIAS_B_MINUS_A = (BIAS_B[0] - BIAS_A[0], BIAS_B[1] - BIAS_A[1])
TRUE_BIAS_C_MINUS_A = (BIAS_C[0] - BIAS_A[0], BIAS_C[1] - BIAS_A[1])

CALIBRATION_TOLERANCE = 0.0004
THETA_TOLERANCE = 0.5
Z_TOLERANCE = 0.01

RESULTS_PATH = '/app/inspection_results.json'


def get_ground_truth():
    """Regenerate ground truth defect parameters using per-defect seeds."""
    truth = []
    for cell_id in range(NUM_CELLS):
        defects_spec = DEFECT_MAP[cell_id]

        if not defects_spec:
            truth.append({
                'cell_id': cell_id,
                'passed': True,
                'defects': [],
            })
            continue

        defects = []
        for defect_idx, defect_type in enumerate(defects_spec):
            df_rng = np.random.default_rng(
                SEED * 200 + cell_id * 100 + defect_idx
            )
            d_theta = float(df_rng.uniform(-np.pi, np.pi))

            if defect_type in ('dent', 'bulge'):
                d_z = float(df_rng.uniform(0.012, CELL_HEIGHT - 0.012))
                # Consume remaining params to keep RNG aligned
                df_rng.uniform(0.5, 0.7)    # ang_r
                df_rng.uniform(0.005, 0.008)  # z_r
                df_rng.uniform(0.003, 0.004)  # magnitude
                type_code = 1 if defect_type == 'dent' else 2
            else:  # scratch
                d_z = float(df_rng.uniform(0.015, CELL_HEIGHT - 0.015))
                df_rng.uniform(0.008, 0.012)   # half_len
                df_rng.uniform(0.08, 0.15)     # ang_w
                df_rng.uniform(0.0025, 0.003)  # magnitude
                type_code = 3

            defects.append({
                'defect_type': type_code,
                'theta': d_theta,
                'z': d_z,
            })

        truth.append({
            'cell_id': cell_id,
            'passed': False,
            'defects': defects,
        })

    return truth


def angular_distance(a, b):
    """Minimum angular distance between two angles."""
    diff = a - b
    return abs((diff + np.pi) % (2 * np.pi) - np.pi)


@pytest.fixture(scope='module')
def results():
    assert os.path.exists(RESULTS_PATH), \
        f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope='module')
def ground_truth():
    return get_ground_truth()


def test_results_file_exists():
    """Results file must exist."""
    assert os.path.exists(RESULTS_PATH), \
        f"Results file not found at {RESULTS_PATH}"


def test_results_top_level_structure(results):
    """Results must contain sensor_calibration and cells."""
    assert 'sensor_calibration' in results, \
        "Results must contain 'sensor_calibration'"
    assert 'cells' in results, \
        "Results must contain 'cells'"


def test_calibration_structure(results):
    """Calibration section must have correct keys."""
    cal = results['sensor_calibration']
    assert 'bias_B_minus_A' in cal, "Missing 'bias_B_minus_A'"
    assert 'bias_C_minus_A' in cal, "Missing 'bias_C_minus_A'"
    for key in ['bias_B_minus_A', 'bias_C_minus_A']:
        assert 'dx' in cal[key], f"Missing 'dx' in {key}"
        assert 'dy' in cal[key], f"Missing 'dy' in {key}"
        assert isinstance(cal[key]['dx'], (int, float)), \
            f"{key}.dx must be numeric"
        assert isinstance(cal[key]['dy'], (int, float)), \
            f"{key}.dy must be numeric"


def test_cells_structure(results):
    """Each cell must have required fields with correct types."""
    for cell in results['cells']:
        assert 'cell_id' in cell, "Each cell must have 'cell_id'"
        assert 'passed' in cell, "Each cell must have 'passed'"
        assert 'defects' in cell, "Each cell must have 'defects'"
        assert isinstance(cell['passed'], bool), "'passed' must be boolean"
        assert isinstance(cell['defects'], list), "'defects' must be a list"
        for defect in cell['defects']:
            assert 'defect_type' in defect
            assert 'theta' in defect
            assert 'z' in defect
            assert defect['defect_type'] in [1, 2, 3], \
                f"defect_type must be 1, 2, or 3, got {defect['defect_type']}"


def test_calibration_bias_B(results):
    """Estimated bias B-A must be within tolerance."""
    cal = results['sensor_calibration']['bias_B_minus_A']
    dx_err = abs(cal['dx'] - TRUE_BIAS_B_MINUS_A[0])
    dy_err = abs(cal['dy'] - TRUE_BIAS_B_MINUS_A[1])
    assert dx_err < CALIBRATION_TOLERANCE, \
        f"bias_B_minus_A dx error: {dx_err:.6f} >= {CALIBRATION_TOLERANCE}"
    assert dy_err < CALIBRATION_TOLERANCE, \
        f"bias_B_minus_A dy error: {dy_err:.6f} >= {CALIBRATION_TOLERANCE}"


def test_calibration_bias_C(results):
    """Estimated bias C-A must be within tolerance."""
    cal = results['sensor_calibration']['bias_C_minus_A']
    dx_err = abs(cal['dx'] - TRUE_BIAS_C_MINUS_A[0])
    dy_err = abs(cal['dy'] - TRUE_BIAS_C_MINUS_A[1])
    assert dx_err < CALIBRATION_TOLERANCE, \
        f"bias_C_minus_A dx error: {dx_err:.6f} >= {CALIBRATION_TOLERANCE}"
    assert dy_err < CALIBRATION_TOLERANCE, \
        f"bias_C_minus_A dy error: {dy_err:.6f} >= {CALIBRATION_TOLERANCE}"


def test_all_cells_present(results):
    """All 12 cells must appear in results."""
    cell_ids = {c['cell_id'] for c in results['cells']}
    expected = set(range(NUM_CELLS))
    assert cell_ids == expected, \
        f"Expected cells {expected}, got {cell_ids}"


def test_pass_fail_accuracy(results, ground_truth):
    """Pass/fail classification must be correct for every cell."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        cid = gt['cell_id']
        assert cid in result_map, f"Cell {cid} missing from results"
        assert result_map[cid]['passed'] == gt['passed'], \
            f"Cell {cid}: expected passed={gt['passed']}, got {result_map[cid]['passed']}"


def test_clean_cells_no_defects(results, ground_truth):
    """Clean cells must report zero defects (seam rejection)."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        if gt['passed']:
            cid = gt['cell_id']
            n = len(result_map[cid]['defects'])
            assert n == 0, \
                f"Cell {cid} is clean but {n} defect(s) reported (seam misclassified?)"


def test_defect_count_per_cell(results, ground_truth):
    """Defective cells must report the correct number of defects."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        if not gt['passed']:
            cid = gt['cell_id']
            expected = len(gt['defects'])
            actual = len(result_map[cid]['defects'])
            assert actual == expected, \
                f"Cell {cid}: expected {expected} defect(s), got {actual}"


def test_defect_type_classification(results, ground_truth):
    """Defect types must be correctly classified for each cell."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        if not gt['passed']:
            cid = gt['cell_id']
            gt_types = sorted([d['defect_type'] for d in gt['defects']])
            res_types = sorted([d['defect_type'] for d in result_map[cid]['defects']])
            assert gt_types == res_types, \
                f"Cell {cid}: expected types {gt_types}, got {res_types}"


def test_defect_theta_accuracy(results, ground_truth):
    """Defect theta must be within tolerance of ground truth."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        if not gt['passed']:
            cid = gt['cell_id']
            for gt_d in gt['defects']:
                gt_type = gt_d['defect_type']
                gt_theta = gt_d['theta']
                matching = [d for d in result_map[cid]['defects']
                            if d['defect_type'] == gt_type]
                assert len(matching) > 0, \
                    f"Cell {cid}: no defect of type {gt_type} found"
                best = min(angular_distance(d['theta'], gt_theta)
                           for d in matching)
                assert best < THETA_TOLERANCE, \
                    f"Cell {cid} type {gt_type}: theta error {best:.4f} " \
                    f"exceeds tolerance {THETA_TOLERANCE}"


def test_defect_z_accuracy(results, ground_truth):
    """Defect z coordinate must be within tolerance of ground truth."""
    result_map = {c['cell_id']: c for c in results['cells']}
    for gt in ground_truth:
        if not gt['passed']:
            cid = gt['cell_id']
            for gt_d in gt['defects']:
                gt_type = gt_d['defect_type']
                gt_z = gt_d['z']
                matching = [d for d in result_map[cid]['defects']
                            if d['defect_type'] == gt_type]
                assert len(matching) > 0, \
                    f"Cell {cid}: no defect of type {gt_type} found"
                best = min(abs(d['z'] - gt_z) for d in matching)
                assert best < Z_TOLERANCE, \
                    f"Cell {cid} type {gt_type}: z error {best:.6f} " \
                    f"exceeds tolerance {Z_TOLERANCE}"
