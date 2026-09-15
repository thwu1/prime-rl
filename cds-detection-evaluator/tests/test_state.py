"""Test scene flow benchmark pipeline outputs.

Independently computes reference metrics from raw data and verifies
the agent's leaderboard.json and DuckDB database against them.
"""

import json
import math
import os
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

GT_DIR = Path("/app/ground_truth")
SUB_DIR = Path("/app/submissions")
LEADERBOARD_PATH = "/app/leaderboard.json"
DB_PATH = "/app/benchmark.duckdb"
EGO_POSES_PATH = "/app/ego_poses.json"

TOL = 5e-4
EPS = 1e-10
TIME_DELTA = 0.1
STRICT_THRESH = 0.05
RELAX_THRESH = 0.10

CATEGORY_MAP = {"Background": [0], "Foreground": [1, 2, 3, 4]}
SKIP_COMBO = ("Background", "Dynamic")
FLOW_COLS = ["flow_tx_m", "flow_ty_m", "flow_tz_m"]

EXPECTED_SUBSETS = [
    "Foreground/Dynamic/Close", "Foreground/Dynamic/Far",
    "Foreground/Static/Close", "Foreground/Static/Far",
    "Background/Static/Close", "Background/Static/Far",
]
EXPECTED_CM = ["Foreground/Dynamic", "Foreground/Static", "Background/Static"]
METRIC_NAMES = ["EPE", "Accuracy Strict", "Accuracy Relaxed", "Angle Error"]
MODEL_NAMES = ["alpha", "beta", "gamma", "delta"]

BETA_COL_MAP = {
    "pred_x": "flow_tx_m",
    "pred_y": "flow_ty_m",
    "pred_z": "flow_tz_m",
    "dynamic_flag": "is_dynamic",
}

DELTA_COL_MAP = {
    "dx": "flow_tx_m",
    "dy": "flow_ty_m",
    "dz": "flow_tz_m",
    "dynamic": "is_dynamic",
}


def _load_ego_poses():
    with open(EGO_POSES_PATH) as f:
        return json.load(f)


EGO_POSES = _load_ego_poses()


def _load_model_data(model_name):
    """Load and concatenate all valid points for a given model."""
    gts_all, preds_all, cats_all = [], [], []
    dyns_all, pdyns_all, closes_all = [], [], []

    for af in sorted(GT_DIR.rglob("*.feather")):
        rel = af.relative_to(GT_DIR)
        gd = pd.read_feather(af)

        if model_name == "alpha":
            pf = SUB_DIR / "alpha" / rel
            pp = pd.read_feather(pf)
        elif model_name == "beta":
            parts = rel.parts
            pf = SUB_DIR / "beta" / parts[0] / (parts[1].replace(".feather", ".parquet"))
            pp = pd.read_parquet(pf).rename(columns=BETA_COL_MAP)
        elif model_name == "gamma":
            with zipfile.ZipFile(SUB_DIR / "gamma.zip") as zf:
                pp = pd.read_feather(zf.open(rel.as_posix()))
        elif model_name == "delta":
            parts = rel.parts
            pf = SUB_DIR / "delta" / parts[0] / (parts[1].replace(".feather", ".csv"))
            pp = pd.read_csv(pf).rename(columns=DELTA_COL_MAP)
            pp["is_dynamic"] = pp["is_dynamic"].astype(bool)
            # Apply ego-motion compensation: subtract ego displacement
            log_id = parts[0]
            ts_str = parts[1].replace(".feather", "")
            ego_disp = EGO_POSES[log_id][ts_str]["ego_displacement_m"]
            pp["flow_tx_m"] = pp["flow_tx_m"] - ego_disp[0]
            pp["flow_ty_m"] = pp["flow_ty_m"] - ego_disp[1]
            pp["flow_tz_m"] = pp["flow_tz_m"] - ego_disp[2]
        else:
            raise ValueError(f"Unknown model: {model_name}")

        v = gd["is_valid"].to_numpy().astype(bool)
        gts_all.append(gd[FLOW_COLS].to_numpy().astype(np.float64)[v])
        preds_all.append(pp[FLOW_COLS].to_numpy().astype(np.float64)[v])
        cats_all.append(gd["category_indices"].to_numpy().astype(int)[v])
        dyns_all.append(gd["is_dynamic"].to_numpy().astype(bool)[v])
        pdyns_all.append(pp["is_dynamic"].to_numpy().astype(bool)[v])
        closes_all.append(gd["is_close"].to_numpy().astype(bool)[v])

    return (
        np.concatenate(gts_all),
        np.concatenate(preds_all),
        np.concatenate(cats_all),
        np.concatenate(dyns_all),
        np.concatenate(pdyns_all),
        np.concatenate(closes_all),
    )


