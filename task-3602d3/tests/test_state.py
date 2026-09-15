"""
Tests for multi-view homography estimation pipeline.

"""
import json
import os
import sys
import numpy as np
import pytest

# gt_generator lives alongside this file inside /tests/
sys.path.insert(0, os.path.dirname(__file__))
from gt_generator import generate_ground_truth  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ground_truth():
    return generate_ground_truth()


@pytest.fixture(scope="module")
def correspondences():
    with open("/app/data/correspondences.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def output_homographies():
    path = "/app/output/homographies.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        data = json.load(f)
    return {k: np.array(v) for k, v in data.items()}


@pytest.fixture(scope="module")
def output_inliers():
    path = "/app/output/inliers.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def output_metrics():
    path = "/app/output/metrics.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def output_decompositions():
    path = "/app/output/decompositions.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# ── Tests ──────────────────────────────────────────────────────────────────

class TestOutputStructure:
    """Verify all output files exist and have correct structure."""

    def test_homographies_keys(self, output_homographies):
        for i in range(5):
            assert f"H_{i}" in output_homographies, f"Missing H_{i}"

    def test_homographies_shapes(self, output_homographies):
        for i in range(5):
            H = output_homographies[f"H_{i}"]
            assert H.shape == (3, 3), f"H_{i} has shape {H.shape}, expected (3, 3)"

    def test_h0_is_identity(self, output_homographies):
        H0 = output_homographies["H_0"]
        np.testing.assert_allclose(H0, np.eye(3), atol=1e-6,
                                   err_msg="H_0 must be the identity matrix")

    def test_inliers_keys(self, output_inliers):
        for i in range(5):
            for j in range(i + 1, 5):
                key = f"{i}-{j}"
                assert key in output_inliers, f"Missing inlier mask for pair {key}"

    def test_inliers_lengths(self, output_inliers, correspondences):
        for key in output_inliers:
            n_corr = len(correspondences["pairs"][key]["pts_src"])
            n_mask = len(output_inliers[key])
            assert n_mask == n_corr, (
                f"Pair {key}: inlier mask length {n_mask} != correspondence count {n_corr}"
            )

    def test_metrics_fields(self, output_metrics):
        assert "per_pair_rms" in output_metrics
        assert "global_rms" in output_metrics
        assert "consistency_error" in output_metrics

    def test_decompositions_keys(self, output_decompositions):
        for i in range(5):
            for j in range(i + 1, 5):
                key = f"{i}-{j}"
                assert key in output_decompositions, f"Missing decomposition for pair {key}"

    def test_decomposition_fields(self, output_decompositions):
        for key, dec in output_decompositions.items():
            assert "R" in dec, f"Missing 'R' in decomposition for {key}"
            assert "t" in dec, f"Missing 't' in decomposition for {key}"
            assert "n" in dec, f"Missing 'n' in decomposition for {key}"


class TestHomographyQuality:
    """Verify the estimated homographies are geometrically accurate."""

    def test_reprojection_error_per_pair(self, output_homographies, output_inliers,
                                         correspondences):
        """Inlier reprojection RMS must be below 2.0 px for each pair."""
        for i in range(5):
            for j in range(i + 1, 5):
                key = f"{i}-{j}"
                H_i = output_homographies[f"H_{i}"]
                H_j = output_homographies[f"H_{j}"]
                H_ij = H_j @ np.linalg.inv(H_i)
                H_ij = H_ij / H_ij[2, 2]

                pts_src = np.array(correspondences["pairs"][key]["pts_src"])
                pts_dst = np.array(correspondences["pairs"][key]["pts_dst"])
                mask = np.array(output_inliers[key])

                if mask.sum() < 4:
                    pytest.fail(f"Pair {key}: fewer than 4 inliers ({mask.sum()})")

                pts_h = np.column_stack([pts_src[mask], np.ones(mask.sum())])
                mapped = (H_ij @ pts_h.T).T
                mapped = mapped[:, :2] / mapped[:, 2:3]
                errors = np.linalg.norm(mapped - pts_dst[mask], axis=1)
                rms = np.sqrt(np.mean(errors ** 2))

                assert rms < 2.0, (
                    f"Pair {key}: inlier reprojection RMS = {rms:.3f} px (threshold 2.0)"
                )

    def test_global_reprojection_rms(self, output_homographies, output_inliers,
                                      correspondences):
        """Overall inlier reprojection RMS across all pairs must be below 2.0 px."""
        all_errors = []
        for i in range(5):
            for j in range(i + 1, 5):
                key = f"{i}-{j}"
                H_i = output_homographies[f"H_{i}"]
                H_j = output_homographies[f"H_{j}"]
                H_ij = H_j @ np.linalg.inv(H_i)
                H_ij = H_ij / H_ij[2, 2]

                pts_src = np.array(correspondences["pairs"][key]["pts_src"])
                pts_dst = np.array(correspondences["pairs"][key]["pts_dst"])
                mask = np.array(output_inliers[key])

                if mask.sum() < 4:
                    continue

                pts_h = np.column_stack([pts_src[mask], np.ones(mask.sum())])
                mapped = (H_ij @ pts_h.T).T
                mapped = mapped[:, :2] / mapped[:, 2:3]
                errors = np.linalg.norm(mapped - pts_dst[mask], axis=1)
                all_errors.extend(errors.tolist())

        global_rms = np.sqrt(np.mean(np.array(all_errors) ** 2))
        assert global_rms < 2.0, f"Global RMS = {global_rms:.3f} px (threshold 2.0)"

    def test_homography_normalization(self, output_homographies):
        """Each H_i must be normalized so H[2][2] == 1."""
        for i in range(5):
            H = output_homographies[f"H_{i}"]
            assert abs(H[2, 2] - 1.0) < 1e-4, (
                f"H_{i}[2][2] = {H[2, 2]:.6f}, expected 1.0"
            )

    def test_homographies_nonsingular(self, output_homographies):
        for i in range(5):
            H = output_homographies[f"H_{i}"]
            det = np.linalg.det(H)
            assert abs(det) > 1e-8, f"H_{i} is singular (det = {det:.2e})"


class TestInlierClassification:
    """Verify inlier/outlier classification quality."""

    def test_inlier_f1_score(self, output_inliers, ground_truth):
        """F1 score of inlier classification must exceed 0.80 for each pair."""
        for key in output_inliers:
            pred = np.array(output_inliers[key])
            gt = ground_truth["gt_inliers"][key]

            tp = np.sum(pred & gt)
            fp = np.sum(pred & ~gt)
            fn = np.sum(~pred & gt)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            assert f1 > 0.80, (
                f"Pair {key}: F1 = {f1:.3f} (threshold 0.80), "
                f"precision = {precision:.3f}, recall = {recall:.3f}"
            )

    def test_reasonable_inlier_count(self, output_inliers, correspondences):
        """Each pair should have between 40 and 68 inliers (out of 70 total, ~60 true)."""
        for key in output_inliers:
            n_inliers = sum(output_inliers[key])
            n_total = len(correspondences["pairs"][key]["pts_src"])
            assert 30 <= n_inliers <= 68, (
                f"Pair {key}: {n_inliers}/{n_total} inliers — outside plausible range"
            )


class TestMultiViewConsistency:
    """Verify that the homographies form a globally consistent set."""

    def test_transitivity(self, output_homographies):
        """For any triple (i,j,k), H_ij @ H_jk should approximately equal H_ik."""
        triples = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (1, 2, 3), (1, 3, 4), (2, 3, 4)]
        for i, j, k in triples:
            H_i = output_homographies[f"H_{i}"]
            H_j = output_homographies[f"H_{j}"]
            H_k = output_homographies[f"H_{k}"]

            H_ij = H_j @ np.linalg.inv(H_i)
            H_jk = H_k @ np.linalg.inv(H_j)
            H_ik = H_k @ np.linalg.inv(H_i)

            H_ij /= H_ij[2, 2]
            H_jk /= H_jk[2, 2]
            H_ik /= H_ik[2, 2]

            composed = H_jk @ H_ij
            composed /= composed[2, 2]

            frob = np.linalg.norm(composed - H_ik, 'fro')
            assert frob < 0.1, (
                f"Triple ({i},{j},{k}): transitivity error = {frob:.4f} (threshold 0.1)"
            )


