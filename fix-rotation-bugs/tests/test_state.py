
"""
Tests for the rotation pipeline audit task.

Verifies:
1. audit_report.json has correct structure and accurate bug identification
2. rotation_service.py is standalone and produces correct results
3. pipeline_fixed.json routes to correct backends
"""

import json
import os
import re
import sys

sys.path.insert(0, '/app')

import numpy as np
import pytest


# Ground truth: which libraries are flawed for each function
EXPECTED_FLAWED = {
    "quaternion_to_matrix": {"beta"},
    "matrix_to_quaternion": {"alpha", "gamma"},
    "axis_angle_to_matrix": {"gamma"},
    "matrix_to_euler_angles": {"beta"},
    "geodesic_distance": {"alpha"},
    "slerp": {"gamma"},
}

EXPECTED_CORRECT = {
    fn: {"alpha", "beta", "gamma"} - flawed
    for fn, flawed in EXPECTED_FLAWED.items()
}

ALL_FUNCTIONS = list(EXPECTED_FLAWED.keys())

ALL_REQUIRED_EXPORTS = [
    "quaternion_to_matrix", "matrix_to_quaternion",
    "axis_angle_to_matrix", "matrix_to_axis_angle",
    "axis_angle_to_quaternion", "quaternion_to_axis_angle",
    "euler_angles_to_matrix", "matrix_to_euler_angles",
    "geodesic_distance", "slerp",
    "standardize_quaternion", "random_rotation_matrix",
    "rotation_6d_to_matrix", "matrix_to_rotation_6d",
]


# ============================================================
# Tests for audit_report.json
# ============================================================

class TestAuditReport:

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/audit_report.json"
        assert os.path.exists(path), "audit_report.json not found at /app/audit_report.json"
        with open(path) as f:
            self.report = json.load(f)

    def test_has_bug_analysis(self):
        assert "bug_analysis" in self.report, "Missing 'bug_analysis' key"
        ba = self.report["bug_analysis"]
        for fn in ALL_FUNCTIONS:
            assert fn in ba, f"bug_analysis missing '{fn}'"
            entry = ba[fn]
            for key in ["correct_libraries", "flawed_libraries",
                        "root_cause", "affected_categories"]:
                assert key in entry, f"bug_analysis['{fn}'] missing '{key}'"

    def test_has_propagation_analysis(self):
        assert "propagation_analysis" in self.report, \
            "Missing 'propagation_analysis' key"
        pa = self.report["propagation_analysis"]
        assert isinstance(pa, dict) and len(pa) >= 1, \
            "propagation_analysis should be a non-empty dict"
        for label, desc in pa.items():
            assert isinstance(desc, str) and len(desc) >= 30, \
                f"propagation_analysis['{label}'] too short"

    def test_has_pipeline_issues(self):
        assert "pipeline_issues" in self.report, \
            "Missing 'pipeline_issues' key"
        pi = self.report["pipeline_issues"]
        for fn in ALL_FUNCTIONS:
            assert fn in pi, f"pipeline_issues missing '{fn}'"
            assert isinstance(pi[fn], str) and len(pi[fn]) >= 10, \
                f"pipeline_issues['{fn}'] too short"

    def test_flawed_identification(self):
        """Verify flawed libraries are correctly identified for each function."""
        ba = self.report["bug_analysis"]
        for fn in ALL_FUNCTIONS:
            identified = set(ba[fn]["flawed_libraries"])
            expected = EXPECTED_FLAWED[fn]
            assert identified == expected, (
                f"{fn}: expected flawed={expected}, got={identified}"
            )

    def test_correct_identification(self):
        """Verify correct libraries are correctly identified for each function."""
        ba = self.report["bug_analysis"]
        for fn in ALL_FUNCTIONS:
            identified = set(ba[fn]["correct_libraries"])
            expected = EXPECTED_CORRECT[fn]
            assert identified == expected, (
                f"{fn}: expected correct={expected}, got={identified}"
            )

    def test_root_cause_quality(self):
        """Root cause must be substantive (>= 50 chars)."""
        ba = self.report["bug_analysis"]
        for fn in ALL_FUNCTIONS:
            rc = ba[fn]["root_cause"]
            assert isinstance(rc, str) and len(rc) >= 50, (
                f"{fn}: root_cause must be >= 50 chars, got {len(rc) if isinstance(rc, str) else 'non-string'}"
            )

    def test_affected_categories_nonempty(self):
        ba = self.report["bug_analysis"]
        for fn in ALL_FUNCTIONS:
            cats = ba[fn]["affected_categories"]
            assert isinstance(cats, list) and len(cats) >= 1, (
                f"{fn}: affected_categories must be a non-empty list"
            )


