"""Tests for camera registration mAA evaluation pipeline.

"""
import pytest
import numpy as np
import json
import os
import sqlite3
from itertools import combinations


# ── COLMAP format helpers ────────────────────────────────────────────


def _quat_to_rot(w, x, y, z):
    """Quaternion (w,x,y,z) to 3x3 rotation matrix."""
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z),
         2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
         2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x),
         1 - 2 * (x * x + y * y)],
    ])


def _parse_colmap_images(path):
    """Parse COLMAP images.txt → (rotations, translations, image_names)."""
    rotations, translations, names = [], [], []
    with open(path) as f:
        lines = f.readlines()
    # Strip comments; keep all data lines (including POINTS2D lines)
    data = [l.strip() for l in lines
            if l.strip() and not l.strip().startswith('#')]
    # COLMAP: pairs of lines — image data, then POINTS2D
    for i in range(0, len(data), 2):
        parts = data[i].split()
        qw, qx, qy, qz = map(float, parts[1:5])
        tx, ty, tz = map(float, parts[5:8])
        name = parts[9]
        R = _quat_to_rot(qw, qx, qy, qz)
        rotations.append(R)
        translations.append(np.array([tx, ty, tz]))
        names.append(name)
    return np.array(rotations), np.array(translations), names


# ── Reference: Horn's absolute orientation ───────────────────────────


def horn_absolute_orientation(p, q):
    """
    Horn's method: find s, R, t such that q ~ s*R*p + t.
    p, q: (N, 3). Returns (s, R, t) or (None, None, None).
    """
    N = p.shape[0]
    assert N >= 3
    p_bar = p.mean(axis=0)
    q_bar = q.mean(axis=0)
    p_c = p - p_bar
    q_c = q - q_bar

    M = p_c.T @ q_c / N

    xx, xy, xz = M[0, 0], M[0, 1], M[0, 2]
    yx, yy, yz = M[1, 0], M[1, 1], M[1, 2]
    zx, zy, zz = M[2, 0], M[2, 1], M[2, 2]

    N4 = np.array([
        [xx + yy + zz, yz - zy, zx - xz, xy - yx],
        [yz - zy, xx - yy - zz, xy + yx, zx + xz],
        [zx - xz, xy + yx, -xx + yy - zz, yz + zy],
        [xy - yx, zx + xz, yz + zy, -xx - yy + zz],
    ])

    vals, vecs = np.linalg.eigh(N4)
    quat = vecs[:, -1]
    w, x, y, z = quat

    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z),
         2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
         2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x),
         1 - 2 * (x * x + y * y)],
    ])

    num = np.sum(q_c * (R @ p_c.T).T)
    den = np.sum(p_c ** 2)
    if den < 1e-15 or num / den <= 0:
        return None, None, None
    s = num / den
    t = q_bar - s * R @ p_bar
    return s, R, t


def _register(pred, gt, threshold):
    """RANSAC-like registration via exhaustive triplet search."""
    N = len(pred)
    if N < 3:
        return 0
    best = 0
    for tri in combinations(range(N), 3):
        idx = list(tri)
        res = horn_absolute_orientation(pred[idx], gt[idx])
        if res[0] is None:
            continue
        s, R, t = res
        xf = s * (R @ pred.T).T + t
        err = np.linalg.norm(xf - gt, axis=1)
        inl = np.where(err < threshold)[0]
        ref_idx = np.unique(np.concatenate([idx, inl]))
        if len(ref_idx) >= 3:
            res2 = horn_absolute_orientation(pred[ref_idx], gt[ref_idx])
            if res2[0] is not None:
                s2, R2, t2 = res2
                xf2 = s2 * (R2 @ pred.T).T + t2
                err2 = np.linalg.norm(xf2 - gt, axis=1)
                cnt = int(np.sum(err2 < threshold))
            else:
                cnt = int(len(inl))
        else:
            cnt = int(len(inl))
        if cnt > best:
            best = cnt
    return best


