#!/usr/bin/env python3
"""Clinical challenge evaluation engine.

Reads submission data from the SQLite database at /app/submissions.db
and produces evaluation results at /app/results.json.

Ported from the original MATLAB reference implementation.
"""

import sqlite3
import json
import math
import random

DB_PATH = "/app/submissions.db"
OUTPUT_PATH = "/app/results.json"


def get_connection():
    return sqlite3.connect(DB_PATH)


def fetch_teams(conn):
    rows = conn.execute(
        "SELECT DISTINCT team FROM segmentation_stats ORDER BY team"
    ).fetchall()
    return [r[0] for r in rows]


def fetch_patients(conn):
    rows = conn.execute(
        "SELECT DISTINCT patient_id FROM segmentation_stats ORDER BY patient_id"
    ).fetchall()
    return [r[0] for r in rows]


def evaluate_segmentation(conn, team):
    """Compute Dice similarity coefficient per class."""
    results = {}
    for cls in [1, 2]:
        rows = conn.execute(
            "SELECT gt_volume_mm3, pred_volume_mm3, intersection_volume_mm3 "
            "FROM segmentation_stats WHERE team=? AND class=?",
            (team, cls)
        ).fetchall()

        dice_scores = []
        for gt_vol, pred_vol, inter_vol in rows:
            denominator = gt_vol + pred_vol
            if denominator == 0.0:
                dice_scores.append(1.0)
            else:
                dice_scores.append(2.0 * inter_vol / denominator)

        results[cls] = sum(dice_scores) / len(dice_scores) if dice_scores else 0.0

    mean_dsc = (results[1] + results[2]) / 2.0
    return {
        "class_1_agg_dsc": results[1],
        "class_2_agg_dsc": results[2],
        "mean_agg_dsc": mean_dsc,
    }


def evaluate_staging(conn, team):
    """Compute accuracy for T and N staging predictions."""
    rows = conn.execute(
        "SELECT T_true, T_pred, N_true, N_pred FROM staging WHERE team=?",
        (team,)
    ).fetchall()

    n = len(rows)
    t_correct = sum(1 for r in rows if r[0] == r[1])
    n_correct = sum(1 for r in rows if r[2] == r[3])

    ba_t = t_correct / n
    ba_n = n_correct / n

    return {
        "balanced_accuracy_T": ba_t,
        "balanced_accuracy_N": ba_n,
        "mean_balanced_accuracy": (ba_t + ba_n) / 2.0,
    }


def evaluate_prognosis(conn, team):
    """Compute concordance index for survival predictions."""
    rows = conn.execute(
        "SELECT event_time, event_observed, risk_score "
        "FROM survival WHERE team=?",
        (team,)
    ).fetchall()

    # Parse valid predictions, skip missing values
    data = []
    for event_time, event_obs, risk_str in rows:
        try:
            risk = float(risk_str)
            if math.isnan(risk):
                continue
        except (ValueError, TypeError):
            continue
        data.append((event_time, int(event_obs), risk))

    n = len(data)
    num_pairs = 0
    num_concordant = 0
    num_tied = 0

    for i in range(n):
        t_i, e_i, p_i = data[i]
        for j in range(i + 1, n):
            t_j, e_j, p_j = data[j]

            # Check admissibility
            if t_i == t_j:
                if e_i == e_j:
                    continue
            else:
                if e_i and e_j:
                    pass
                elif e_i and t_i < t_j:
                    pass
                elif e_j and t_j < t_i:
                    pass
                else:
                    continue

            num_pairs += 1

            if p_i == p_j:
                num_tied += 1
                continue

            if p_i < p_j:
                is_concordant = (t_i < t_j) or (t_i == t_j and e_i and not e_j)
            else:
                is_concordant = (t_i > t_j) or (t_i == t_j and not e_i and e_j)

            if is_concordant:
                num_concordant += 1

    if num_pairs == 0:
        return 0.5

    return (num_concordant + num_tied / 2.0) / num_pairs


def compute_rankings(team_results, teams):
    """Rank teams by weighted score with consistency tie-breaking."""
    items = [
        (t, team_results[t]["overall"]["weighted_score"],
         team_results[t]["overall"]["consistency"])
        for t in teams
    ]
    items.sort(key=lambda x: (-x[1], x[2]))

    rankings = {}
    for rank, (team, _, _) in enumerate(items, 1):
        rankings[team] = rank
        team_results[team]["overall"]["rank"] = rank
    return rankings


