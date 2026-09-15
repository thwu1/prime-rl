#!/usr/bin/env python3
"""Correct evaluation engine for the multi-task clinical challenge.

Reads configuration from /app/eval_config.toml, data from /app/submissions.db.
Computes all metrics, bootstrap CIs, and rank-stability analysis.
Writes /app/results.json and /app/stability.json.
"""

import tomllib
import sqlite3
import json
import math
import random

CONFIG_PATH = "/app/eval_config.toml"
DB_PATH = "/app/submissions.db"
RESULTS_PATH = "/app/results.json"
STABILITY_PATH = "/app/stability.json"


def load_config(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_data(conn):
    """Load all submission data from SQLite into lists of dicts."""
    seg_data = []
    for row in conn.execute(
        "SELECT team, patient_id, class, gt_volume_mm3, "
        "pred_volume_mm3, intersection_volume_mm3 "
        "FROM segmentation_stats"
    ):
        seg_data.append({
            "team": row[0], "patient_id": row[1], "class": row[2],
            "gt_volume_mm3": row[3], "pred_volume_mm3": row[4],
            "intersection_volume_mm3": row[5],
        })

    staging_data = []
    for row in conn.execute(
        "SELECT team, patient_id, T_true, T_pred, N_true, N_pred FROM staging"
    ):
        staging_data.append({
            "team": row[0], "patient_id": row[1],
            "T_true": row[2], "T_pred": row[3],
            "N_true": row[4], "N_pred": row[5],
        })

    surv_data = []
    for row in conn.execute(
        "SELECT team, patient_id, event_time, event_observed, risk_score "
        "FROM survival"
    ):
        rs = row[4]
        try:
            rs_float = float(rs)
        except (ValueError, TypeError):
            rs_float = float("nan")
        surv_data.append({
            "team": row[0], "patient_id": row[1],
            "event_time": row[2], "event_observed": row[3],
            "risk_score": rs_float,
        })

    patients = sorted(set(
        r["patient_id"] for r in seg_data if r["team"] == "alpha"
    ))

    return seg_data, staging_data, surv_data, patients


# --------------- Metrics ---------------

def compute_aggregated_dsc(seg_rows, team, config):
    """Micro-averaged (aggregated) DSC per class, then mean."""
    team_rows = [r for r in seg_rows if r["team"] == team]
    classes = config["segmentation"]["classes"]
    empty_score = config["segmentation"]["empty_volume_score"]
    class_dscs = []

    for cls in classes:
        cls_rows = [r for r in team_rows if r["class"] == cls]
        total_inter = sum(r["intersection_volume_mm3"] for r in cls_rows)
        total_vol_sum = sum(
            r["gt_volume_mm3"] + r["pred_volume_mm3"] for r in cls_rows
        )
        if total_vol_sum == 0:
            agg_dsc = empty_score
        else:
            agg_dsc = 2.0 * total_inter / total_vol_sum
        class_dscs.append(agg_dsc)

    mean_dsc = sum(class_dscs) / len(class_dscs)
    return {
        "class_1_agg_dsc": class_dscs[0],
        "class_2_agg_dsc": class_dscs[1],
        "mean_agg_dsc": mean_dsc,
    }


def compute_balanced_accuracy(staging_rows, team, stage_type):
    """Balanced accuracy: unweighted mean of per-class recall."""
    team_rows = [r for r in staging_rows if r["team"] == team]

    if stage_type == "T":
        true_key, pred_key = "T_true", "T_pred"
    else:
        true_key, pred_key = "N_true", "N_pred"

    gt_classes = sorted(set(r[true_key] for r in team_rows))

    recalls = []
    for cls in gt_classes:
        cls_rows = [r for r in team_rows if r[true_key] == cls]
        if len(cls_rows) == 0:
            continue
        correct = sum(1 for r in cls_rows if r[pred_key] == cls)
        recalls.append(correct / len(cls_rows))

    return sum(recalls) / len(recalls) if recalls else 0.0


def compute_concordance_index(surv_rows, team):
    """C-index with NaN-as-tied-prediction and hazard convention negation."""
    team_rows = [r for r in surv_rows if r["team"] == team]

    # Negate risk scores (hazard convention: higher risk = shorter survival)
    preds = []
    for row in team_rows:
        rs = row["risk_score"]
        preds.append(float("nan") if math.isnan(rs) else -rs)

    n = len(team_rows)
    num_pairs = 0.0
    num_correct = 0.0
    num_tied = 0.0

    for i in range(n):
        time_a = team_rows[i]["event_time"]
        event_a = team_rows[i]["event_observed"]
        pred_a = preds[i]

        for j in range(i + 1, n):
            time_b = team_rows[j]["event_time"]
            event_b = team_rows[j]["event_observed"]
            pred_b = preds[j]

            # Valid pair check
            if time_a == time_b:
                if event_a == event_b:
                    continue
            else:
                if event_a and event_b:
                    pass
                elif event_a and time_a < time_b:
                    pass
                elif event_b and time_b < time_a:
                    pass
                else:
                    continue

            num_pairs += 1.0

            # NaN predictions count as ties (Approach B)
            if math.isnan(pred_a) or math.isnan(pred_b):
                num_tied += 1
                continue

            if pred_a == pred_b:
                num_tied += 1
                continue

            if pred_a < pred_b:
                concordant = (
                    (time_a < time_b)
                    or (time_a == time_b and event_a and not event_b)
                )
            else:
                concordant = (
                    (time_a > time_b)
                    or (time_a == time_b and not event_a and event_b)
                )

            if concordant:
                num_correct += 1

    if num_pairs == 0:
        return 0.5

    return (num_correct + num_tied / 2.0) / num_pairs


# --------------- Main pipeline ---------------

def compute_team_results(seg_data, staging_data, surv_data, team, config):
    seg_res = compute_aggregated_dsc(seg_data, team, config)
    ba_T = compute_balanced_accuracy(staging_data, team, "T")
    ba_N = compute_balanced_accuracy(staging_data, team, "N")
    c_idx = compute_concordance_index(surv_data, team)

    seg_score = seg_res["mean_agg_dsc"]
    staging_score = (ba_T + ba_N) / 2.0
    prognosis_score = c_idx

    w_seg = config["weights"]["segmentation"]
    w_stg = config["weights"]["staging"]
    w_prg = config["weights"]["prognosis"]

    weighted = w_seg * seg_score + w_stg * staging_score + w_prg * prognosis_score
    unweighted = (seg_score + staging_score + prognosis_score) / 3.0
    consistency = abs(weighted - unweighted)

    return {
        "segmentation": seg_res,
        "staging": {
            "balanced_accuracy_T": ba_T,
            "balanced_accuracy_N": ba_N,
            "mean_balanced_accuracy": staging_score,
        },
        "prognosis": {"c_index": c_idx},
        "overall": {
            "segmentation_score": seg_score,
            "staging_score": staging_score,
            "prognosis_score": prognosis_score,
            "weighted_score": weighted,
            "unweighted_score": unweighted,
            "consistency": consistency,
        },
    }


def compute_rankings(results, teams):
    scored = [
        (t, results[t]["overall"]["weighted_score"],
         results[t]["overall"]["consistency"])
        for t in teams
    ]
    scored.sort(key=lambda x: (-x[1], x[2]))
    rankings = {}
    for rank, (team, _, _) in enumerate(scored, 1):
        rankings[team] = rank
        results[team]["overall"]["rank"] = rank
    return rankings


def compute_bootstrap_ci(seg_data, staging_data, surv_data, patients, config):
    boot_config = config["bootstrap"]
    random.seed(boot_config["seed"])
    n_iter = boot_config["n_iterations"]
    percentiles = boot_config["ci_percentiles"]
    teams = config["challenge"]["teams"]

    w_seg = config["weights"]["segmentation"]
    w_stg = config["weights"]["staging"]
    w_prg = config["weights"]["prognosis"]

    boot_vals = {t: {"seg": [], "staging": [], "prognosis": [], "weighted": []}
                 for t in teams}

    for _ in range(n_iter):
        boot_patients = [random.choice(patients) for _ in range(len(patients))]

        for team in teams:
            b_seg = []
            b_stg = []
            b_srv = []
            for bp in boot_patients:
                b_seg.extend(
                    r for r in seg_data
                    if r["team"] == team and r["patient_id"] == bp
                )
                b_stg.extend(
                    r for r in staging_data
                    if r["team"] == team and r["patient_id"] == bp
                )
                b_srv.extend(
                    r for r in surv_data
                    if r["team"] == team and r["patient_id"] == bp
                )

            seg_res = compute_aggregated_dsc(b_seg, team, config)
            ba_T = compute_balanced_accuracy(b_stg, team, "T")
            ba_N = compute_balanced_accuracy(b_stg, team, "N")
            c_idx = compute_concordance_index(b_srv, team)

            seg_s = seg_res["mean_agg_dsc"]
            stg_s = (ba_T + ba_N) / 2.0
            prg_s = c_idx
            w_s = w_seg * seg_s + w_stg * stg_s + w_prg * prg_s

            boot_vals[team]["seg"].append(seg_s)
            boot_vals[team]["staging"].append(stg_s)
            boot_vals[team]["prognosis"].append(prg_s)
            boot_vals[team]["weighted"].append(w_s)

    ci_results = {}
    for team in teams:
        ci = {}
        for metric in ["seg", "staging", "prognosis", "weighted"]:
            vals = sorted(boot_vals[team][metric])
            ci[metric] = {
                "lower": vals[int(percentiles[0] / 100.0 * n_iter)],
                "upper": vals[int(percentiles[1] / 100.0 * n_iter)],
            }
        ci_results[team] = ci

    return ci_results


def compute_rank_stability(seg_data, staging_data, surv_data, patients, config):
    stab_config = config["rank_stability"]
    random.seed(stab_config["seed"])
    n_iter = stab_config["n_iterations"]
    teams = config["challenge"]["teams"]
    n_teams = len(teams)

    w_seg = config["weights"]["segmentation"]
    w_stg = config["weights"]["staging"]
    w_prg = config["weights"]["prognosis"]

    rank_counts = {t: {r: 0 for r in range(1, n_teams + 1)} for t in teams}
    pairwise_wins = {t1: {t2: 0 for t2 in teams} for t1 in teams}

    for _ in range(n_iter):
        boot_patients = [random.choice(patients) for _ in range(len(patients))]
        boot_scores = {}

        for team in teams:
            b_seg = []
            b_stg = []
            b_srv = []
            for bp in boot_patients:
                b_seg.extend(
                    r for r in seg_data
                    if r["team"] == team and r["patient_id"] == bp
                )
                b_stg.extend(
                    r for r in staging_data
                    if r["team"] == team and r["patient_id"] == bp
                )
                b_srv.extend(
                    r for r in surv_data
                    if r["team"] == team and r["patient_id"] == bp
                )

            seg_res = compute_aggregated_dsc(b_seg, team, config)
            ba_T = compute_balanced_accuracy(b_stg, team, "T")
            ba_N = compute_balanced_accuracy(b_stg, team, "N")
            c_idx = compute_concordance_index(b_srv, team)

            seg_s = seg_res["mean_agg_dsc"]
            stg_s = (ba_T + ba_N) / 2.0
            prg_s = c_idx
            w_s = w_seg * seg_s + w_stg * stg_s + w_prg * prg_s
            boot_scores[team] = w_s

        sorted_teams = sorted(teams, key=lambda t: -boot_scores[t])
        for rank, team in enumerate(sorted_teams, 1):
            rank_counts[team][rank] += 1

        for t1 in teams:
            for t2 in teams:
                if t1 != t2 and boot_scores[t1] > boot_scores[t2]:
                    pairwise_wins[t1][t2] += 1

    rank_prob = {}
    for team in teams:
        rank_prob[team] = {
            str(r): rank_counts[team][r] / n_iter
            for r in range(1, n_teams + 1)
        }

    dominant_rank = {}
    rank_certainty = {}
    for team in teams:
        best_rank = max(range(1, n_teams + 1),
                        key=lambda r: rank_counts[team][r])
        dominant_rank[team] = best_rank
        rank_certainty[team] = rank_counts[team][best_rank] / n_iter

    pairwise_dominance = {}
    for t1 in teams:
        pairwise_dominance[t1] = {}
        for t2 in teams:
            if t1 == t2:
                pairwise_dominance[t1][t2] = 0.5
            else:
                pairwise_dominance[t1][t2] = pairwise_wins[t1][t2] / n_iter

    return {
        "rank_probability_matrix": rank_prob,
        "dominant_rank": dominant_rank,
        "rank_certainty": rank_certainty,
        "pairwise_dominance": pairwise_dominance,
    }


def main():
    config = load_config(CONFIG_PATH)
    teams = config["challenge"]["teams"]

    conn = sqlite3.connect(DB_PATH)
    seg_data, staging_data, surv_data, patients = load_data(conn)
    conn.close()

    # Compute per-team results
    results = {}
    for team in teams:
        results[team] = compute_team_results(
            seg_data, staging_data, surv_data, team, config
        )

    # Rankings
    rankings = compute_rankings(results, teams)

    # Bootstrap CIs
    ci_results = compute_bootstrap_ci(
        seg_data, staging_data, surv_data, patients, config
    )
    for team in teams:
        results[team]["bootstrap_ci"] = ci_results[team]

    # Write results.json
    output = {"teams": results, "rankings": rankings}
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results written to {RESULTS_PATH}")
    for team in teams:
        r = results[team]["overall"]
        print(f"  {team}: rank={r['rank']}, weighted={r['weighted_score']:.4f}")

    # Rank stability analysis
    stability = compute_rank_stability(
        seg_data, staging_data, surv_data, patients, config
    )
    with open(STABILITY_PATH, "w") as f:
        json.dump(stability, f, indent=2)

    print(f"Stability analysis written to {STABILITY_PATH}")


if __name__ == "__main__":
    main()
