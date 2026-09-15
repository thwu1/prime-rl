"""
Verification tests for ISLES-26 challenge evaluation pipeline.
Independently computes all metrics, stratified bootstrap ranking,
leave-one-out stability, and Holm-Bonferroni correction.

"""
import json
import os
import numpy as np
import nibabel as nib
from scipy.ndimage import label as cc3d_label
from scipy.stats import wilcoxon, rankdata
import pytest

RESULTS_PATH = "/app/results.json"
DATA_DIR = "/app/data"
GT_DIR = os.path.join(DATA_DIR, "ground_truth")
PRED_DIR = os.path.join(DATA_DIR, "predictions")
TEAMS = ["alpha", "beta", "gamma", "delta"]
CASES = [f"case_{i:03d}" for i in range(1, 9)]
TOL = 1e-4


# --------------- reference metric implementations ---------------

def _load(path):
    img = nib.load(path)
    return img.get_fdata().astype(np.float32), list(img.header.get_zooms()[:3])


def _dice(pred, gt):
    p = pred > 0.5
    g = gt > 0.5
    ps, gs = p.sum(), g.sum()
    if ps == 0 and gs == 0:
        return 1.0
    return float(2.0 * np.logical_and(p, g).sum() / (ps + gs))


def _avd(pred, gt, vd):
    vol = float(np.prod(vd)) / 1000.0
    return abs(float((pred > 0.5).sum() - (gt > 0.5).sum())) * vol


def _f1(pred, gt):
    p = (pred > 0.5).astype(np.int32)
    g = (gt > 0.5).astype(np.int32)
    gl, ng = cc3d_label(g)
    pl, np_ = cc3d_label(p)
    if ng == 0 and np_ == 0:
        return 1.0
    if ng == 0 or np_ == 0:
        return 0.0
    tp = sum(1 for i in range(1, ng + 1) if np.any(p[gl == i] > 0))
    fn = ng - tp
    fp = sum(1 for i in range(1, np_ + 1) if not np.any(g[pl == i] > 0))
    d = 2 * tp + fp + fn
    return float(2 * tp / d) if d > 0 else 1.0


def _ald(pred, gt):
    _, ng = cc3d_label((gt > 0.5).astype(np.int32))
    _, np_ = cc3d_label((pred > 0.5).astype(np.int32))
    return abs(np_ - ng)


def _classify(gt, vd):
    g = (gt > 0.5).astype(np.int32)
    total = int(g.sum())
    if total == 0:
        return "no_lesion"
    labels, nl = cc3d_label(g)
    sizes = [int((labels == i).sum()) for i in range(1, nl + 1)]
    largest = max(sizes)
    if largest / total > 0.95:
        return "single_vessel_infarct"
    vol_ml = total * float(np.prod(vd)) / 1000.0
    if nl >= 3 and (largest / total < 0.60 or vol_ml < 5.0):
        return "scattered_infarcts"
    return "mixed"


# --------------- reference bootstrap implementation ---------------

def _stratified_bootstrap(metrics, teams, cases, classifications,
                          n_boot=1000, seed=42):
    rng = np.random.RandomState(seed)
    metric_names = ["dice", "lesion_f1", "avd_ml", "ald"]
    higher_better = {"dice": True, "lesion_f1": True,
                     "avd_ml": False, "ald": False}

    strata = {}
    for case in cases:
        cat = classifications[case]
        strata.setdefault(cat, []).append(case)
    sorted_cats = sorted(strata.keys())

    combined_all = {t: [] for t in teams}
    r1_count = {t: 0 for t in teams}

    for _ in range(n_boot):
        sampled = []
        for cat in sorted_cats:
            sc = strata[cat]
            idx = rng.choice(len(sc), size=len(sc), replace=True)
            sampled.extend([sc[i] for i in idx])

        per_metric_ranks = {t: [] for t in teams}
        for mn in metric_names:
            means = np.array([np.mean([metrics[t][c][mn] for c in sampled])
                              for t in teams])
            if higher_better[mn]:
                ranks = rankdata(-means, method="average")
            else:
                ranks = rankdata(means, method="average")
            for j, t in enumerate(teams):
                per_metric_ranks[t].append(ranks[j])

        combined = {t: float(np.mean(per_metric_ranks[t])) for t in teams}
        best = min(combined.values())
        for t in teams:
            combined_all[t].append(combined[t])
            if combined[t] == best:
                r1_count[t] += 1

    mean_ranks = {t: float(np.mean(combined_all[t])) for t in teams}
    final_order = sorted(teams, key=lambda t: mean_ranks[t])
    r1_freq = {t: r1_count[t] / n_boot for t in teams}
    ci_95 = {}
    for t in teams:
        ci_95[t] = [float(np.percentile(combined_all[t], 2.5)),
                    float(np.percentile(combined_all[t], 97.5))]

    return {
        "final_order": final_order,
        "mean_ranks": mean_ranks,
        "rank1_frequency": r1_freq,
        "confidence_intervals_95": ci_95,
    }