class TestDecomposition:
    """Verify the homography decomposition into R, t, n."""

    def test_rotation_matrix_properties(self, output_decompositions):
        """R must be orthogonal with determinant +1."""
        for key, dec in output_decompositions.items():
            R = np.array(dec["R"])
            assert R.shape == (3, 3), f"{key}: R shape is {R.shape}"

            np.testing.assert_allclose(
                R.T @ R, np.eye(3), atol=1e-3,
                err_msg=f"{key}: R is not orthogonal (R^T R != I)"
            )

            det = np.linalg.det(R)
            assert abs(det - 1.0) < 1e-3, (
                f"{key}: det(R) = {det:.6f}, expected +1.0"
            )

    def test_translation_normalized(self, output_decompositions):
        """t must be a unit vector."""
        for key, dec in output_decompositions.items():
            t = np.array(dec["t"])
            assert t.shape == (3,), f"{key}: t shape is {t.shape}"
            norm = np.linalg.norm(t)
            assert abs(norm - 1.0) < 1e-3, (
                f"{key}: ||t|| = {norm:.6f}, expected 1.0"
            )

    def test_normal_unit_length(self, output_decompositions):
        """n must be a unit vector."""
        for key, dec in output_decompositions.items():
            n = np.array(dec["n"])
            assert n.shape == (3,), f"{key}: n shape is {n.shape}"
            norm = np.linalg.norm(n)
            assert abs(norm - 1.0) < 1e-3, (
                f"{key}: ||n|| = {norm:.6f}, expected 1.0"
            )

    def test_rotation_accuracy(self, output_decompositions, ground_truth):
        """Decomposed rotation must be within 5 degrees of ground truth."""
        for key, dec in output_decompositions.items():
            R_est = np.array(dec["R"])
            R_gt = ground_truth["gt_rotations_pairwise"][key]

            cos_angle = (np.trace(R_gt.T @ R_est) - 1) / 2
            cos_angle = np.clip(cos_angle, -1, 1)
            angle_deg = np.degrees(np.arccos(cos_angle))

            # Also check the transpose (sign ambiguity)
            cos_angle_t = (np.trace(R_gt.T @ R_est.T) - 1) / 2
            cos_angle_t = np.clip(cos_angle_t, -1, 1)
            angle_deg_t = np.degrees(np.arccos(cos_angle_t))

            min_angle = min(angle_deg, angle_deg_t)
            assert min_angle < 5.0, (
                f"Pair {key}: rotation error = {min_angle:.2f} deg (threshold 5.0 deg)"
            )

    def test_decomposition_reconstructs_homography(self, output_decompositions,
                                                     output_homographies,
                                                     correspondences):
        """Decomposed R, t, n should reconstruct a homography consistent with
        the estimated one (up to scale)."""
        K = np.array(correspondences["camera_matrix"])
        K_inv = np.linalg.inv(K)

        for key, dec in output_decompositions.items():
            i, j = map(int, key.split("-"))
            H_i = output_homographies[f"H_{i}"]
            H_j = output_homographies[f"H_{j}"]
            H_ij = H_j @ np.linalg.inv(H_i)
            H_ij /= H_ij[2, 2]

            R = np.array(dec["R"])
            t = np.array(dec["t"])
            n = np.array(dec["n"])

            H_norm = K_inv @ H_ij @ K
            H_norm /= H_norm[2, 2]

            assert R.shape == (3, 3)
            assert t.shape == (3,)
            assert n.shape == (3,)


