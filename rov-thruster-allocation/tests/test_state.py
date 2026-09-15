"""
Tests for ROV thruster fault diagnosis.

"""

import json
import os
import numpy as np
import pytest

DIAGNOSIS_PATH = "/app/diagnosis.json"
PARAM_PATH = "/app/config/frame.param"
ATOL = 1e-3
RTOL = 0.02

# Ground truth: correct thruster parameters (embedded as constants)
CORRECT_THRUSTERS = [
    {"id": 1, "position": [0.18, 0.15, 0.0], "direction": [0.7071068, -0.7071068, 0.0]},
    {"id": 2, "position": [0.18, -0.15, 0.0], "direction": [0.7071068, 0.7071068, 0.0]},
    {"id": 3, "position": [-0.20, 0.18, 0.0], "direction": [-0.7071068, -0.7071068, 0.0]},
    {"id": 4, "position": [-0.20, -0.18, 0.0], "direction": [-0.7071068, 0.7071068, 0.0]},
    {"id": 5, "position": [0.12, 0.16, 0.03], "direction": [0.0, 0.0, 1.0]},
    {"id": 6, "position": [0.12, -0.16, 0.03], "direction": [0.0, 0.0, 1.0]},
    {"id": 7, "position": [-0.14, 0.16, 0.03], "direction": [0.0, 0.0, 1.0]},
    {"id": 8, "position": [-0.14, -0.16, 0.03], "direction": [0.0, 0.0, 1.0]},
]

# Expected faults: thruster_id -> {field, incorrect, correct}
# These match the faulty values in frame.param
EXPECTED_FAULTS = {
    3: {"field": "direction",
        "incorrect": [0.707107, -0.707107, 0.0],
        "correct": [-0.7071068, -0.7071068, 0.0]},
    6: {"field": "position",
        "incorrect": [0.12, -0.25, 0.03],
        "correct": [0.12, -0.16, 0.03]},
    8: {"field": "direction",
        "incorrect": [0.258819, 0.0, 0.965926],
        "correct": [0.0, 0.0, 1.0]},
}

# Faulty thruster parameters (as stored in frame.param)
FAULTY_THRUSTERS = []
for t in CORRECT_THRUSTERS:
    ft = dict(t)
    if t["id"] in EXPECTED_FAULTS:
        fault = EXPECTED_FAULTS[t["id"]]
        ft[fault["field"]] = list(fault["incorrect"])
    FAULTY_THRUSTERS.append(ft)


def build_allocation_matrix(thrusters):
    """Build 6x8 TAM from thruster positions and directions."""
    n = len(thrusters)
    B = np.zeros((6, n))
    for i, t in enumerate(thrusters):
        pos = np.array(t["position"])
        d = np.array(t["direction"])
        B[0:3, i] = d
        B[3:6, i] = np.cross(pos, d)
    return B


