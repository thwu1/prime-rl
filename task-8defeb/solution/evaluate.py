#!/usr/bin/env python3
"""
ISLES-26 challenge evaluation pipeline.
Computes segmentation metrics, lesion classification, stratified bootstrap
ranking with confidence intervals, leave-one-out stability analysis,
and pairwise significance with Holm-Bonferroni correction.

"""
import json
import os
import numpy as np
import nibabel as nib
from scipy.ndimage import label as cc3d_label
from scipy.stats import wilcoxon, rankdata

DATA_DIR = "/app/data"
GT_DIR = os.path.join(DATA_DIR, "ground_truth")
PRED_DIR = os.path.join(DATA_DIR, "predictions")
OUTPUT = "/app/results.json"


def discover():
    teams = sorted(d for d in os.listdir(PRED_DIR)
                   if os.path.isdir(os.path.join(PRED_DIR, d)))
    cases = sorted(f.replace(".nii.gz", "")
                   for f in os.listdir(GT_DIR) if f.endswith(".nii.gz"))
    return teams, cases


def load_mask(path):
    img = nib.load(path)
    data = img.get_fdata().astype(np.float32)
    voxdims = list(img.header.get_zooms()[:3])
    return data, voxdims


# ---- metrics ----

def dice(pred, gt):
    p = pred > 0.5
    g = gt > 0.5
    ps, gs = int(p.sum()), int(g.sum())
    if ps == 0 and gs == 0:
        return 1.0
    inter = int(np.logical_and(p, g).sum())
    return 2.0 * inter / (ps + gs)


def avd_ml(pred, gt, voxdims):
    vvol = float(np.prod(voxdims)) / 1000.0
    pv = float((pred > 0.5).sum()) * vvol
    gv = float((gt > 0.5).sum()) * vvol
    return abs(pv - gv)


def lesion_f1(pred, gt):
    """Any-voxel-overlap F1 (NOT panoptica IoU-threshold matching)."""
    p = (pred > 0.5).astype(np.int32)
    g = (gt > 0.5).astype(np.int32)
    gl, ng = cc3d_label(g)
    pl, npred = cc3d_label(p)
    if ng == 0 and npred == 0:
        return 1.0
    if ng == 0 or npred == 0:
        return 0.0
    tp = 0
    for i in range(1, ng + 1):
        if np.any(p[gl == i] > 0):
            tp += 1
    fn = ng - tp
    fp = 0
    for i in range(1, npred + 1):
        if not np.any(g[pl == i] > 0):
            fp += 1
    denom = 2 * tp + fp + fn
    return (2.0 * tp / denom) if denom > 0 else 1.0


def ald(pred, gt):
    _, ng = cc3d_label((gt > 0.5).astype(np.int32))
    _, np_ = cc3d_label((pred > 0.5).astype(np.int32))
    return abs(int(np_) - int(ng))


# ---- classification ----

def classify(gt, voxdims):
    g = (gt > 0.5).astype(np.int32)
    total = int(g.sum())
    if total == 0:
        return "no_lesion"
    labels, nl = cc3d_label(g)
    sizes = [int((labels == i).sum()) for i in range(1, nl + 1)]
    largest = max(sizes)
    if largest / total > 0.95:
        return "single_vessel_infarct"
    vol_ml = total * float(np.prod(voxdims)) / 1000.0
    if nl >= 3 and (largest / total < 0.60 or vol_ml < 5.0):
        return "scattered_infarcts"
    return "mixed"


# ---- stratified bootstrap ranking ----

def stratified_bootstrap_rank(metrics, teams, cases, classifications,
                               n_boot=1000, seed=42):
    rng = np.random.RandomState(seed)
    metric_names = ["dice", "lesion_f1", "avd_ml", "ald"]
    higher_better = {"dice": True, "lesion_f1": True,
                     "avd_ml": False, "ald": False}

    # Build strata (sorted lexicographically by category name)
    strata = {}
    for case in cases:
        cat = classifications[case]
        strata.setdefault(cat, []).append(case)
    sorted_cats = sorted(strata.keys())

    combined_all = {t: [] for t in teams}
    r1_count = {t: 0 for t in teams}

    for _ in range(n_boot):
        # Stratified sampling: sample within each stratum independently
        sampled = []
        for cat in sorted_cats:
            stratum_cases = strata[cat]
            n_s = len(stratum_cases)
            idx = rng.choice(n_s, size=n_s, replace=True)
            sampled.extend([stratum_cases[i] for i in idx])

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