def _compute_pointwise(gt, pred):
    """Compute per-point flow metrics independently."""
    diff = pred - gt
    epe = np.sqrt(np.sum(diff ** 2, axis=-1))

    gt_mag = np.sqrt(np.sum(gt ** 2, axis=-1))
    rel = epe / (gt_mag + EPS)
    acc_s = ((epe < STRICT_THRESH) | (rel < STRICT_THRESH)).astype(np.float64)
    acc_r = ((epe < RELAX_THRESH) | (rel < RELAX_THRESH)).astype(np.float64)

    gt4 = np.concatenate([gt, np.full((len(gt), 1), TIME_DELTA)], axis=1)
    p4 = np.concatenate([pred, np.full((len(pred), 1), TIME_DELTA)], axis=1)
    g_n = gt4 / np.sqrt(np.sum(gt4 ** 2, axis=-1, keepdims=True))
    p_n = p4 / np.sqrt(np.sum(p4 ** 2, axis=-1, keepdims=True))
    dot = np.sum(g_n * p_n, axis=1)
    angle = np.arccos(np.clip(dot, -1.0, 1.0))

    return epe, acc_s, acc_r, angle


def _subset_vals(epe, acc_s, acc_r, angle, mask):
    if mask.sum() == 0:
        return None
    return {
        "EPE": float(epe[mask].mean()),
        "Accuracy Strict": float(acc_s[mask].mean()),
        "Accuracy Relaxed": float(acc_r[mask].mean()),
        "Angle Error": float(angle[mask].mean()),
    }


def _compute_model_reference(model_name):
    """Compute full reference metrics for one model."""
    gt, pred, cat, dyn, pdyn, close = _load_model_data(model_name)
    epe, acc_s, acc_r, angle = _compute_pointwise(gt, pred)

    per_subset = {}
    per_cm = {}

    for cn, ci in CATEGORY_MAP.items():
        cm = np.isin(cat, ci)
        for mn, mf in [("Dynamic", True), ("Static", False)]:
            if (cn, mn) == SKIP_COMBO:
                continue
            mm = dyn == mf
            cmm = cm & mm
            per_cm[f"{cn}/{mn}"] = _subset_vals(epe, acc_s, acc_r, angle, cmm)
            for dn, df in [("Close", True), ("Far", False)]:
                dm = close == df
                per_subset[f"{cn}/{mn}/{dn}"] = _subset_vals(
                    epe, acc_s, acc_r, angle, cmm & dm
                )

    tp = int(np.logical_and(pdyn, dyn).sum())
    fp = int(np.logical_and(pdyn, ~dyn).sum())
    fn = int(np.logical_and(~pdyn, dyn).sum())
    dynamic_iou = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

    groups = ["Foreground/Dynamic", "Foreground/Static", "Background/Static"]
    epe_3way = float(np.mean([per_cm[g]["EPE"] for g in groups]))
    acc_s_3way = float(np.mean([per_cm[g]["Accuracy Strict"] for g in groups]))
    acc_r_3way = float(np.mean([per_cm[g]["Accuracy Relaxed"] for g in groups]))
    angle_3way = float(np.mean([per_cm[g]["Angle Error"] for g in groups]))

    epe_score = max(0.0, 1.0 - epe_3way / 2.0)
    acc_score = (acc_s_3way + acc_r_3way) / 2.0
    angle_score = max(0.0, 1.0 - angle_3way / math.pi)
    csfs = dynamic_iou * (epe_score + acc_score + angle_score) / 3.0

    return {
        "per_subset": per_subset,
        "per_class_motion": per_cm,
        "dynamic_iou": dynamic_iou,
        "epe_3way": epe_3way,
        "accuracy_strict_3way": acc_s_3way,
        "accuracy_relaxed_3way": acc_r_3way,
        "angle_error_3way": angle_3way,
        "csfs": csfs,
    }