def compute_bootstrap_ci(conn, teams):
    """Compute 95% bootstrap confidence intervals."""
    random.seed(42)
    n_iter = 1000

    # Pre-load per-team data for efficiency
    seg_cache = {}
    stg_cache = {}
    srv_cache = {}

    for team in teams:
        seg_cache[team] = conn.execute(
            "SELECT class, gt_volume_mm3, pred_volume_mm3, "
            "intersection_volume_mm3 FROM segmentation_stats WHERE team=?",
            (team,)
        ).fetchall()

        stg_cache[team] = conn.execute(
            "SELECT T_true, T_pred, N_true, N_pred "
            "FROM staging WHERE team=?", (team,)
        ).fetchall()

        srv_cache[team] = conn.execute(
            "SELECT event_time, event_observed, risk_score "
            "FROM survival WHERE team=?", (team,)
        ).fetchall()

    boot_results = {
        t: {"seg": [], "staging": [], "prognosis": [], "weighted": []}
        for t in teams
    }

    for _ in range(n_iter):
        for team in teams:
            ns = len(seg_cache[team])
            nt = len(stg_cache[team])
            nv = len(srv_cache[team])

            b_seg = [seg_cache[team][random.randint(0, ns - 1)]
                     for _ in range(ns)]
            b_stg = [stg_cache[team][random.randint(0, nt - 1)]
                     for _ in range(nt)]
            b_srv = [srv_cache[team][random.randint(0, nv - 1)]
                     for _ in range(nv)]

            # Segmentation: per-patient Dice average
            cls_scores = {}
            for cls in [1, 2]:
                cls_rows = [r for r in b_seg if r[0] == cls]
                dscs = []
                for r in cls_rows:
                    denom = r[1] + r[2]
                    if denom == 0:
                        dscs.append(1.0)
                    else:
                        dscs.append(2.0 * r[3] / denom)
                cls_scores[cls] = (sum(dscs) / len(dscs)) if dscs else 0.0
            seg_s = (cls_scores[1] + cls_scores[2]) / 2.0

            # Staging: simple accuracy
            tc = sum(1 for r in b_stg if r[0] == r[1])
            nc = sum(1 for r in b_stg if r[2] == r[3])
            stg_s = (tc / len(b_stg) + nc / len(b_stg)) / 2.0

            # Prognosis: concordance without negation, NaN dropped
            valid = []
            for r in b_srv:
                try:
                    rs = float(r[2])
                    if math.isnan(rs):
                        continue
                except (ValueError, TypeError):
                    continue
                valid.append((r[0], int(r[1]), rs))

            nb = len(valid)
            npairs = ncorr = ntied = 0
            for i in range(nb):
                for j in range(i + 1, nb):
                    ti, ei, pi_ = valid[i]
                    tj, ej, pj = valid[j]
                    if ti == tj:
                        if ei == ej:
                            continue
                    else:
                        if ei and ej:
                            pass
                        elif ei and ti < tj:
                            pass
                        elif ej and tj < ti:
                            pass
                        else:
                            continue
                    npairs += 1
                    if pi_ == pj:
                        ntied += 1
                        continue
                    if pi_ < pj:
                        c = (ti < tj) or (ti == tj and ei and not ej)
                    else:
                        c = (ti > tj) or (ti == tj and not ei and ej)
                    if c:
                        ncorr += 1

            prg_s = (ncorr + ntied / 2.0) / npairs if npairs > 0 else 0.5
            w_s = 0.25 * seg_s + 0.35 * stg_s + 0.40 * prg_s

            boot_results[team]["seg"].append(seg_s)
            boot_results[team]["staging"].append(stg_s)
            boot_results[team]["prognosis"].append(prg_s)
            boot_results[team]["weighted"].append(w_s)

    ci_output = {}
    for team in teams:
        ci = {}
        for metric in ["seg", "staging", "prognosis", "weighted"]:
            vals = sorted(boot_results[team][metric])
            ci[metric] = {
                "lower": vals[int(0.025 * n_iter)],
                "upper": vals[int(0.975 * n_iter)],
            }
        ci_output[team] = ci

    return ci_output


def main():
    conn = get_connection()
    teams = fetch_teams(conn)

    team_results = {}
    for team in teams:
        seg = evaluate_segmentation(conn, team)
        stg = evaluate_staging(conn, team)
        c_idx = evaluate_prognosis(conn, team)

        seg_score = seg["mean_agg_dsc"]
        staging_score = stg["mean_balanced_accuracy"]
        prognosis_score = c_idx

        weighted = (0.25 * seg_score + 0.35 * staging_score +
                    0.40 * prognosis_score)
        unweighted = (seg_score + staging_score + prognosis_score) / 3.0
        consistency = abs(weighted - unweighted)

        team_results[team] = {
            "segmentation": seg,
            "staging": stg,
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

    rankings = compute_rankings(team_results, teams)
    ci_results = compute_bootstrap_ci(conn, teams)

    for team in teams:
        team_results[team]["bootstrap_ci"] = ci_results[team]

    output = {"teams": team_results, "rankings": rankings}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results written to {OUTPUT_PATH}")
    for team in teams:
        ovr = team_results[team]["overall"]
        print(f"  {team}: rank={ovr['rank']}, "
              f"weighted={ovr['weighted_score']:.4f}")

    conn.close()


if __name__ == "__main__":
    main()