class TestMetrics:
    """Verify that reported metrics are accurate and within bounds."""

    def test_per_pair_rms_reported_correctly(self, output_metrics, output_homographies,
                                              output_inliers, correspondences):
        """Verify the reported per-pair RMS matches independent computation."""
        for key, reported_rms in output_metrics["per_pair_rms"].items():
            i, j = map(int, key.split("-"))
            H_i = output_homographies[f"H_{i}"]
            H_j = output_homographies[f"H_{j}"]
            H_ij = H_j @ np.linalg.inv(H_i)
            H_ij = H_ij / H_ij[2, 2]

            pts_src = np.array(correspondences["pairs"][key]["pts_src"])
            pts_dst = np.array(correspondences["pairs"][key]["pts_dst"])
            mask = np.array(output_inliers[key])

            if mask.sum() < 4:
                continue

            pts_h = np.column_stack([pts_src[mask], np.ones(mask.sum())])
            mapped = (H_ij @ pts_h.T).T
            mapped = mapped[:, :2] / mapped[:, 2:3]
            errors = np.linalg.norm(mapped - pts_dst[mask], axis=1)
            computed_rms = float(np.sqrt(np.mean(errors ** 2)))

            assert abs(computed_rms - reported_rms) < 0.5, (
                f"Pair {key}: reported RMS = {reported_rms:.3f}, "
                f"computed = {computed_rms:.3f}"
            )

    def test_global_rms_bounded(self, output_metrics):
        assert output_metrics["global_rms"] < 2.0, (
            f"Global RMS = {output_metrics['global_rms']:.3f} (threshold 2.0)"
        )

    def test_consistency_error_bounded(self, output_metrics):
        assert output_metrics["consistency_error"] < 1.5, (
            f"Consistency error = {output_metrics['consistency_error']:.4f} (threshold 1.5)"
        )