def _reference_maa():
    """Compute reference mAA from COLMAP models + SQLite metadata."""
    conn = sqlite3.connect("/app/data/metadata.db")
    cur = conn.cursor()

    thresholds = json.loads(
        cur.execute(
            "SELECT value FROM eval_config WHERE key='thresholds'"
        ).fetchone()[0]
    )

    gt_rows = cur.execute(
        "SELECT scene_name, model_dir FROM reconstructions "
        "WHERE is_ground_truth=1"
    ).fetchall()
    gt_map = {row[0]: row[1] for row in gt_rows}

    pred_rows = cur.execute(
        "SELECT DISTINCT method_name FROM reconstructions "
        "WHERE is_ground_truth=0"
    ).fetchall()
    methods = [r[0] for r in pred_rows]

    scenes = list(gt_map.keys())

    result = {}
    for m in methods:
        accs_by_t = []
        for t in thresholds:
            scene_accs = []
            for sc in scenes:
                gt_dir = os.path.join("/app/data", gt_map[sc])
                gR, gT, g_names = _parse_colmap_images(
                    os.path.join(gt_dir, "images.txt"))

                row = cur.execute(
                    "SELECT model_dir FROM reconstructions "
                    "WHERE method_name=? AND scene_name=? "
                    "AND is_ground_truth=0",
                    (m, sc)
                ).fetchone()
                if row is None:
                    scene_accs.append(0.0)
                    continue
                pred_dir = os.path.join("/app/data", row[0])
                pR, pT, p_names = _parse_colmap_images(
                    os.path.join(pred_dir, "images.txt"))

                gc = np.array([-R.T @ T for R, T in zip(gR, gT)])
                pc = np.array([-R.T @ T for R, T in zip(pR, pT)])
                cnt = _register(pc, gc, t)
                scene_accs.append(cnt / len(gc))
            accs_by_t.append(float(np.mean(scene_accs)))
        maa = float(
            np.trapz(accs_by_t, thresholds)
            / (thresholds[-1] - thresholds[0])
        )
        result[m] = {"mAA": maa, "accs": accs_by_t}

    conn.close()
    return result, thresholds


# ── Tests: output format ─────────────────────────────────────────────