def _holm_bonferroni(raw_pvals):
    m = len(raw_pvals)
    sorted_idx = sorted(range(m), key=lambda i: raw_pvals[i])
    corrected = [0.0] * m
    for rank_pos, orig_idx in enumerate(sorted_idx):
        multiplier = m - rank_pos
        corrected[orig_idx] = min(raw_pvals[orig_idx] * multiplier, 1.0)
    prev = 0.0
    for rank_pos, orig_idx in enumerate(sorted_idx):
        corrected[orig_idx] = max(corrected[orig_idx], prev)
        prev = corrected[orig_idx]
    return corrected


# --------------- fixtures ---------------

@pytest.fixture(scope="module")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref():
    metrics = {}
    for team in TEAMS:
        metrics[team] = {}
        for case in CASES:
            gt, vd = _load(os.path.join(GT_DIR, f"{case}.nii.gz"))
            pr, _ = _load(os.path.join(PRED_DIR, team, f"{case}.nii.gz"))
            metrics[team][case] = {
                "dice": _dice(pr, gt),
                "avd_ml": _avd(pr, gt, vd),
                "lesion_f1": _f1(pr, gt),
                "ald": _ald(pr, gt),
            }
    return metrics


@pytest.fixture(scope="module")
def ref_classifications():
    classifications = {}
    for case in CASES:
        gt, vd = _load(os.path.join(GT_DIR, f"{case}.nii.gz"))
        classifications[case] = _classify(gt, vd)
    return classifications


@pytest.fixture(scope="module")
def ref_ranking(ref, ref_classifications):
    return _stratified_bootstrap(ref, TEAMS, CASES, ref_classifications)


@pytest.fixture(scope="module")
def ref_loo(ref, ref_classifications, ref_ranking):
    full_order = ref_ranking["final_order"]
    full_positions = {t: i for i, t in enumerate(full_order)}
    loo_results = {}
    max_change = -1
    most_influential = None
    for excluded in CASES:
        remaining = [c for c in CASES if c != excluded]
        rem_class = {c: ref_classifications[c] for c in remaining}
        loo_ranking = _stratified_bootstrap(ref, TEAMS, remaining, rem_class)
        loo_order = loo_ranking["final_order"]
        loo_positions = {t: i for i, t in enumerate(loo_order)}
        total_change = sum(abs(full_positions[t] - loo_positions[t])
                          for t in TEAMS)
        loo_results[excluded] = {
            "ranking_change": total_change,
            "order": loo_order,
        }
        if total_change > max_change or (
                total_change == max_change and
                (most_influential is None or excluded < most_influential)):
            max_change = total_change
            most_influential = excluded
    return loo_results, most_influential


# =============== STRUCTURAL TESTS ===============

def test_output_exists():
    assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"


def test_valid_json(results):
    assert isinstance(results, dict)


def test_top_level_keys(results):
    for k in ("metrics", "case_classification", "ranking",
              "stability", "pairwise_significance"):
        assert k in results, f"Missing top-level key: {k}"


