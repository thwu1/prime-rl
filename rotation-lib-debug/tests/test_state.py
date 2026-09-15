"""
Tests for rotation calibration pipeline.

Verifies:
- Rotation library bugs are fixed (roundtrip consistency, known values, determinants)
- SO(3) analysis functions work correctly (geodesic distance, SLERP, Karcher mean)
- Calibration report is correct (structure, ranking consistency, independent verification)
- Diagnostic plot is generated
"""


import json
import math
import os
import sys
import torch
import pytest

sys.path.insert(0, "/app")


# ──────────────────────────────────────────────
# Section 1: Rotation library bug-fix verification
# ──────────────────────────────────────────────

class TestRotationLibFixes:
    """Verify the bugs in rotation_lib.py have been fixed."""

    def test_matrix_to_quaternion_roundtrip(self):
        """matrix_to_quaternion must produce correct roundtrip results."""
        from rotation_lib import random_rotation_matrices, matrix_to_quaternion, quaternion_to_matrix
        torch.manual_seed(42)
        R = random_rotation_matrices(50)
        q = matrix_to_quaternion(R)
        R_back = quaternion_to_matrix(q)
        max_err = (R - R_back).abs().max().item()
        assert max_err < 1e-5, f"Quaternion roundtrip error: {max_err:.8f}"

    def test_euler_angles_intrinsic_order(self):
        """euler_angles_to_matrix must produce correct intrinsic rotation."""
        from rotation_lib import euler_angles_to_matrix
        angles = torch.tensor([[math.pi / 2, math.pi / 4, 0.0]])
        R = euler_angles_to_matrix(angles, "XYZ")
        s = math.sqrt(2) / 2
        R_expected = torch.tensor([[[s, 0.0, s],
                                     [s, 0.0, -s],
                                     [0.0, 1.0, 0.0]]])
        assert torch.allclose(R, R_expected, atol=1e-5), \
            f"Euler XYZ forward:\ngot {R}\nexpected {R_expected}"

    def test_euler_roundtrip(self):
        """Euler angle roundtrip: R -> euler(XYZ) -> R for small rotations."""
        from rotation_lib import (
            euler_angles_to_matrix, matrix_to_euler_angles,
            axis_angle_to_quaternion, quaternion_to_matrix,
        )
        torch.manual_seed(123)
        aa = torch.randn(30, 3) * 0.3
        q = axis_angle_to_quaternion(aa)
        R = quaternion_to_matrix(q)
        euler = matrix_to_euler_angles(R, "XYZ")
        R_back = euler_angles_to_matrix(euler, "XYZ")
        max_err = (R - R_back).abs().max().item()
        assert max_err < 1e-4, f"Euler roundtrip error: {max_err:.8f}"

    def test_rotation_6d_positive_det(self):
        """rotation_6d_to_matrix must produce det=+1 (proper rotations)."""
        from rotation_lib import random_rotation_matrices, matrix_to_rotation_6d, rotation_6d_to_matrix
        torch.manual_seed(99)
        R = random_rotation_matrices(30)
        d6 = matrix_to_rotation_6d(R)
        R_back = rotation_6d_to_matrix(d6)
        dets = torch.det(R_back)
        assert torch.allclose(dets, torch.ones_like(dets), atol=1e-5), \
            f"6D determinants: min={dets.min():.4f}, max={dets.max():.4f}"

    def test_rotation_6d_roundtrip(self):
        """6D roundtrip: R -> 6d -> R must reconstruct R."""
        from rotation_lib import random_rotation_matrices, matrix_to_rotation_6d, rotation_6d_to_matrix
        torch.manual_seed(99)
        R = random_rotation_matrices(30)
        d6 = matrix_to_rotation_6d(R)
        R_back = rotation_6d_to_matrix(d6)
        max_err = (R - R_back).abs().max().item()
        assert max_err < 1e-5, f"6D roundtrip error: {max_err:.8f}"

    def test_axis_angle_roundtrip(self):
        """Axis-angle roundtrip: aa -> R -> aa must reconstruct aa."""
        from rotation_lib import axis_angle_to_matrix, matrix_to_axis_angle
        torch.manual_seed(77)
        aa = torch.randn(30, 3) * 0.5
        R = axis_angle_to_matrix(aa)
        aa_back = matrix_to_axis_angle(R)
        max_err = (aa - aa_back).abs().max().item()
        assert max_err < 1e-4, f"Axis-angle roundtrip error: {max_err:.8f}"


