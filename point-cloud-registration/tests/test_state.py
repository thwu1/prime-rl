
"""
Functional verification of point cloud registration pipeline.

Tests verify:
1. Output SQLite database schema correctness (table, columns, completeness)
2. Transformation structural validity (rotation orthogonality, determinant)
3. Alignment quality via trimmed nearest-neighbor RMS distance
4. Bidirectional consistency of the recovered transformation
No ground truth transformation parameters are stored in this file.
"""

import os
import sqlite3

import numpy as np
import pytest

SCANS_DB = "/app/scans.db"
RESULTS_DB = "/app/results.db"

# ---------------------------------------------------------------------------
# SQLite I/O helpers
# ---------------------------------------------------------------------------


def _get_scan_names():
    conn = sqlite3.connect(SCANS_DB)
    c = conn.cursor()
    c.execute("SELECT name FROM scans ORDER BY id")
    names = [row[0] for row in c.fetchall()]
    conn.close()
    return names


def _load_source(name):
    conn = sqlite3.connect(SCANS_DB)
    c = conn.cursor()
    c.execute(
        "SELECT sp.x, sp.y, sp.z FROM source_points sp "
        "JOIN scans s ON sp.scan_id = s.id "
        "WHERE s.name = ? ORDER BY sp.point_idx",
        (name,),
    )
    pts = np.array(c.fetchall(), dtype=np.float64)
    conn.close()
    return pts


def _load_target(name):
    conn = sqlite3.connect(SCANS_DB)
    c = conn.cursor()
    c.execute(
        "SELECT tp.x, tp.y, tp.z FROM target_points tp "
        "JOIN scans s ON tp.scan_id = s.id "
        "WHERE s.name = ? ORDER BY tp.point_idx",
        (name,),
    )
    pts = np.array(c.fetchall(), dtype=np.float64)
    conn.close()
    return pts


def _load_metadata(name):
    conn = sqlite3.connect(SCANS_DB)
    c = conn.cursor()
    c.execute(
        "SELECT noise_std, outlier_ratio, overlap_ratio FROM scans WHERE name = ?",
        (name,),
    )
    row = c.fetchone()
    conn.close()
    return {"noise_std": row[0], "outlier_ratio": row[1], "overlap_ratio": row[2]}


def _load_result(name):
    conn = sqlite3.connect(RESULTS_DB)
    c = conn.cursor()
    c.execute(
        "SELECT r11, r12, r13, r21, r22, r23, r31, r32, r33, "
        "tx, ty, tz, scale FROM transformations WHERE scenario = ?",
        (name,),
    )
    row = c.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"No result for scenario '{name}' in {RESULTS_DB}")
    R = np.array(
        [[row[0], row[1], row[2]],
         [row[3], row[4], row[5]],
         [row[6], row[7], row[8]]],
        dtype=np.float64,
    )
    t = np.array([row[9], row[10], row[11]], dtype=np.float64)
    s = float(row[12])
    return R, t, s


# ---------------------------------------------------------------------------
# Alignment metrics
# ---------------------------------------------------------------------------


def _nearest_neighbor_dists(A, B):
    """For each point in A, compute distance to nearest point in B."""
    dists_min = np.empty(len(A))
    chunk_size = 100
    for i in range(0, len(A), chunk_size):
        chunk = A[i : i + chunk_size]
        diff = chunk[:, None, :] - B[None, :, :]
        d = np.sqrt(np.sum(diff ** 2, axis=2))
        dists_min[i : i + chunk_size] = np.min(d, axis=1)
    return dists_min


def _trimmed_rms(dists, trim_frac):
    """Compute RMS of the best trim_frac fraction of distances."""
    n = max(1, int(len(dists) * trim_frac))
    sorted_d = np.sort(dists)[:n]
    return np.sqrt(np.mean(sorted_d ** 2))


_NAMES = _get_scan_names()


# ---------------------------------------------------------------------------
# Tests: output database schema
# ---------------------------------------------------------------------------