def test_metrics_structure(results):
    for team in TEAMS:
        assert team in results["metrics"], f"Missing team: {team}"
        for case in CASES:
            assert case in results["metrics"][team], f"Missing {team}/{case}"
            m = results["metrics"][team][case]
            for field in ("dice", "avd_ml", "lesion_f1", "ald"):
                assert field in m, f"Missing field {field} in {team}/{case}"


# =============== METRIC ACCURACY TESTS ===============

def test_dice_values(results, ref):
    for team in TEAMS:
        for case in CASES:
            exp = ref[team][case]["dice"]
            act = results["metrics"][team][case]["dice"]
            assert abs(act - exp) < TOL, \
                f"Dice {team}/{case}: expected {exp:.6f}, got {act}"


def test_avd_values(results, ref):
    for team in TEAMS:
        for case in CASES:
            exp = ref[team][case]["avd_ml"]
            act = results["metrics"][team][case]["avd_ml"]
            assert abs(act - exp) < TOL, \
                f"AVD {team}/{case}: expected {exp:.6f}, got {act}"


def test_lesion_f1_values(results, ref):
    for team in TEAMS:
        for case in CASES:
            exp = ref[team][case]["lesion_f1"]
            act = results["metrics"][team][case]["lesion_f1"]
            assert abs(act - exp) < TOL, \
                f"F1 {team}/{case}: expected {exp:.6f}, got {act}"


def test_ald_values(results, ref):
    for team in TEAMS:
        for case in CASES:
            exp = ref[team][case]["ald"]
            act = int(results["metrics"][team][case]["ald"])
            assert act == exp, \
                f"ALD {team}/{case}: expected {exp}, got {act}"


# =============== SPOT-CHECK EDGE CASES ===============

def test_perfect_match(results):
    m = results["metrics"]["alpha"]["case_001"]
    assert m["dice"] == 1.0
    assert m["avd_ml"] == 0.0
    assert m["lesion_f1"] == 1.0
    assert m["ald"] == 0


def test_both_empty(results):
    m = results["metrics"]["alpha"]["case_003"]
    assert m["dice"] == 1.0
    assert m["avd_ml"] == 0.0
    assert m["lesion_f1"] == 1.0
    assert m["ald"] == 0


def test_pred_empty_on_nonempty_gt(results):
    m = results["metrics"]["delta"]["case_002"]
    assert m["dice"] == 0.0
    assert m["lesion_f1"] == 0.0


def test_false_positive_on_empty_gt(results):
    m = results["metrics"]["gamma"]["case_003"]
    assert m["dice"] == 0.0
    assert m["lesion_f1"] == 0.0


def test_no_overlap(results):
    m = results["metrics"]["delta"]["case_005"]
    assert m["dice"] == 0.0
    assert m["lesion_f1"] == 0.0


# =============== CASE CLASSIFICATION ===============

def test_case_classification(results):
    expected = {
        "case_001": "single_vessel_infarct",
        "case_002": "mixed",
        "case_003": "no_lesion",
        "case_004": "single_vessel_infarct",
        "case_005": "scattered_infarcts",
        "case_006": "single_vessel_infarct",
        "case_007": "single_vessel_infarct",
        "case_008": "mixed",
    }
    cc = results["case_classification"]
    for case, cat in expected.items():
        assert cc[case] == cat, \
            f"Classification {case}: expected '{cat}', got '{cc[case]}'"


# =============== RANKING TESTS ===============

def test_ranking_structure(results):
    r = results["ranking"]
    assert "final_order" in r
    assert "mean_ranks" in r
    assert "rank1_frequency" in r
    assert "confidence_intervals_95" in r
    assert set(r["final_order"]) == set(TEAMS)
    assert len(r["final_order"]) == len(TEAMS)


def test_ranking_order(results):
    order = results["ranking"]["final_order"]
    assert order[0] == "alpha", f"Expected alpha rank 1, got {order[0]}"
    assert order[-1] == "delta", f"Expected delta rank 4, got {order[-1]}"
    assert order.index("beta") < order.index("gamma"), \
        "Expected beta ranked above gamma"


def test_mean_ranks_range(results):
    for team in TEAMS:
        mr = results["ranking"]["mean_ranks"][team]
        assert 1.0 <= mr <= 4.0, f"{team} mean rank {mr} out of [1,4]"