# ──────────────────────────────────────────────
# Section 2: Geodesic distance verification
# ──────────────────────────────────────────────

class TestGeodesicDistance:
    """Verify geodesic_distance implementation."""

    def test_self_distance_zero(self):
        """Distance from a rotation to itself must be 0."""
        from rotation_lib import random_rotation_matrices
        from rotation_analysis import geodesic_distance
        torch.manual_seed(55)
        # Use float64 to avoid numerical issues near identity relative rotation
        R = random_rotation_matrices(20, dtype=torch.float64)
        d = geodesic_distance(R, R)
        assert torch.allclose(d, torch.zeros(20, dtype=torch.float64), atol=1e-6), \
            f"Self-distance max: {d.max():.8f}"

    def test_known_90_degree(self):
        """Distance between identity and 90-deg Z rotation must be pi/2."""
        from rotation_analysis import geodesic_distance
        I = torch.eye(3).unsqueeze(0)
        c, s = math.cos(math.pi / 2), math.sin(math.pi / 2)
        Rz90 = torch.tensor([[[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]])
        d = geodesic_distance(I, Rz90)
        assert abs(d.item() - math.pi / 2) < 1e-5, \
            f"Expected pi/2={math.pi / 2:.6f}, got {d.item():.6f}"

    def test_known_180_degree(self):
        """Distance between identity and 180-deg X rotation must be pi."""
        from rotation_analysis import geodesic_distance
        I = torch.eye(3).unsqueeze(0)
        Rx180 = torch.tensor([[[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]])
        d = geodesic_distance(I, Rx180)
        assert abs(d.item() - math.pi) < 1e-4, \
            f"Expected pi={math.pi:.6f}, got {d.item():.6f}"

    def test_symmetry(self):
        """d(R1, R2) must equal d(R2, R1)."""
        from rotation_lib import random_rotation_matrices
        from rotation_analysis import geodesic_distance
        torch.manual_seed(33)
        R1 = random_rotation_matrices(20)
        R2 = random_rotation_matrices(20)
        d12 = geodesic_distance(R1, R2)
        d21 = geodesic_distance(R2, R1)
        assert torch.allclose(d12, d21, atol=1e-6), \
            f"Asymmetry: max diff = {(d12 - d21).abs().max():.8f}"


# ──────────────────────────────────────────────
# Section 3: SLERP verification
# ──────────────────────────────────────────────

class TestSlerp:
    """Verify SLERP implementation."""

    def test_endpoints(self):
        """slerp at t=0 must return q1, at t=1 must return q2 (up to sign)."""
        from rotation_lib import random_quaternions
        from rotation_analysis import slerp
        torch.manual_seed(10)
        q1 = random_quaternions(5)
        q2 = random_quaternions(5)
        r0 = slerp(q1, q2, 0.0)
        r1 = slerp(q1, q2, 1.0)
        diff0 = torch.min((r0 - q1).norm(dim=-1), (r0 + q1).norm(dim=-1))
        assert diff0.max() < 1e-5, f"slerp(q1,q2,0) != q1: err {diff0.max():.8f}"
        diff1 = torch.min((r1 - q2).norm(dim=-1), (r1 + q2).norm(dim=-1))
        assert diff1.max() < 1e-5, f"slerp(q1,q2,1) != q2: err {diff1.max():.8f}"

    def test_midpoint_equidistant(self):
        """SLERP midpoint must be equidistant from both endpoints."""
        from rotation_lib import random_quaternions, quaternion_to_matrix
        from rotation_analysis import slerp, geodesic_distance
        torch.manual_seed(20)
        q1 = random_quaternions(10)
        q2 = random_quaternions(10)
        qm = slerp(q1, q2, 0.5)
        R1 = quaternion_to_matrix(q1)
        R2 = quaternion_to_matrix(q2)
        Rm = quaternion_to_matrix(qm)
        d1m = geodesic_distance(R1, Rm)
        dm2 = geodesic_distance(Rm, R2)
        assert torch.allclose(d1m, dm2, atol=1e-4), \
            f"Midpoint not equidistant: max diff = {(d1m - dm2).abs().max():.6f}"

    def test_unit_quaternion_output(self):
        """SLERP output must always be a unit quaternion."""
        from rotation_lib import random_quaternions
        from rotation_analysis import slerp
        torch.manual_seed(30)
        q1 = random_quaternions(10)
        q2 = random_quaternions(10)
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            r = slerp(q1, q2, t)
            norms = r.norm(dim=-1)
            assert torch.allclose(norms, torch.ones_like(norms), atol=1e-5), \
                f"Non-unit at t={t}: norms={norms.tolist()}"

    def test_antipodal_no_nan(self):
        """SLERP must not produce NaN for antipodal quaternions."""
        from rotation_analysis import slerp
        q = torch.tensor([[1.0, 0.0, 0.0, 0.0]])
        neg_q = -q
        r = slerp(q, neg_q, 0.5)
        assert not torch.isnan(r).any(), "SLERP produced NaN for antipodal inputs"
        assert torch.allclose(r.norm(dim=-1), torch.ones(1), atol=1e-5), \
            "SLERP antipodal result not unit quaternion"


# ──────────────────────────────────────────────
# Section 4: Karcher mean verification
# ──────────────────────────────────────────────

class TestKarcherMean:
    """Verify Karcher mean implementation."""

    def test_identical_quaternions(self):
        """Mean of N identical quaternions must equal that quaternion."""
        from rotation_lib import random_quaternions
        from rotation_analysis import karcher_mean
        torch.manual_seed(40)
        q = random_quaternions(1)
        qs = q.expand(20, -1).contiguous()
        m = karcher_mean(qs, max_iter=50)
        diff = torch.min((m - q[0]).norm(), (m + q[0]).norm())
        assert diff < 1e-5, f"Mean of identical != input: diff={diff:.8f}"

    def test_convergence_small_perturbations(self):
        """Karcher mean of clustered rotations must converge near center."""
        from rotation_lib import random_quaternions, axis_angle_to_quaternion, quaternion_to_matrix, quaternion_multiply
        from rotation_analysis import karcher_mean, geodesic_distance
        torch.manual_seed(50)
        base_q = random_quaternions(1)
        base_R = quaternion_to_matrix(base_q)
        small_aa = torch.randn(30, 3) * 0.05
        qs = []
        for i in range(30):
            qi = axis_angle_to_quaternion(small_aa[i:i + 1])
            perturbed = quaternion_multiply(base_q, qi)
            qs.append(perturbed[0])
        qs_tensor = torch.stack(qs)
        mean_q = karcher_mean(qs_tensor, max_iter=200, tol=1e-10)
        mean_R = quaternion_to_matrix(mean_q.unsqueeze(0))
        d = geodesic_distance(mean_R, base_R)
        assert d.item() < 0.1, f"Karcher mean too far from center: d={d.item():.6f} rad"

    def test_mean_is_unit_quaternion(self):
        """Karcher mean output must be a unit quaternion."""
        from rotation_lib import random_quaternions
        from rotation_analysis import karcher_mean
        torch.manual_seed(60)
        qs = random_quaternions(15)
        m = karcher_mean(qs, max_iter=100)
        norm = m.norm().item()
        assert abs(norm - 1.0) < 1e-5, f"Karcher mean norm = {norm:.8f}"


# ──────────────────────────────────────────────
# Section 5: Calibration report verification
# ──────────────────────────────────────────────

class TestCalibrationReport:
    """Verify calibration report structure and correctness."""

    def test_report_exists(self):
        assert os.path.exists("/app/calibration_report.json"), \
            "calibration_report.json not found at /app/"

    def test_report_structure(self):
        """Report must have all required keys with correct types."""
        with open("/app/calibration_report.json") as f:
            report = json.load(f)

        assert "overall_mean_quaternion" in report, "Missing overall_mean_quaternion"
        assert isinstance(report["overall_mean_quaternion"], list)
        assert len(report["overall_mean_quaternion"]) == 4

        assert "sensor_rankings" in report, "Missing sensor_rankings"
        assert isinstance(report["sensor_rankings"], list)
        assert len(report["sensor_rankings"]) == 5

        assert "per_sensor_stats" in report, "Missing per_sensor_stats"
        assert isinstance(report["per_sensor_stats"], dict)
        assert len(report["per_sensor_stats"]) == 5

        for sid, stats in report["per_sensor_stats"].items():
            assert "mean_geodesic_distance" in stats, f"{sid}: missing mean_geodesic_distance"
            assert "max_geodesic_distance" in stats, f"{sid}: missing max_geodesic_distance"
            assert "individual_mean_quaternion" in stats, f"{sid}: missing individual_mean_quaternion"
            assert len(stats["individual_mean_quaternion"]) == 4, f"{sid}: quaternion not length 4"
            assert stats["mean_geodesic_distance"] >= 0, f"{sid}: negative mean distance"
            assert stats["max_geodesic_distance"] >= stats["mean_geodesic_distance"] - 1e-8, \
                f"{sid}: max < mean"

        assert "slerp_trajectory" in report, "Missing slerp_trajectory"
        traj = report["slerp_trajectory"]
        assert "from_sensor" in traj
        assert "to_sensor" in traj
        assert "quaternions" in traj

    def test_mean_is_unit_quaternion(self):
        """Overall mean quaternion must have unit norm."""
        with open("/app/calibration_report.json") as f:
            report = json.load(f)
        q = torch.tensor(report["overall_mean_quaternion"])
        assert abs(q.norm().item() - 1.0) < 1e-4, \
            f"Mean quaternion norm = {q.norm().item():.8f}"

    def test_ranking_consistency(self):
        """Rankings must be sorted by ascending mean geodesic distance."""
        with open("/app/calibration_report.json") as f:
            report = json.load(f)
        rankings = report["sensor_rankings"]
        stats = report["per_sensor_stats"]
        dists = [stats[s]["mean_geodesic_distance"] for s in rankings]
        for i in range(len(dists) - 1):
            assert dists[i] <= dists[i + 1] + 1e-8, \
                f"Ranking not sorted: {rankings[i]}={dists[i]:.6f} > {rankings[i + 1]}={dists[i + 1]:.6f}"

    def test_slerp_trajectory_valid(self):
        """SLERP trajectory must have correct length and unit quaternions."""
        with open("/app/calibration_report.json") as f:
            report = json.load(f)

        import tomllib
        with open("/app/analysis_config.toml", "rb") as cf:
            config = tomllib.load(cf)
        num_steps = config["slerp"]["num_steps"]

        traj = report["slerp_trajectory"]
        quats = traj["quaternions"]
        assert len(quats) == num_steps, \
            f"Expected {num_steps} SLERP steps, got {len(quats)}"

        for i, q in enumerate(quats):
            norm = sum(x ** 2 for x in q) ** 0.5
            assert abs(norm - 1.0) < 1e-4, \
                f"SLERP step {i} not unit: norm={norm:.6f}"

        # Endpoints must match best/worst sensor
        assert traj["from_sensor"] == report["sensor_rankings"][0], \
            f"from_sensor should be best: {traj['from_sensor']} vs {report['sensor_rankings'][0]}"
        assert traj["to_sensor"] == report["sensor_rankings"][-1], \
            f"to_sensor should be worst: {traj['to_sensor']} vs {report['sensor_rankings'][-1]}"

    def test_slerp_trajectory_endpoints_match_means(self):
        """SLERP first/last quaternions must match the per-sensor means."""
        with open("/app/calibration_report.json") as f:
            report = json.load(f)
        traj = report["slerp_trajectory"]
        stats = report["per_sensor_stats"]

        q_first = torch.tensor(traj["quaternions"][0])
        q_last = torch.tensor(traj["quaternions"][-1])
        q_best_mean = torch.tensor(stats[traj["from_sensor"]]["individual_mean_quaternion"])
        q_worst_mean = torch.tensor(stats[traj["to_sensor"]]["individual_mean_quaternion"])

        diff_first = torch.min((q_first - q_best_mean).norm(), (q_first + q_best_mean).norm())
        assert diff_first < 1e-3, \
            f"SLERP start doesn't match best sensor mean: diff={diff_first:.6f}"
        diff_last = torch.min((q_last - q_worst_mean).norm(), (q_last + q_worst_mean).norm())
        assert diff_last < 1e-3, \
            f"SLERP end doesn't match worst sensor mean: diff={diff_last:.6f}"

    def test_independent_verification(self):
        """Independently compute per-sensor distances and verify report values."""
        from rotation_lib import (
            quaternion_to_matrix, matrix_to_quaternion,
            axis_angle_to_quaternion, euler_angles_to_matrix,
            rotation_6d_to_matrix, standardize_quaternion,
        )
        from rotation_analysis import geodesic_distance, karcher_mean

        with open("/app/sensor_data.json") as f:
            sensor_data = json.load(f)
        with open("/app/calibration_report.json") as f:
            report = json.load(f)

        # Convert all measurements to quaternions
        all_quats = []
        sensor_quats = {}
        for sid, sinfo in sensor_data["sensors"].items():
            fmt = sinfo["format"]
            quats = []
            for m in sinfo["measurements"]:
                t = torch.tensor(m, dtype=torch.float32)
                if fmt == "quaternion":
                    q = standardize_quaternion(t.unsqueeze(0))[0]
                elif fmt == "axis_angle":
                    q = axis_angle_to_quaternion(t.unsqueeze(0))[0]
                elif fmt == "rotation_matrix":
                    R = t.reshape(3, 3).unsqueeze(0)
                    q = matrix_to_quaternion(R)[0]
                elif fmt.startswith("euler_"):
                    convention = fmt.split("_", 1)[1]
                    R = euler_angles_to_matrix(t.unsqueeze(0), convention)
                    q = matrix_to_quaternion(R)[0]
                elif fmt == "rotation_6d":
                    R = rotation_6d_to_matrix(t.unsqueeze(0))
                    q = matrix_to_quaternion(R)[0]
                else:
                    pytest.fail(f"Unknown format: {fmt}")
                q = standardize_quaternion(q.unsqueeze(0))[0]
                quats.append(q)
            sensor_quats[sid] = torch.stack(quats)
            all_quats.append(sensor_quats[sid])

        all_q = torch.cat(all_quats, dim=0)

        # Compute overall mean independently
        overall_mean = karcher_mean(all_q, max_iter=200, tol=1e-10)
        reported_mean = torch.tensor(report["overall_mean_quaternion"])
        diff = torch.min(
            (overall_mean - reported_mean).norm(),
            (overall_mean + reported_mean).norm(),
        )
        assert diff < 1e-3, f"Mean quaternion mismatch: diff={diff:.6f}"

        # Verify per-sensor mean geodesic distances
        overall_mean_R = quaternion_to_matrix(overall_mean.unsqueeze(0))[0]
        for sid in sensor_quats:
            Rs = quaternion_to_matrix(sensor_quats[sid])
            R_expanded = overall_mean_R.unsqueeze(0).expand_as(Rs)
            dists = geodesic_distance(Rs, R_expanded)
            computed_mean_dist = dists.mean().item()
            reported_mean_dist = report["per_sensor_stats"][sid]["mean_geodesic_distance"]
            assert abs(computed_mean_dist - reported_mean_dist) < 1e-2, \
                f"Sensor {sid} mean dist: computed={computed_mean_dist:.6f}, reported={reported_mean_dist:.6f}"


# ──────────────────────────────────────────────
# Section 6: Diagnostic plot verification
# ──────────────────────────────────────────────

class TestDiagnosticPlot:
    """Verify diagnostic plot was generated."""

    def test_plot_exists_and_valid(self):
        """sensor_diagnostic.png must exist with reasonable file size."""
        path = "/app/sensor_diagnostic.png"
        assert os.path.exists(path), f"{path} not found"
        size = os.path.getsize(path)
        assert size > 1000, f"Plot file too small ({size} bytes), probably invalid"