@pytest.fixture(scope="module")
def reference():
    """Compute reference metrics for all models from raw data."""
    return {m: _compute_model_reference(m) for m in MODEL_NAMES}


@pytest.fixture(scope="module")
def leaderboard():
    """Load the agent's leaderboard output."""
    assert os.path.exists(LEADERBOARD_PATH), (
        f"Leaderboard not found at {LEADERBOARD_PATH}"
    )
    with open(LEADERBOARD_PATH) as f:
        return json.load(f)


def _get_entry(leaderboard, model):
    """Find a model's entry in the leaderboard ranking."""
    for e in leaderboard["ranking"]:
        if e["model"] == model:
            return e
    pytest.fail(f"Model '{model}' not found in leaderboard ranking")


# ───────────────────────────────────────────────────────
# Structure tests
# ───────────────────────────────────────────────────────

class TestLeaderboardStructure:

    def test_has_ranking(self, leaderboard):
        assert "ranking" in leaderboard, "Missing 'ranking' key"

    def test_ranking_count(self, leaderboard):
        assert len(leaderboard["ranking"]) == 4, (
            f"Expected 4 entries, got {len(leaderboard['ranking'])}"
        )

    @pytest.mark.parametrize("field", [
        "rank", "model", "csfs", "dynamic_iou", "epe_3way",
        "accuracy_strict_3way", "accuracy_relaxed_3way", "angle_error_3way",
        "per_subset", "per_class_motion",
    ])
    def test_entry_has_field(self, leaderboard, field):
        for entry in leaderboard["ranking"]:
            assert field in entry, (
                f"Missing field '{field}' in entry for model {entry.get('model', '?')}"
            )

    def test_all_models_present(self, leaderboard):
        models = {e["model"] for e in leaderboard["ranking"]}
        assert models == set(MODEL_NAMES), (
            f"Expected models {set(MODEL_NAMES)}, got {models}"
        )

    def test_no_excluded_subsets(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in entry.get("per_subset", {}):
                assert not key.startswith("Background/Dynamic"), (
                    f"Excluded subset '{key}' present in {entry['model']}"
                )

    def test_no_excluded_class_motion(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in entry.get("per_class_motion", {}):
                assert key != "Background/Dynamic", (
                    f"Excluded class/motion 'Background/Dynamic' in {entry['model']}"
                )

    def test_all_subsets_present(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in EXPECTED_SUBSETS:
                assert key in entry["per_subset"], (
                    f"Missing subset '{key}' in {entry['model']}"
                )

    def test_all_class_motion_present(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in EXPECTED_CM:
                assert key in entry["per_class_motion"], (
                    f"Missing class/motion '{key}' in {entry['model']}"
                )

    def test_all_metrics_in_subsets(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in EXPECTED_SUBSETS:
                for m in METRIC_NAMES:
                    assert m in entry["per_subset"][key], (
                        f"Missing metric '{m}' in {entry['model']}/{key}"
                    )

    def test_all_metrics_in_class_motion(self, leaderboard):
        for entry in leaderboard["ranking"]:
            for key in EXPECTED_CM:
                for m in METRIC_NAMES:
                    assert m in entry["per_class_motion"][key], (
                        f"Missing metric '{m}' in {entry['model']}/{key}"
                    )

    def test_ranks_sequential(self, leaderboard):
        ranks = sorted(e["rank"] for e in leaderboard["ranking"])
        assert ranks == [1, 2, 3, 4], f"Expected ranks [1,2,3,4], got {ranks}"


# ───────────────────────────────────────────────────────
# Per-subset metric accuracy
# ───────────────────────────────────────────────────────

class TestPerSubsetMetrics:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("subset", EXPECTED_SUBSETS)
    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_value(self, leaderboard, reference, model, subset, metric):
        ref_entry = reference[model]["per_subset"].get(subset)
        if ref_entry is None:
            pytest.skip(f"No reference for {model}/{subset}")
        ref_v = ref_entry[metric]
        entry = _get_entry(leaderboard, model)
        agt_v = entry["per_subset"][subset][metric]
        assert abs(ref_v - agt_v) < TOL, (
            f"{model}/{subset}/{metric}: expected {ref_v:.6f}, got {agt_v}"
        )


# ───────────────────────────────────────────────────────
# Per-class/motion metric accuracy
# ───────────────────────────────────────────────────────

class TestPerCMMetrics:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("cm", EXPECTED_CM)
    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_value(self, leaderboard, reference, model, cm, metric):
        ref_entry = reference[model]["per_class_motion"].get(cm)
        if ref_entry is None:
            pytest.skip(f"No reference for {model}/{cm}")
        ref_v = ref_entry[metric]
        entry = _get_entry(leaderboard, model)
        agt_v = entry["per_class_motion"][cm][metric]
        assert abs(ref_v - agt_v) < TOL, (
            f"{model}/{cm}/{metric}: expected {ref_v:.6f}, got {agt_v}"
        )


# ───────────────────────────────────────────────────────
# Summary metrics
# ───────────────────────────────────────────────────────

class TestSummaryMetrics:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_dynamic_iou(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["dynamic_iou"]
        assert abs(ref_v - entry["dynamic_iou"]) < TOL, (
            f"{model} Dynamic IoU: expected {ref_v:.6f}, got {entry['dynamic_iou']}"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_epe_3way(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["epe_3way"]
        assert abs(ref_v - entry["epe_3way"]) < TOL, (
            f"{model} EPE 3-Way: expected {ref_v:.6f}, got {entry['epe_3way']}"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_accuracy_strict_3way(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["accuracy_strict_3way"]
        assert abs(ref_v - entry["accuracy_strict_3way"]) < TOL, (
            f"{model} AccS 3-Way: expected {ref_v:.6f}, got {entry['accuracy_strict_3way']}"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_accuracy_relaxed_3way(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["accuracy_relaxed_3way"]
        assert abs(ref_v - entry["accuracy_relaxed_3way"]) < TOL, (
            f"{model} AccR 3-Way: expected {ref_v:.6f}, got {entry['accuracy_relaxed_3way']}"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_angle_error_3way(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["angle_error_3way"]
        assert abs(ref_v - entry["angle_error_3way"]) < TOL, (
            f"{model} Angle 3-Way: expected {ref_v:.6f}, got {entry['angle_error_3way']}"
        )


# ───────────────────────────────────────────────────────
# CSFS
# ───────────────────────────────────────────────────────

class TestCSFS:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_csfs_value(self, leaderboard, reference, model):
        entry = _get_entry(leaderboard, model)
        ref_v = reference[model]["csfs"]
        assert abs(ref_v - entry["csfs"]) < TOL, (
            f"{model} CSFS: expected {ref_v:.6f}, got {entry['csfs']}"
        )


# ───────────────────────────────────────────────────────
# Ranking
# ───────────────────────────────────────────────────────

class TestRanking:

    def test_ranking_order_descending(self, leaderboard):
        entries = leaderboard["ranking"]
        for i in range(len(entries) - 1):
            assert entries[i]["csfs"] >= entries[i + 1]["csfs"], (
                f"Rank {entries[i]['rank']} CSFS ({entries[i]['csfs']}) < "
                f"rank {entries[i+1]['rank']} CSFS ({entries[i+1]['csfs']})"
            )

    def test_expected_ranking(self, reference):
        """Alpha should rank first (lowest noise), gamma last (highest noise).
        Delta (after ego-motion correction) should rank between alpha and beta."""
        assert reference["alpha"]["csfs"] > reference["delta"]["csfs"], (
            "Alpha should beat delta"
        )
        assert reference["delta"]["csfs"] > reference["beta"]["csfs"], (
            "Delta should beat beta"
        )
        assert reference["beta"]["csfs"] > reference["gamma"]["csfs"], (
            "Beta should beat gamma"
        )


# ───────────────────────────────────────────────────────
# DuckDB
# ───────────────────────────────────────────────────────

class TestDuckDB:

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), f"DuckDB database not found at {DB_PATH}"

    def test_point_metrics_table_exists(self):
        conn = duckdb.connect(DB_PATH, read_only=True)
        tables = conn.execute("SHOW TABLES").fetchdf()
        conn.close()
        assert "point_metrics" in tables["name"].values, (
            "Table 'point_metrics' not found in database"
        )

    def test_required_columns(self):
        conn = duckdb.connect(DB_PATH, read_only=True)
        cols = conn.execute("DESCRIBE point_metrics").fetchdf()
        conn.close()
        required = {
            "model", "log_id", "timestamp_ns", "class_name", "motion",
            "is_close", "epe", "accuracy_strict", "accuracy_relaxed",
            "angle_error", "pred_dynamic", "gt_dynamic",
        }
        actual = set(cols["column_name"].values)
        missing = required - actual
        assert not missing, f"Missing columns in point_metrics: {missing}"

    def test_has_all_models(self):
        conn = duckdb.connect(DB_PATH, read_only=True)
        models = conn.execute(
            "SELECT DISTINCT model FROM point_metrics ORDER BY model"
        ).fetchdf()
        conn.close()
        assert set(models["model"].values) == set(MODEL_NAMES), (
            f"Expected models {set(MODEL_NAMES)}, "
            f"got {set(models['model'].values)}"
        )

    def test_row_count_reasonable(self):
        conn = duckdb.connect(DB_PATH, read_only=True)
        count = conn.execute("SELECT COUNT(*) FROM point_metrics").fetchone()[0]
        conn.close()
        # 15 sweeps * ~600-1100 pts * ~91% valid * 4 models ~ 32000-60000
        assert 25000 < count < 70000, (
            f"point_metrics row count {count} outside expected range [25000, 70000]"
        )

    def test_aggregation_matches_leaderboard(self):
        """Verify that SQL aggregation on point_metrics matches leaderboard."""
        if not os.path.exists(LEADERBOARD_PATH):
            pytest.skip("No leaderboard to compare against")
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = conn.execute("""
            SELECT model, AVG(epe) as mean_epe
            FROM point_metrics
            WHERE class_name = 'Foreground' AND motion = 'Dynamic'
            GROUP BY model
            ORDER BY model
        """).fetchdf()
        conn.close()

        with open(LEADERBOARD_PATH) as f:
            lb = json.load(f)

        for _, row in result.iterrows():
            model = row["model"]
            db_epe = row["mean_epe"]
            entry = _get_entry(lb, model)
            lb_epe = entry["per_class_motion"]["Foreground/Dynamic"]["EPE"]
            assert abs(db_epe - lb_epe) < TOL, (
                f"{model} FG/Dyn EPE: DB={db_epe:.6f}, LB={lb_epe:.6f}"
            )


# ───────────────────────────────────────────────────────
# Metric bounds and consistency
# ───────────────────────────────────────────────────────

class TestMetricBounds:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("subset", EXPECTED_SUBSETS)
    def test_epe_nonneg(self, leaderboard, model, subset):
        entry = _get_entry(leaderboard, model)
        v = entry["per_subset"][subset]["EPE"]
        assert v >= 0, f"{model}/{subset} EPE={v} should be non-negative"

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("subset", EXPECTED_SUBSETS)
    @pytest.mark.parametrize("metric", ["Accuracy Strict", "Accuracy Relaxed"])
    def test_accuracy_bounds(self, leaderboard, model, subset, metric):
        entry = _get_entry(leaderboard, model)
        v = entry["per_subset"][subset][metric]
        assert 0.0 <= v <= 1.0 + 1e-6, (
            f"{model}/{subset}/{metric}={v} out of [0, 1]"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("subset", EXPECTED_SUBSETS)
    def test_angle_bounds(self, leaderboard, model, subset):
        entry = _get_entry(leaderboard, model)
        v = entry["per_subset"][subset]["Angle Error"]
        assert 0.0 <= v <= math.pi + 1e-4, (
            f"{model}/{subset} Angle Error={v} out of [0, pi]"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("subset", EXPECTED_SUBSETS)
    def test_strict_leq_relaxed(self, leaderboard, model, subset):
        entry = _get_entry(leaderboard, model)
        s = entry["per_subset"][subset]["Accuracy Strict"]
        r = entry["per_subset"][subset]["Accuracy Relaxed"]
        assert s <= r + 1e-6, (
            f"{model}/{subset}: Strict ({s}) > Relaxed ({r})"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_iou_bounds(self, leaderboard, model):
        entry = _get_entry(leaderboard, model)
        v = entry["dynamic_iou"]
        assert 0.0 <= v <= 1.0 + 1e-6, f"{model} Dynamic IoU={v} out of [0, 1]"

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_csfs_bounds(self, leaderboard, model):
        entry = _get_entry(leaderboard, model)
        v = entry["csfs"]
        assert 0.0 <= v <= 1.0 + 1e-6, f"{model} CSFS={v} out of [0, 1]"


class TestConsistency:

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_epe_3way_is_mean(self, leaderboard, model):
        """EPE 3-Way should equal the mean of the three class/motion EPE values."""
        entry = _get_entry(leaderboard, model)
        vals = [entry["per_class_motion"][g]["EPE"] for g in EXPECTED_CM]
        expected = sum(vals) / len(vals)
        assert abs(entry["epe_3way"] - expected) < 1e-3, (
            f"{model} EPE 3-Way ({entry['epe_3way']}) != mean ({expected})"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    def test_csfs_formula(self, leaderboard, model):
        """Verify CSFS matches the derived composite scoring formula."""
        entry = _get_entry(leaderboard, model)
        epe_score = max(0.0, 1.0 - entry["epe_3way"] / 2.0)
        acc_score = (
            entry["accuracy_strict_3way"] + entry["accuracy_relaxed_3way"]
        ) / 2.0
        angle_score = max(0.0, 1.0 - entry["angle_error_3way"] / math.pi)
        expected = entry["dynamic_iou"] * (epe_score + acc_score + angle_score) / 3.0
        assert abs(entry["csfs"] - expected) < 1e-3, (
            f"{model} CSFS ({entry['csfs']}) != formula ({expected})"
        )

    @pytest.mark.parametrize("model", MODEL_NAMES)
    @pytest.mark.parametrize("cm", EXPECTED_CM)
    def test_cm_between_distance_subsets(self, leaderboard, model, cm):
        """Class/motion EPE should be between its Close and Far subset EPEs."""
        entry = _get_entry(leaderboard, model)
        cm_epe = entry["per_class_motion"][cm]["EPE"]
        close_epe = entry["per_subset"].get(f"{cm}/Close", {}).get("EPE")
        far_epe = entry["per_subset"].get(f"{cm}/Far", {}).get("EPE")
        if close_epe is not None and far_epe is not None:
            lo = min(close_epe, far_epe)
            hi = max(close_epe, far_epe)
            assert lo - 1e-4 <= cm_epe <= hi + 1e-4, (
                f"{model}/{cm} EPE ({cm_epe}) not between "
                f"Close ({close_epe}) and Far ({far_epe})"
            )