def test_alpha_best_mean_rank(results):
    mr = results["ranking"]["mean_ranks"]
    assert mr["alpha"] < mr["beta"], "Alpha should have lower mean rank"
    assert mr["alpha"] < mr["gamma"]
    assert mr["alpha"] < mr["delta"]


def test_mean_ranks_match_reference(results, ref_ranking):
    for team in TEAMS:
        exp = ref_ranking["mean_ranks"][team]
        act = results["ranking"]["mean_ranks"][team]
        assert abs(act - exp) < TOL, \
            f"Mean rank {team}: expected {exp:.6f}, got {act}"


def test_rank1_frequency_match(results, ref_ranking):
    for team in TEAMS:
        exp = ref_ranking["rank1_frequency"][team]
        act = results["ranking"]["rank1_frequency"][team]
        assert abs(act - exp) < TOL, \
            f"Rank1 freq {team}: expected {exp:.6f}, got {act}"


def test_rank1_frequency_properties(results):
    r1 = results["ranking"]["rank1_frequency"]
    for team in TEAMS:
        assert 0.0 <= r1[team] <= 1.0
    total = sum(r1.values())
    assert abs(total - 1.0) < 0.1, f"rank1 frequencies sum to {total}"
    assert r1["alpha"] > 0.3, f"Alpha rank1 freq too low: {r1['alpha']}"


# =============== CONFIDENCE INTERVAL TESTS ===============

def test_ci_structure(results):
    ci = results["ranking"]["confidence_intervals_95"]
    for team in TEAMS:
        assert team in ci, f"Missing CI for {team}"
        assert isinstance(ci[team], list) and len(ci[team]) == 2, \
            f"CI for {team} should be [lower, upper]"
        assert ci[team][0] <= ci[team][1], \
            f"CI lower > upper for {team}: {ci[team]}"


def test_ci_contains_mean_rank(results):
    ci = results["ranking"]["confidence_intervals_95"]
    mr = results["ranking"]["mean_ranks"]
    for team in TEAMS:
        assert ci[team][0] <= mr[team] <= ci[team][1], \
            f"Mean rank {mr[team]} not within CI {ci[team]} for {team}"


def test_ci_values_match_reference(results, ref_ranking):
    for team in TEAMS:
        exp = ref_ranking["confidence_intervals_95"][team]
        act = results["ranking"]["confidence_intervals_95"][team]
        assert abs(act[0] - exp[0]) < TOL, \
            f"CI lower {team}: expected {exp[0]:.4f}, got {act[0]}"
        assert abs(act[1] - exp[1]) < TOL, \
            f"CI upper {team}: expected {exp[1]:.4f}, got {act[1]}"


def test_ci_ranges_reasonable(results):
    ci = results["ranking"]["confidence_intervals_95"]
    for team in TEAMS:
        assert ci[team][0] >= 1.0, f"CI lower below 1.0 for {team}"
        assert ci[team][1] <= 4.0, f"CI upper above 4.0 for {team}"


# =============== STABILITY (LEAVE-ONE-OUT) TESTS ===============

def test_stability_structure(results):
    s = results["stability"]
    assert "leave_one_out" in s
    assert "most_influential_case" in s
    loo = s["leave_one_out"]
    for case in CASES:
        assert case in loo, f"Missing LOO entry for {case}"
        assert "ranking_change" in loo[case]
        assert "order" in loo[case]
        assert isinstance(loo[case]["ranking_change"], int)
        assert set(loo[case]["order"]) == set(TEAMS)


def test_loo_ranking_change_nonnegative(results):
    for case in CASES:
        rc = results["stability"]["leave_one_out"][case]["ranking_change"]
        assert rc >= 0, f"Negative ranking change for {case}: {rc}"


def test_most_influential_case_matches(results, ref_loo):
    _, ref_most = ref_loo
    act = results["stability"]["most_influential_case"]
    assert act == ref_most, \
        f"Most influential: expected '{ref_most}', got '{act}'"


