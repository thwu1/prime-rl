"""Verification tests for Argoverse 2 scene flow evaluation pipeline."""

import json
import math
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

_ANN_DIR = "/app/data/annotations"
_PRED_DIR = "/app/data/predictions"
_CFG_PATH = "/app/config.json"
_RES_PATH = "/app/results.json"
_EPS = 1e-10
_EXCL = ("Background", "Dynamic")
_TOL = 1e-3
_FLOW_METRICS = ["EPE", "Accuracy Strict", "Accuracy Relax", "Angle Error"]


# ============================================================================
# Reference computation — intentionally structured differently from a clean
# solution to avoid trivial copy-paste.
# ============================================================================

def _ref_single_scene(sid, cfg):
    """Return per-subset records and global segmentation counts for one scene."""
    gt = np.load(os.path.join(cfg["annotations_dir"], f"{sid}.npz"))
    pdf = pd.read_feather(os.path.join(cfg["predictions_dir"], f"{sid}.feather"))

    v = gt["is_valid"].astype(bool)
    gf = gt["flow"][v].astype(np.float64)
    gd = gt["is_dynamic"][v].astype(bool)
    gc = gt["category_indices"][v]
    gk = gt["is_close"][v].astype(bool)

    pf = np.column_stack([
        pdf["flow_tx_m"].values.astype(np.float64),
        pdf["flow_ty_m"].values.astype(np.float64),
        pdf["flow_tz_m"].values.astype(np.float64),
    ])[v]
    pd_dyn = pdf["is_dynamic"].values[v].astype(bool)

    tp = int(np.logical_and(pd_dyn, gd).sum())
    fp = int(np.logical_and(pd_dyn, ~gd).sum())
    fn = int(np.logical_and(~pd_dyn, gd).sum())

    td = cfg["sweep_pair_time_delta"]
    st = cfg["accuracy_strict_threshold"]
    rt = cfg["accuracy_relax_threshold"]
    fg = cfg["foreground_categories"]
    bg = cfg["background_categories"]

    records = {}
    for cn, cats in [("Foreground", fg), ("Background", bg)]:
        cm = np.isin(gc, cats)
        for mn, mf in [("Dynamic", True), ("Static", False)]:
            mm = gd == mf
            for dn, df_ in [("Close", True), ("Far", False)]:
                dm = gk == df_
                mask = cm & mm & dm
                cnt = int(mask.sum())
                rec = {"count": cnt}
                if cnt > 0:
                    sp, sg = pf[mask], gf[mask]
                    diff_norm = np.linalg.norm(sp - sg, axis=-1)
                    gt_norm = np.linalg.norm(sg, axis=-1)
                    rel = diff_norm / (gt_norm + _EPS)

                    rec["EPE"] = float(diff_norm.mean())
                    rec["Accuracy Strict"] = float(
                        np.logical_or(diff_norm < st, rel < st).mean()
                    )
                    rec["Accuracy Relax"] = float(
                        np.logical_or(diff_norm < rt, rel < rt).mean()
                    )
                    sp4 = np.pad(sp, ((0, 0), (0, 1)), constant_values=td)
                    sg4 = np.pad(sg, ((0, 0), (0, 1)), constant_values=td)
                    up = sp4 / np.linalg.norm(sp4, axis=-1, keepdims=True)
                    ug = sg4 / np.linalg.norm(sg4, axis=-1, keepdims=True)
                    dot = np.clip(np.einsum("ij,ij->i", up, ug), -1.0, 1.0)
                    rec["Angle Error"] = float(np.arccos(dot).mean())
                records[(cn, mn, dn)] = rec
    return records, tp, fp, fn


@pytest.fixture(scope="module")
def config():
    with open(_CFG_PATH) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(_RES_PATH), f"Results not found at {_RES_PATH}"
    with open(_RES_PATH) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def reference(config):
    ann_files = sorted(f for f in os.listdir(config["annotations_dir"]) if f.endswith(".npz"))
    all_recs = defaultdict(list)
    g_tp, g_fp, g_fn = 0, 0, 0

    for af in ann_files:
        sid = af[:-4]
        recs, tp, fp, fn = _ref_single_scene(sid, config)
        g_tp += tp
        g_fp += fp
        g_fn += fn
        for key, rec in recs.items():
            all_recs[key].append(rec)

    # Per-distance aggregation
    metrics = {}
    for (cls, mot, dist), scene_recs in all_recs.items():
        if (cls, mot) == _EXCL:
            continue
        total = sum(r["count"] for r in scene_recs)
        for m in _FLOW_METRICS:
            k = f"{m}/{cls}/{mot}/{dist}"
            if total > 0:
                wsum = sum(r[m] * r["count"] for r in scene_recs if r["count"] > 0)
                metrics[k] = round(wsum / total, 6)
            else:
                metrics[k] = None

    # Distance-aggregated
    class_names = ["Foreground", "Background"]
    motion_names = ["Dynamic", "Static"]
    for cn in class_names:
        for mn in motion_names:
            if (cn, mn) == _EXCL:
                continue
            cr = all_recs.get((cn, mn, "Close"), [])
            fr = all_recs.get((cn, mn, "Far"), [])
            ar = cr + fr
            total = sum(r["count"] for r in ar)
            for m in _FLOW_METRICS:
                k = f"{m}/{cn}/{mn}"
                if total > 0:
                    wsum = sum(r[m] * r["count"] for r in ar if r["count"] > 0)
                    metrics[k] = round(wsum / total, 6)
                else:
                    metrics[k] = None

    epe_3 = sum(
        metrics.get(f"EPE/{c}", 0) or 0
        for c in ["Foreground/Dynamic", "Foreground/Static", "Background/Static"]
    ) / 3.0

    dyn_iou = g_tp / (g_tp + g_fp + g_fn + _EPS)

    return {
        "metrics": metrics,
        "EPE_3Way": round(epe_3, 6),
        "Dynamic_IoU": round(dyn_iou, 6),
    }