class TestDatabaseSchema:

    def test_results_db_exists(self):
        assert os.path.exists(RESULTS_DB), f"Results database not found: {RESULTS_DB}"

    def test_transformations_table_exists(self):
        conn = sqlite3.connect(RESULTS_DB)
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='transformations'"
        )
        result = c.fetchone()
        conn.close()
        assert result is not None, "Table 'transformations' not found in results.db"

    def test_required_columns(self):
        conn = sqlite3.connect(RESULTS_DB)
        c = conn.cursor()
        c.execute("PRAGMA table_info(transformations)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        expected = {
            "scenario", "r11", "r12", "r13", "r21", "r22", "r23",
            "r31", "r32", "r33", "tx", "ty", "tz", "scale",
        }
        missing = expected - cols
        assert not missing, f"Missing columns in transformations table: {missing}"

    @pytest.mark.parametrize("name", _NAMES)
    def test_scenario_present(self, name):
        conn = sqlite3.connect(RESULTS_DB)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM transformations WHERE scenario = ?", (name,)
        )
        count = c.fetchone()[0]
        conn.close()
        assert count == 1, f"Scenario '{name}' not found or duplicated in results.db"


# ---------------------------------------------------------------------------
# Tests: rotation matrix structural validity
# ---------------------------------------------------------------------------


class TestRotationStructure:

    @pytest.mark.parametrize("name", _NAMES)
    def test_orthogonality(self, name):
        R, _, _ = _load_result(name)
        np.testing.assert_allclose(
            R @ R.T, np.eye(3), atol=0.02,
            err_msg=f"R not orthogonal for {name}",
        )

    @pytest.mark.parametrize("name", _NAMES)
    def test_determinant_positive(self, name):
        R, _, _ = _load_result(name)
        det = np.linalg.det(R)
        assert abs(det - 1.0) < 0.02, (
            f"det(R)={det:.4f} for {name}, expected ~1.0"
        )


# ---------------------------------------------------------------------------
# Tests: scale is in a reasonable physical range
# ---------------------------------------------------------------------------


class TestScaleReasonable:

    @pytest.mark.parametrize("name", _NAMES)
    def test_scale_range(self, name):
        _, _, s = _load_result(name)
        assert 0.3 < s < 3.0, (
            f"Scale {s:.4f} outside reasonable range (0.3, 3.0)"
        )


# ---------------------------------------------------------------------------
# Tests: functional alignment quality
# ---------------------------------------------------------------------------


class TestAlignmentQuality:

    @pytest.mark.parametrize("name", _NAMES)
    def test_alignment(self, name):
        meta = _load_metadata(name)
        source = _load_source(name)
        target = _load_target(name)
        R, t, s = _load_result(name)

        # Apply transformation: target ≈ s * R @ source + t
        transformed = s * (source @ R.T) + t

        # Nearest-neighbor distances from transformed source to target
        dists = _nearest_neighbor_dists(transformed, target)

        # Trim fraction: use overlap ratio
        overlap = meta.get("overlap_ratio", 1.0)
        trim_frac = max(0.3, overlap)
        rms = _trimmed_rms(dists, trim_frac)

        # Threshold: scales with noise level
        noise = meta.get("noise_std", 0.0)
        threshold = max(0.05, 4.0 * max(noise, 0.005) + 0.01)

        assert rms < threshold, (
            f"Trimmed RMS alignment error {rms:.4f} exceeds threshold "
            f"{threshold:.4f} for scenario '{name}' "
            f"(noise={noise}, overlap={overlap}, trim={trim_frac:.2f})"
        )


# ---------------------------------------------------------------------------
# Tests: bidirectional alignment (target -> source) as consistency check
# ---------------------------------------------------------------------------


class TestBidirectionalConsistency:

    @pytest.mark.parametrize("name", _NAMES)
    def test_reverse_alignment(self, name):
        """Verify that applying the inverse transformation to the target
        also aligns well with the source. This catches degenerate solutions."""
        meta = _load_metadata(name)
        source = _load_source(name)
        target = _load_target(name)
        R, t, s = _load_result(name)

        # Inverse transformation: source ≈ (1/s) * R^T @ (target - t)
        inv_transformed = (1.0 / s) * ((target - t) @ R)

        dists = _nearest_neighbor_dists(inv_transformed, source)

        overlap = meta.get("overlap_ratio", 1.0)
        outlier_ratio = meta.get("outlier_ratio", 0.0)
        effective_inlier_frac = overlap * (1.0 - outlier_ratio)
        trim_frac = max(0.25, effective_inlier_frac * 0.9)
        rms = _trimmed_rms(dists, trim_frac)

        noise = meta.get("noise_std", 0.0)
        threshold = max(0.08, 5.0 * max(noise, 0.005) + 0.02)

        assert rms < threshold, (
            f"Reverse trimmed RMS {rms:.4f} exceeds threshold "
            f"{threshold:.4f} for scenario '{name}'"
        )