def test_loo_ranking_changes_match(results, ref_loo):
    ref_results, _ = ref_loo
    for case in CASES:
        exp = ref_results[case]["ranking_change"]
        act = results["stability"]["leave_one_out"][case]["ranking_change"]
        assert act == exp, \
            f"LOO change {case}: expected {exp}, got {act}"


def test_loo_orders_match(results, ref_loo):
    ref_results, _ = ref_loo
    for case in CASES:
        exp = ref_results[case]["order"]
        act = results["stability"]["leave_one_out"][case]["order"]
        assert act == exp, \
            f"LOO order {case}: expected {exp}, got {act}"


def test_most_influential_has_max_change(results):
    loo = results["stability"]["leave_one_out"]
    mic = results["stability"]["most_influential_case"]
    max_change = max(loo[c]["ranking_change"] for c in CASES)
    assert loo[mic]["ranking_change"] == max_change, \
        f"Most influential case {mic} has change {loo[mic]['ranking_change']} " \
        f"but max is {max_change}"


# =============== PAIRWISE SIGNIFICANCE TESTS ===============

def test_pairwise_structure(results):
    pairs = results["pairwise_significance"]
    assert isinstance(pairs, list)
    assert len(pairs) == 3, f"Expected 3 pairwise comparisons, got {len(pairs)}"
    for p in pairs:
        assert "team_a" in p
        assert "team_b" in p
        assert "dice_p_value_raw" in p
        assert "dice_p_value_corrected" in p
        assert 0.0 <= p["dice_p_value_raw"] <= 1.0
        assert 0.0 <= p["dice_p_value_corrected"] <= 1.0


def test_pairwise_teams_match_ranking(results):
    order = results["ranking"]["final_order"]
    pairs = results["pairwise_significance"]
    for i, p in enumerate(pairs):
        assert p["team_a"] == order[i], \
            f"Pair {i} team_a should be {order[i]}, got {p['team_a']}"
        assert p["team_b"] == order[i + 1], \
            f"Pair {i} team_b should be {order[i+1]}, got {p['team_b']}"


def test_corrected_geq_raw(results):
    for p in results["pairwise_significance"]:
        assert p["dice_p_value_corrected"] >= p["dice_p_value_raw"] - TOL, \
            f"Corrected p-value {p['dice_p_value_corrected']} < raw " \
            f"{p['dice_p_value_raw']} for {p['team_a']} vs {p['team_b']}"


def test_holm_bonferroni_correction(results, ref):
    order = results["ranking"]["final_order"]
    raw_pvals = []
    for i in range(len(order) - 1):
        ta, tb = order[i], order[i + 1]
        da = [ref[ta][c]["dice"] for c in CASES]
        db = [ref[tb][c]["dice"] for c in CASES]
        diffs = [a - b for a, b in zip(da, db)]
        if all(d == 0.0 for d in diffs):
            pv = 1.0
        else:
            try:
                _, pv = wilcoxon(da, db)
            except ValueError:
                pv = 1.0
        raw_pvals.append(pv)

    expected_corrected = _holm_bonferroni(raw_pvals)

    pairs = results["pairwise_significance"]
    for i in range(len(pairs)):
        assert abs(pairs[i]["dice_p_value_raw"] - raw_pvals[i]) < TOL, \
            f"Raw p-value mismatch at position {i}"
        assert abs(pairs[i]["dice_p_value_corrected"] -
                   expected_corrected[i]) < TOL, \
            f"Corrected p-value mismatch at position {i}: " \
            f"expected {expected_corrected[i]:.6f}, " \
            f"got {pairs[i]['dice_p_value_corrected']}"


def test_corrected_pvalues_monotone_in_sorted_order(results):
    """Holm-Bonferroni corrected p-values must be non-decreasing when
    sorted by their raw p-value."""
    pairs = results["pairwise_significance"]
    sorted_pairs = sorted(pairs, key=lambda p: p["dice_p_value_raw"])
    for i in range(1, len(sorted_pairs)):
        assert sorted_pairs[i]["dice_p_value_corrected"] >= \
               sorted_pairs[i - 1]["dice_p_value_corrected"] - TOL, \
            "Corrected p-values not monotone in sorted order"