@pytest.fixture(scope="module")
def diagnosis():
    assert os.path.exists(DIAGNOSIS_PATH), f"diagnosis.json not found at {DIAGNOSIS_PATH}"
    with open(DIAGNOSIS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def B_correct():
    return build_allocation_matrix(CORRECT_THRUSTERS)


@pytest.fixture(scope="module")
def B_faulty():
    return build_allocation_matrix(FAULTY_THRUSTERS)


class TestDiagnosisStructure:
    """Verify diagnosis.json has required keys and valid structure."""

    def test_file_exists(self):
        assert os.path.exists(DIAGNOSIS_PATH), "diagnosis.json must exist"

    def test_required_keys(self, diagnosis):
        required = [
            "faults", "corrected_allocation_matrix", "original_allocation_matrix",
            "corrected_condition_number", "original_condition_number",
            "corrected_rank", "controllability_restored",
        ]
        for key in required:
            assert key in diagnosis, f"Missing required key: {key}"

    def test_faults_is_list(self, diagnosis):
        assert isinstance(diagnosis["faults"], list)

    def test_matrix_shapes(self, diagnosis):
        cam = diagnosis["corrected_allocation_matrix"]
        oam = diagnosis["original_allocation_matrix"]
        assert len(cam) == 6 and all(len(r) == 8 for r in cam), "corrected matrix must be 6x8"
        assert len(oam) == 6 and all(len(r) == 8 for r in oam), "original matrix must be 6x8"


class TestFaultDetection:
    """Verify the correct faults were identified."""

    def test_fault_count(self, diagnosis):
        assert len(diagnosis["faults"]) == 3, \
            f"Expected exactly 3 faults, found {len(diagnosis['faults'])}"

    def test_fault_thruster_ids(self, diagnosis):
        found_ids = sorted([f["thruster_id"] for f in diagnosis["faults"]])
        expected_ids = sorted(EXPECTED_FAULTS.keys())
        assert found_ids == expected_ids, \
            f"Expected faults on thrusters {expected_ids}, found {found_ids}"

    def test_fault_fields(self, diagnosis):
        for fault in diagnosis["faults"]:
            tid = fault["thruster_id"]
            expected = EXPECTED_FAULTS[tid]
            assert fault["field"] == expected["field"], \
                f"Thruster {tid}: expected field '{expected['field']}', got '{fault['field']}'"

    def test_fault_incorrect_values(self, diagnosis):
        for fault in diagnosis["faults"]:
            tid = fault["thruster_id"]
            expected = EXPECTED_FAULTS[tid]
            np.testing.assert_allclose(
                fault["incorrect"], expected["incorrect"], atol=ATOL,
                err_msg=f"Thruster {tid}: incorrect value mismatch"
            )

    def test_fault_correct_values(self, diagnosis):
        for fault in diagnosis["faults"]:
            tid = fault["thruster_id"]
            expected = EXPECTED_FAULTS[tid]
            np.testing.assert_allclose(
                fault["correct"], expected["correct"], atol=ATOL,
                err_msg=f"Thruster {tid}: correct value mismatch"
            )


class TestAllocationMatrices:
    """Verify both allocation matrices are computed correctly."""

    def test_corrected_matrix(self, diagnosis, B_correct):
        result = np.array(diagnosis["corrected_allocation_matrix"])
        np.testing.assert_allclose(result, B_correct, atol=ATOL,
            err_msg="Corrected allocation matrix does not match expected")

    def test_original_matrix(self, diagnosis, B_faulty):
        result = np.array(diagnosis["original_allocation_matrix"])
        np.testing.assert_allclose(result, B_faulty, atol=ATOL,
            err_msg="Original allocation matrix does not match faulty frame config")

    def test_matrices_differ(self, diagnosis):
        cam = np.array(diagnosis["corrected_allocation_matrix"])
        oam = np.array(diagnosis["original_allocation_matrix"])
        assert not np.allclose(cam, oam, atol=1e-6), \
            "Corrected and original matrices should differ (faults exist)"

    def test_corrected_force_rows_unit(self, diagnosis):
        """Each column's force component (top 3 rows) should be a unit vector."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        for i in range(8):
            force = B[0:3, i]
            norm = np.linalg.norm(force)
            assert abs(norm - 1.0) < ATOL, \
                f"Column {i} force vector norm = {norm:.6f}, expected 1.0"

    def test_corrected_torque_rows_consistency(self, diagnosis):
        """Torque rows should equal cross(position, direction) for correct thrusters."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        for i, t in enumerate(CORRECT_THRUSTERS):
            pos = np.array(t["position"])
            d = np.array(t["direction"])
            expected_torque = np.cross(pos, d)
            np.testing.assert_allclose(B[3:6, i], expected_torque, atol=ATOL,
                err_msg=f"Torque mismatch for thruster {t['id']}")


class TestControllabilityMetrics:
    """Verify condition numbers, rank, and controllability assessment."""

    def test_corrected_condition_number(self, diagnosis, B_correct):
        expected = np.linalg.cond(B_correct)
        got = diagnosis["corrected_condition_number"]
        assert abs(got - expected) / expected < RTOL, \
            f"Corrected cond number: expected {expected:.4f}, got {got}"

    def test_original_condition_number(self, diagnosis, B_faulty):
        expected = np.linalg.cond(B_faulty)
        got = diagnosis["original_condition_number"]
        assert abs(got - expected) / expected < RTOL, \
            f"Original cond number: expected {expected:.4f}, got {got}"

    def test_corrected_rank(self, diagnosis, B_correct):
        expected = int(np.linalg.matrix_rank(B_correct))
        assert diagnosis["corrected_rank"] == expected, \
            f"Expected corrected rank {expected}, got {diagnosis['corrected_rank']}"

    def test_corrected_full_rank(self, diagnosis):
        assert diagnosis["corrected_rank"] == 6, \
            "Corrected system should have full rank (6 DOF)"

    def test_controllability_restored(self, diagnosis):
        assert diagnosis["controllability_restored"] is True, \
            "Controllability should be restored with corrections"


class TestPhysicalConsistency:
    """Cross-validate physical properties of the corrected system."""

    def test_horizontal_thrusters_no_heave(self, diagnosis):
        """Horizontal thrusters (1-4) should produce no vertical force."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        for i in range(4):
            assert abs(B[2, i]) < ATOL, \
                f"Horizontal thruster {i+1} should have zero Z-force, got {B[2, i]}"

    def test_vertical_thrusters_no_horizontal(self, diagnosis):
        """Vertical thrusters (5-8) should produce no horizontal force."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        for i in range(4, 8):
            assert abs(B[0, i]) < ATOL and abs(B[1, i]) < ATOL, \
                f"Vertical thruster {i+1} should have zero XY-force"

    def test_pinv_identity(self, diagnosis):
        """B @ pinv(B) should approximate I_6 for a full-rank corrected matrix."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        B_pinv = np.linalg.pinv(B)
        product = B @ B_pinv
        np.testing.assert_allclose(product, np.eye(6), atol=ATOL,
            err_msg="B_corrected @ pinv(B_corrected) should approximate I_6")

    def test_thruster3_direction_sign_flip(self, diagnosis):
        """Thruster 3 had an X-sign flip. Verify the corrected X is negative."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        assert B[0, 2] < -0.5, \
            f"Thruster 3 corrected X-direction should be negative, got {B[0, 2]}"

    def test_thruster8_direction_vertical(self, diagnosis):
        """Thruster 8 should be purely vertical after correction."""
        B = np.array(diagnosis["corrected_allocation_matrix"])
        assert abs(B[0, 7]) < ATOL, f"Thruster 8 X-force should be ~0, got {B[0, 7]}"
        assert abs(B[1, 7]) < ATOL, f"Thruster 8 Y-force should be ~0, got {B[1, 7]}"
        assert abs(B[2, 7] - 1.0) < ATOL, f"Thruster 8 Z-force should be ~1, got {B[2, 7]}"


class TestRounding:
    """Verify all floats are rounded to 6 decimal places."""

    def _check_rounded(self, obj, path=""):
        if isinstance(obj, float):
            rounded = round(obj, 6)
            assert abs(obj - rounded) < 1e-9, \
                f"Value at {path} not rounded to 6 decimals: {obj}"
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._check_rounded(item, f"{path}[{i}]")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._check_rounded(v, f"{path}.{k}")

    def test_matrices_rounded(self, diagnosis):
        self._check_rounded(diagnosis["corrected_allocation_matrix"], "corrected_matrix")
        self._check_rounded(diagnosis["original_allocation_matrix"], "original_matrix")

    def test_condition_numbers_rounded(self, diagnosis):
        self._check_rounded(diagnosis["corrected_condition_number"], "corrected_cond")
        self._check_rounded(diagnosis["original_condition_number"], "original_cond")

    def test_fault_values_rounded(self, diagnosis):
        for fault in diagnosis["faults"]:
            self._check_rounded(fault["incorrect"], f"fault_{fault['thruster_id']}_incorrect")
            self._check_rounded(fault["correct"], f"fault_{fault['thruster_id']}_correct")