class TestResultsFormat:
    def test_file_exists(self):
        assert os.path.exists("/app/results.json"), \
            "results.json not found at /app/results.json"

    def test_valid_json(self):
        with open("/app/results.json") as f:
            json.load(f)

    def test_required_keys(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        assert "methods" in d
        assert "ranking" in d
        assert "thresholds" in d

    def test_all_methods_present(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        for m in ["method_a", "method_b", "method_c"]:
            assert m in d["methods"], f"Missing {m}"
            assert "mAA" in d["methods"][m], f"mAA missing for {m}"
            assert "accuracies" in d["methods"][m], \
                f"accuracies missing for {m}"

    def test_maa_in_range(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        for m in d["methods"]:
            v = d["methods"][m]["mAA"]
            assert 0.0 <= v <= 1.0, f"{m} mAA={v} out of [0,1]"

    def test_threshold_count(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        assert len(d["thresholds"]) == 7, "Expected 7 thresholds"
        for m in d["methods"]:
            assert len(d["methods"][m]["accuracies"]) == 7, \
                f"{m}: expected 7 accuracy entries"


# ── Tests: Horn's method sanity ──────────────────────────────────────


class TestHornMethod:

    def test_identity(self):
        np.random.seed(200)
        pts = np.random.randn(10, 3)
        s, R, t = horn_absolute_orientation(pts, pts.copy())
        assert abs(s - 1) < 1e-6
        assert np.allclose(R, np.eye(3), atol=1e-6)
        assert np.allclose(t, 0, atol=1e-6)

    def test_scale_and_translation(self):
        np.random.seed(201)
        p = np.random.randn(8, 3)
        q = 2.5 * p + np.array([1.0, -2.0, 3.0])
        s, R, t = horn_absolute_orientation(p, q)
        assert abs(s - 2.5) < 1e-5
        assert np.allclose(R, np.eye(3), atol=1e-5)
        assert np.allclose(t, [1, -2, 3], atol=1e-5)

    def test_rotation_90z(self):
        np.random.seed(202)
        p = np.random.randn(6, 3)
        Rz = np.array([[0.0, -1.0, 0.0],
                        [1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0]])
        q = (Rz @ p.T).T
        s, R, t = horn_absolute_orientation(p, q)
        assert abs(s - 1) < 1e-5
        assert np.allclose(R, Rz, atol=1e-5)
        assert np.allclose(t, 0, atol=1e-5)

    def test_full_similarity(self):
        np.random.seed(203)
        p = np.random.randn(10, 3)
        ax = np.array([1.0, 1.0, 1.0]) / np.sqrt(3)
        ang = np.pi / 4
        K = np.array([[0, -ax[2], ax[1]],
                       [ax[2], 0, -ax[0]],
                       [-ax[1], ax[0], 0]])
        Rt = np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)
        st, tt = 0.7, np.array([5.0, -3.0, 1.0])
        q = st * (Rt @ p.T).T + tt
        s, R, t = horn_absolute_orientation(p, q)
        assert abs(s - st) < 1e-4
        assert np.allclose(R, Rt, atol=1e-4)
        assert np.allclose(t, tt, atol=1e-4)


# ── Tests: mAA correctness ──────────────────────────────────────────


class TestMAAValues:

    def test_ranking_order(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        a = d["methods"]["method_a"]["mAA"]
        b = d["methods"]["method_b"]["mAA"]
        c = d["methods"]["method_c"]["mAA"]
        assert a > b, \
            f"method_a ({a:.4f}) should beat method_b ({b:.4f})"
        assert b > c, \
            f"method_b ({b:.4f}) should beat method_c ({c:.4f})"

    def test_ranking_list(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        assert d["ranking"][0] == "method_a", \
            f"Best should be method_a, got {d['ranking'][0]}"
        assert d["ranking"][-1] == "method_c", \
            f"Worst should be method_c, got {d['ranking'][-1]}"

    def test_method_a_high(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        assert d["methods"]["method_a"]["mAA"] > 0.80, \
            f"method_a mAA too low: {d['methods']['method_a']['mAA']}"

    def test_method_c_low(self):
        with open("/app/results.json") as f:
            d = json.load(f)
        assert d["methods"]["method_c"]["mAA"] < 0.65, \
            f"method_c mAA too high: {d['methods']['method_c']['mAA']}"

    def test_reference_comparison(self):
        """Compare agent output against independent reference."""
        ref, thresholds = _reference_maa()
        with open("/app/results.json") as f:
            d = json.load(f)
        for m in ["method_a", "method_b", "method_c"]:
            agent_v = d["methods"][m]["mAA"]
            ref_v = ref[m]["mAA"]
            assert abs(agent_v - ref_v) < 0.04, \
                (f"{m}: agent={agent_v:.4f} ref={ref_v:.4f} "
                 f"diff={abs(agent_v - ref_v):.4f}")

    def test_accuracy_monotonic(self):
        """Accuracy must be non-decreasing as threshold increases."""
        with open("/app/results.json") as f:
            d = json.load(f)
        ts = sorted(d["thresholds"])
        for m in d["methods"]:
            accs = d["methods"][m]["accuracies"]
            vals = [accs[str(t)] for t in ts]
            for i in range(1, len(vals)):
                assert vals[i] >= vals[i - 1] - 1e-6, \
                    f"{m}: accuracy not monotonic at t={ts[i]}"

    def test_auc_consistency(self):
        """Verify mAA equals normalized AUC of reported accuracies."""
        with open("/app/results.json") as f:
            d = json.load(f)
        ts = d["thresholds"]
        for m in d["methods"]:
            accs = [d["methods"][m]["accuracies"][str(t)] for t in ts]
            expected = float(
                np.trapz(accs, ts) / (ts[-1] - ts[0])
            )
            actual = d["methods"][m]["mAA"]
            assert abs(actual - expected) < 0.01, \
                f"{m}: mAA {actual:.4f} != AUC {expected:.4f}"


# ── Tests: camera center computation ────────────────────────────────


class TestCameraCenter:

    def test_center_formula(self):
        """Verify C = -R^T @ T for a known case."""
        R = np.array([[0.0, 0.0, 1.0],
                       [1.0, 0.0, 0.0],
                       [0.0, 1.0, 0.0]])
        T = np.array([1.0, 2.0, 3.0])
        C = -R.T @ T
        expected = np.array([-2.0, -3.0, -1.0])
        assert np.allclose(C, expected), f"C={C}, expected={expected}"

    def test_center_roundtrip(self):
        """Camera at origin: R=I, T=0 => C=0."""
        R = np.eye(3)
        T = np.zeros(3)
        C = -R.T @ T
        assert np.allclose(C, np.zeros(3))