# ---- leave-one-out stability ----

def leave_one_out_stability(metrics, teams, cases, classifications):
    full_ranking = stratified_bootstrap_rank(
        metrics, teams, cases, classifications)
    full_order = full_ranking["final_order"]
    full_positions = {t: i for i, t in enumerate(full_order)}

    loo_results = {}
    max_change = -1
    most_influential = None

    for excluded in cases:
        remaining = [c for c in cases if c != excluded]
        remaining_class = {c: classifications[c] for c in remaining}
        loo_ranking = stratified_bootstrap_rank(
            metrics, teams, remaining, remaining_class)
        loo_order = loo_ranking["final_order"]
        loo_positions = {t: i for i, t in enumerate(loo_order)}

        total_change = sum(
            abs(full_positions[t] - loo_positions[t]) for t in teams)

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


# ---- pairwise significance with Holm-Bonferroni ----

def pairwise_sig_corrected(metrics, order, cases):
    pairs = []
    raw_pvals = []

    for i in range(len(order) - 1):
        ta, tb = order[i], order[i + 1]
        da = [metrics[ta][c]["dice"] for c in cases]
        db = [metrics[tb][c]["dice"] for c in cases]
        diffs = [a - b for a, b in zip(da, db)]
        if all(d == 0.0 for d in diffs):
            pv = 1.0
        else:
            try:
                _, pv = wilcoxon(da, db)
            except ValueError:
                pv = 1.0
        raw_pvals.append(pv)
        pairs.append({"team_a": ta, "team_b": tb})

    # Holm-Bonferroni step-down correction
    m = len(raw_pvals)
    sorted_indices = sorted(range(m), key=lambda i: raw_pvals[i])
    corrected = [0.0] * m

    for rank_pos, orig_idx in enumerate(sorted_indices):
        multiplier = m - rank_pos
        corrected[orig_idx] = min(raw_pvals[orig_idx] * multiplier, 1.0)

    # Enforce monotonicity in sorted order
    prev = 0.0
    for rank_pos, orig_idx in enumerate(sorted_indices):
        corrected[orig_idx] = max(corrected[orig_idx], prev)
        prev = corrected[orig_idx]

    for i in range(m):
        pairs[i]["dice_p_value_raw"] = float(raw_pvals[i])
        pairs[i]["dice_p_value_corrected"] = float(corrected[i])

    return pairs


# ---- main ----

def main():
    teams, cases = discover()
    print(f"Teams: {teams}")
    print(f"Cases: {cases}")

    all_metrics = {}
    classifications = {}

    for team in teams:
        all_metrics[team] = {}
        for case in cases:
            gt, vd = load_mask(os.path.join(GT_DIR, f"{case}.nii.gz"))
            pr, _ = load_mask(os.path.join(PRED_DIR, team, f"{case}.nii.gz"))
            all_metrics[team][case] = {
                "dice": dice(pr, gt),
                "avd_ml": avd_ml(pr, gt, vd),
                "lesion_f1": lesion_f1(pr, gt),
                "ald": ald(pr, gt),
            }

    for case in cases:
        gt, vd = load_mask(os.path.join(GT_DIR, f"{case}.nii.gz"))
        classifications[case] = classify(gt, vd)

    print(f"Classifications: {classifications}")

    ranking = stratified_bootstrap_rank(
        all_metrics, teams, cases, classifications)
    print(f"Ranking: {ranking['final_order']}")

    loo_results, most_influential = leave_one_out_stability(
        all_metrics, teams, cases, classifications)
    print(f"Most influential case: {most_influential}")

    pairs = pairwise_sig_corrected(
        all_metrics, ranking["final_order"], cases)

    out = {
        "metrics": all_metrics,
        "case_classification": classifications,
        "ranking": ranking,
        "stability": {
            "leave_one_out": loo_results,
            "most_influential_case": most_influential,
        },
        "pairwise_significance": pairs,
    }
    with open(OUTPUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results written to {OUTPUT}")


if __name__ == "__main__":
    main()