# ============================================================
# Tests for rotation_service.py (standalone corrected library)
# ============================================================

class TestRotationService:

    @pytest.fixture(autouse=True)
    def load_lib(self):
        svc_path = "/app/rotation_service.py"
        assert os.path.exists(svc_path), \
            "rotation_service.py not found at /app/rotation_service.py"

        # Verify standalone: no imports from lib_alpha/beta/gamma
        with open(svc_path) as f:
            source = f.read()
        if re.search(r'(?:import|from)\s+lib_(?:alpha|beta|gamma)', source):
            pytest.fail(
                "rotation_service.py must be standalone; "
                "found import from lib_alpha, lib_beta, or lib_gamma"
            )

        # Import the module
        if 'rotation_service' in sys.modules:
            del sys.modules['rotation_service']
        import rotation_service
        self.lib = rotation_service

    def test_api_completeness(self):
        """Check that all 14 required functions are exported."""
        for name in ALL_REQUIRED_EXPORTS:
            assert hasattr(self.lib, name), \
                f"rotation_service.py missing function: {name}"

    # -- quaternion_to_matrix tests --

    def test_q2m_identity(self):
        q = np.array([1.0, 0.0, 0.0, 0.0])
        R = self.lib.quaternion_to_matrix(q)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_q2m_120_around_111(self):
        """120-degree rotation around (1,1,1)/sqrt(3).
        Catches R[0,2] sign bug present in Beta."""
        q = np.array([0.5, 0.5, 0.5, 0.5])
        R = self.lib.quaternion_to_matrix(q)
        expected = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
        np.testing.assert_allclose(R, expected, atol=1e-10)

    def test_q2m_produces_so3(self):
        """Generated matrices must be proper rotations (det=1, R^T R = I)."""
        np.random.seed(42)
        for _ in range(10):
            q = np.random.randn(4)
            q /= np.linalg.norm(q)
            R = self.lib.quaternion_to_matrix(q)
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10)

    # -- matrix_to_quaternion tests --

    def test_m2q_identity(self):
        R = np.eye(3)
        q = self.lib.matrix_to_quaternion(R)
        np.testing.assert_allclose(q, [1, 0, 0, 0], atol=1e-6)

    def test_m2q_180_around_y(self):
        """180 deg around Y. Catches incomplete Shepperd (x-only fallback
        in Alpha fails here because m00 is not the largest diagonal element)."""
        R = np.diag([-1.0, 1.0, -1.0])
        q = self.lib.matrix_to_quaternion(R)
        assert np.isclose(abs(q[2]), 1.0, atol=1e-6), \
            f"Expected |q_y| near 1 for 180 deg around Y, got q={q}"

    def test_m2q_180_around_z(self):
        """180 deg around Z. Catches incomplete Shepperd."""
        R = np.diag([-1.0, -1.0, 1.0])
        q = self.lib.matrix_to_quaternion(R)
        assert np.isclose(abs(q[3]), 1.0, atol=1e-6), \
            f"Expected |q_z| near 1 for 180 deg around Z, got q={q}"

    def test_m2q_180_around_x(self):
        """180 deg around X. Catches z-only Shepperd fallback in Gamma."""
        R = np.diag([1.0, -1.0, -1.0])
        q = self.lib.matrix_to_quaternion(R)
        assert np.isclose(abs(q[1]), 1.0, atol=1e-6), \
            f"Expected |q_x| near 1 for 180 deg around X, got q={q}"

    # -- axis_angle_to_matrix tests --

    def test_aa2m_identity(self):
        aa = np.array([0.0, 0.0, 0.0])
        R = self.lib.axis_angle_to_matrix(aa)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

    def test_aa2m_180_around_y(self):
        """180 deg rotation. Catches (1+cos) coefficient bug in Gamma's
        Rodrigues formula (should be 1-cos)."""
        aa = np.array([0.0, np.pi, 0.0])
        R = self.lib.axis_angle_to_matrix(aa)
        expected = np.diag([-1.0, 1.0, -1.0])
        np.testing.assert_allclose(R, expected, atol=1e-10)

    def test_aa2m_60_around_z(self):
        angle = np.pi / 3
        aa = np.array([0.0, 0.0, angle])
        R = self.lib.axis_angle_to_matrix(aa)
        c, s = np.cos(angle), np.sin(angle)
        expected = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        np.testing.assert_allclose(R, expected, atol=1e-10)

    # -- matrix_to_euler_angles tests --

    def test_euler_roundtrip_xyz(self):
        """Euler XYZ roundtrip. Catches sign multiplier bug in Beta."""
        angles = np.array([0.3, 0.5, 0.7])
        R = self.lib.euler_angles_to_matrix(angles, "XYZ")
        recovered = self.lib.matrix_to_euler_angles(R, "XYZ")
        np.testing.assert_allclose(recovered, angles, atol=1e-10)

    def test_euler_roundtrip_zyx(self):
        angles = np.array([0.2, -0.4, 0.6])
        R = self.lib.euler_angles_to_matrix(angles, "ZYX")
        recovered = self.lib.matrix_to_euler_angles(R, "ZYX")
        np.testing.assert_allclose(recovered, angles, atol=1e-10)

    def test_euler_roundtrip_yzx(self):
        angles = np.array([-0.3, 0.4, 0.1])
        R = self.lib.euler_angles_to_matrix(angles, "YZX")
        recovered = self.lib.matrix_to_euler_angles(R, "YZX")
        np.testing.assert_allclose(recovered, angles, atol=1e-10)

    # -- geodesic_distance tests --

    def test_geodesic_zero(self):
        R = np.eye(3)
        d = self.lib.geodesic_distance(R, R)
        np.testing.assert_allclose(d, 0.0, atol=1e-12)

    def test_geodesic_90(self):
        """90 deg rotation. Catches (trace+1)/2 bug in Alpha
        (correct formula: (trace-1)/2)."""
        R1 = np.eye(3)
        R2 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
        d = self.lib.geodesic_distance(R1, R2)
        np.testing.assert_allclose(d, np.pi / 2, atol=1e-10)

    def test_geodesic_180(self):
        R1 = np.eye(3)
        R2 = np.diag([1.0, -1.0, -1.0])
        d = self.lib.geodesic_distance(R1, R2)
        np.testing.assert_allclose(d, np.pi, atol=1e-10)

    def test_geodesic_symmetry(self):
        np.random.seed(99)
        q1 = np.random.randn(4)
        q1 /= np.linalg.norm(q1)
        q2 = np.random.randn(4)
        q2 /= np.linalg.norm(q2)
        R1 = self.lib.quaternion_to_matrix(q1)
        R2 = self.lib.quaternion_to_matrix(q2)
        d12 = self.lib.geodesic_distance(R1, R2)
        d21 = self.lib.geodesic_distance(R2, R1)
        np.testing.assert_allclose(d12, d21, atol=1e-10)

    # -- slerp tests --

    def test_slerp_endpoints(self):
        q0 = np.array([1.0, 0.0, 0.0, 0.0])
        q1 = np.array([np.cos(np.pi / 4), np.sin(np.pi / 4), 0.0, 0.0])
        r0 = self.lib.slerp(q0, q1, 0.0)
        r1 = self.lib.slerp(q0, q1, 1.0)
        np.testing.assert_allclose(r0, q0, atol=1e-10)
        np.testing.assert_allclose(np.abs(r1), np.abs(q1), atol=1e-10)

    def test_slerp_shortest_path(self):
        """Negative dot product. Catches missing shortest-path check in Gamma.
        Without the check, SLERP takes the long arc and the midpoint becomes
        the identity quaternion instead of a 120-degree rotation."""
        q0 = np.array([0.5, 0.5, 0.5, 0.5])
        q1 = np.array([0.5, -0.5, -0.5, -0.5])
        mid = self.lib.slerp(q0, q1, 0.5)
        mid = mid / np.linalg.norm(mid)
        mid = self.lib.standardize_quaternion(mid)
        identity_q = np.array([1.0, 0.0, 0.0, 0.0])
        assert not np.allclose(mid, identity_q, atol=0.1), (
            f"SLERP took the long path: midpoint is near identity ({mid})"
        )

    # -- Full pipeline integration tests --

    def test_full_pipeline_roundtrip(self):
        """axis-angle -> quaternion -> matrix -> euler -> matrix -> 6d -> matrix.
        Exercises multiple conversions in sequence."""
        aa = np.array([0.5, 0.3, -0.4])
        q = self.lib.axis_angle_to_quaternion(aa)
        R1 = self.lib.quaternion_to_matrix(q)
        euler = self.lib.matrix_to_euler_angles(R1, "XYZ")
        R2 = self.lib.euler_angles_to_matrix(euler, "XYZ")
        d6 = self.lib.matrix_to_rotation_6d(R2)
        R3 = self.lib.rotation_6d_to_matrix(d6)
        np.testing.assert_allclose(R1, R3, atol=1e-6)

    def test_matrix_axis_angle_roundtrip(self):
        """matrix -> axis_angle -> matrix roundtrip.
        Tests the dependency chain through matrix_to_quaternion."""
        aa0 = np.array([0.3, -0.5, 0.7])
        R = self.lib.axis_angle_to_matrix(aa0)
        aa1 = self.lib.matrix_to_axis_angle(R)
        np.testing.assert_allclose(aa0, aa1, atol=1e-6)

    def test_random_rotation_valid(self):
        """random_rotation_matrix must produce valid SO(3) elements."""
        np.random.seed(123)
        for _ in range(5):
            R = self.lib.random_rotation_matrix()
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-10)
            np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-10)


# ============================================================
# Tests for pipeline_fixed.json
# ============================================================

class TestPipelineFixed:

    @pytest.fixture(autouse=True)
    def load_config(self):
        path = "/app/pipeline_fixed.json"
        assert os.path.exists(path), \
            "pipeline_fixed.json not found at /app/pipeline_fixed.json"
        with open(path) as f:
            self.config = json.load(f)

    def test_has_backends(self):
        assert "backends" in self.config, "Missing 'backends' key"
        for fn in ALL_FUNCTIONS:
            assert fn in self.config["backends"], \
                f"Missing backend routing for '{fn}'"

    def test_all_backends_correct(self):
        """Every function must route to a non-flawed backend."""
        for fn in ALL_FUNCTIONS:
            chosen = self.config["backends"][fn]
            assert chosen in EXPECTED_CORRECT[fn], (
                f"{fn}: routed to '{chosen}' which is flawed; "
                f"correct options: {EXPECTED_CORRECT[fn]}"
            )

    def test_has_conversion_chains(self):
        """Fixed config should preserve the conversion_chains structure."""
        assert "conversion_chains" in self.config, \
            "Missing 'conversion_chains' key"
        assert isinstance(self.config["conversion_chains"], dict)