# ============================================================================
# Structural tests
# ============================================================================

class TestFileStructure:
    def test_results_file_exists(self):
        assert os.path.exists(_RES_PATH), "results.json missing"

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_metrics_dict(self, results):
        assert "metrics" in results
        assert isinstance(results["metrics"], dict)

    def test_has_epe_3way(self, results):
        assert "EPE_3Way" in results

    def test_has_dynamic_iou(self, results):
        assert "Dynamic_IoU" in results


class TestMetricKeys:
    def test_per_distance_keys_present(self, results, reference):
        for key in reference["metrics"]:
            if key.count("/") == 3:
                assert key in results["metrics"], f"Missing per-distance key: {key}"

    def test_aggregated_keys_present(self, results, reference):
        for key in reference["metrics"]:
            if key.count("/") == 2:
                assert key in results["metrics"], f"Missing aggregated key: {key}"

    def test_no_excluded_background_dynamic(self, results):
        for key in results["metrics"]:
            parts = key.split("/")
            if len(parts) >= 3:
                assert (parts[1], parts[2]) != _EXCL, \
                    f"Excluded combination present: {key}"


# ============================================================================
# Value correctness tests
# ============================================================================

class TestEPE:
    def test_per_distance(self, results, reference):
        for key, ref_val in reference["metrics"].items():
            if not key.startswith("EPE/") or ref_val is None:
                continue
            assert key in results["metrics"], f"Missing: {key}"
            assert abs(results["metrics"][key] - ref_val) < _TOL, \
                f"{key}: got {results['metrics'][key]}, expected {ref_val}"

    def test_non_negative(self, results):
        for key, val in results["metrics"].items():
            if key.startswith("EPE/") and val is not None:
                assert val >= 0.0, f"{key} negative: {val}"


class TestAccuracyStrict:
    def test_values(self, results, reference):
        for key, ref_val in reference["metrics"].items():
            if not key.startswith("Accuracy Strict/") or ref_val is None:
                continue
            assert key in results["metrics"], f"Missing: {key}"
            assert abs(results["metrics"][key] - ref_val) < _TOL, \
                f"{key}: got {results['metrics'][key]}, expected {ref_val}"

    def test_range(self, results):
        for key, val in results["metrics"].items():
            if key.startswith("Accuracy Strict/") and val is not None:
                assert 0.0 <= val <= 1.0, f"{key} out of [0,1]: {val}"


class TestAccuracyRelax:
    def test_values(self, results, reference):
        for key, ref_val in reference["metrics"].items():
            if not key.startswith("Accuracy Relax/") or ref_val is None:
                continue
            assert key in results["metrics"], f"Missing: {key}"
            assert abs(results["metrics"][key] - ref_val) < _TOL, \
                f"{key}: got {results['metrics'][key]}, expected {ref_val}"

    def test_range(self, results):
        for key, val in results["metrics"].items():
            if key.startswith("Accuracy Relax/") and val is not None:
                assert 0.0 <= val <= 1.0, f"{key} out of [0,1]: {val}"


class TestAngleError:
    def test_values(self, results, reference):
        for key, ref_val in reference["metrics"].items():
            if not key.startswith("Angle Error/") or ref_val is None:
                continue
            assert key in results["metrics"], f"Missing: {key}"
            assert abs(results["metrics"][key] - ref_val) < _TOL, \
                f"{key}: got {results['metrics'][key]}, expected {ref_val}"

    def test_range(self, results):
        for key, val in results["metrics"].items():
            if key.startswith("Angle Error/") and val is not None:
                assert 0.0 <= val <= math.pi + 0.01, \
                    f"{key} out of [0, pi]: {val}"


class TestComposites:
    def test_epe_3way(self, results, reference):
        assert abs(results["EPE_3Way"] - reference["EPE_3Way"]) < _TOL, \
            f"EPE_3Way: got {results['EPE_3Way']}, expected {reference['EPE_3Way']}"

    def test_dynamic_iou(self, results, reference):
        assert abs(results["Dynamic_IoU"] - reference["Dynamic_IoU"]) < _TOL, \
            f"Dynamic_IoU: got {results['Dynamic_IoU']}, expected {reference['Dynamic_IoU']}"

    def test_dynamic_iou_range(self, results):
        assert 0.0 <= results["Dynamic_IoU"] <= 1.0, \
            f"Dynamic_IoU out of [0,1]: {results['Dynamic_IoU']}"

    def test_epe_3way_consistency(self, results):
        m = results["metrics"]
        vals = [
            m.get("EPE/Foreground/Dynamic"),
            m.get("EPE/Foreground/Static"),
            m.get("EPE/Background/Static"),
        ]
        if all(v is not None for v in vals):
            expected = sum(vals) / 3.0
            assert abs(results["EPE_3Way"] - expected) < 1e-4, \
                f"EPE_3Way inconsistency: {results['EPE_3Way']} vs {expected}"

    def test_accuracy_relax_ge_strict(self, results):
        m = results["metrics"]
        for key, val in m.items():
            if key.startswith("Accuracy Strict/") and val is not None:
                relax_key = key.replace("Accuracy Strict/", "Accuracy Relax/")
                relax_val = m.get(relax_key)
                if relax_val is not None:
                    assert relax_val >= val - 1e-6, \
                        f"Relax < Strict for {key}: {relax_val} < {val}"
