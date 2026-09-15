#!/usr/bin/env python3
"""NIST GenAI Discriminator Evaluation -- Metrics Computation

Reads validated submissions from the evaluation database, computes
performance metrics, and writes results to both the database metrics
table and the output JSON file.
"""

import argparse
import json
import os
import sqlite3
import sys

# Load pipeline configuration
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
with open(_CONFIG_PATH) as _f:
    CONFIG = json.load(_f)


def connect_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_valid_submissions(conn):
    """Return valid submissions as list of (file_stem, eval_set, team)."""
    rows = conn.execute(
        "SELECT file_stem, eval_set, team FROM submissions WHERE is_valid = 1"
    ).fetchall()
    return [(r["file_stem"], r["eval_set"], r["team"]) for r in rows]


def load_evaluation_data(conn, file_stem, eval_set):
    """Load predictions joined with ground truth for one submission.

    Returns list of dicts with keys: ai_likelihood, believability,
    true_source, human_believability
    """
    rows = conn.execute("""
        SELECT p.ai_likelihood, p.believability,
               g.true_source, g.human_believability
        FROM predictions p
        JOIN ground_truth g
          ON g.narrative_id = p.narrative_id AND g.set_name = ?
        WHERE p.file_stem = ? AND p.ai_likelihood IS NOT NULL
    """, (eval_set, file_stem)).fetchall()
    return [dict(r) for r in rows]


def compute_discrimination(positives, negatives):
    """Concordance probability between positive and negative score distributions.

    Equivalent to the Wilcoxon-Mann-Whitney U-statistic normalized to [0, 1].
    Tied pairs contribute half weight to concordance.

    Args:
        positives: scores for positive-class instances (AI-generated)
        negatives: scores for negative-class instances (human-written)
    Returns:
        float in [0, 1] or None if undefined
    """
    if not positives or not negatives:
        return None
    concordant = 0
    total = len(positives) * len(negatives)
    for p in positives:
        for n in negatives:
            if p > n:
                concordant += 1
            elif p == n:
                concordant += 0.5
    return concordant / total


def compute_accuracy_error(predictions_labels):
    """Sample mean squared prediction error with bias correction.

    Uses Bessel's correction (n-1 denominator) for an unbiased estimate
    of the population prediction variance.

    Args:
        predictions_labels: list of (predicted_score, true_binary_label)
    Returns:
        float >= 0
    """
    n = len(predictions_labels)
    if n <= 1:
        return 0.0
    total = sum((pred - label) ** 2 for pred, label in predictions_labels)
    return total / (n - 1)


def compute_calibration_error(predictions_labels):
    """Expected calibration error with equal-width binning.

    Partitions [0, 1] into equal-width bins as specified by the pipeline
    configuration, then computes the weighted average absolute gap between
    predicted confidence and observed positive frequency.

    Args:
        predictions_labels: list of (predicted_score, true_binary_label)
    Returns:
        float >= 0
    """
    n_bins = CONFIG["ece_bins"]
    bins = [[] for _ in range(n_bins)]
    for pred, label in predictions_labels:
        idx = min(int(pred * n_bins), n_bins - 1)
        bins[idx].append((pred, label))

    total_samples = len(predictions_labels)
    ece = 0.0
    for bin_items in bins:
        if not bin_items:
            continue
        avg_conf = sum(p for p, _ in bin_items) / len(bin_items)
        avg_acc = sum(l for _, l in bin_items) / len(bin_items)
        ece += (len(bin_items) / total_samples) * abs(avg_conf - avg_acc)
    return ece


def evaluate_submission(conn, file_stem, eval_set, team):
    """Evaluate a single submission. Returns metrics dict or None."""
    data = load_evaluation_data(conn, file_stem, eval_set)
    if not data:
        return None

    pos_scores = [d["ai_likelihood"] for d in data if d["true_source"] == "ai"]
    neg_scores = [d["ai_likelihood"] for d in data if d["true_source"] == "human"]
    pred_labels = [
        (d["ai_likelihood"], 1 if d["true_source"] == "ai" else 0)
        for d in data
    ]

    disc = compute_discrimination(pos_scores, neg_scores)
    acc_err = compute_accuracy_error(pred_labels)
    cal_err = compute_calibration_error(pred_labels)

    bel_all = [d["believability"] for d in data if d["believability"] is not None]
    bel_human = [d["believability"] for d in data
                 if d["true_source"] == "human" and d["believability"] is not None]
    bel_ai = [d["believability"] for d in data
              if d["true_source"] == "ai" and d["believability"] is not None]

    over_deception = disc is not None and disc < CONFIG["over_deception_threshold"]

    if disc is not None:
        w = CONFIG["composite_weights"]
        composite = (w["discrimination"] * disc +
                     w["accuracy"] * (1 - acc_err) +
                     w["calibration"] * (1 - cal_err))
    else:
        composite = None

    def safe_mean(lst):
        return sum(lst) / len(lst) if lst else None

    precision = CONFIG["rounding_precision"]
    return {
        "eval_set": eval_set,
        "team": team,
        "n_predictions": len(data),
        "auc_roc": round(disc, precision) if disc is not None else None,
        "brier_score": round(acc_err, precision),
        "ece": round(cal_err, precision),
        "mean_believability": round(safe_mean(bel_all), precision) if bel_all else None,
        "max_believability": round(max(bel_all), precision) if bel_all else None,
        "mean_human_believability": round(safe_mean(bel_human), precision) if bel_human else None,
        "mean_ai_believability": round(safe_mean(bel_ai), precision) if bel_ai else None,
        "over_deception": over_deception,
        "composite_score": round(composite, precision) if composite is not None else None,
    }


def store_metrics(conn, metrics):
    """Write computed metrics into the database metrics table."""
    for stem, m in metrics.items():
        conn.execute("""
            INSERT OR REPLACE INTO metrics
            (file_stem, eval_set, team, n_predictions, auc_roc, brier_score,
             ece, mean_believability, max_believability, mean_human_believability,
             over_deception, composite_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stem, m["eval_set"], m["team"], m["n_predictions"],
            m["auc_roc"], m["brier_score"], m["ece"],
            m["mean_believability"], m["max_believability"],
            m["mean_human_believability"],
            1 if m["over_deception"] else 0,
            m["composite_score"]
        ))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Compute evaluation metrics")
    parser.add_argument("--db", required=True, help="Path to evaluation SQLite database")
    parser.add_argument("--output", required=True, help="Output directory for JSON files")
    args = parser.parse_args()

    conn = connect_db(args.db)
    submissions = get_valid_submissions(conn)

    if not submissions:
        print("No valid submissions found", file=sys.stderr)
        sys.exit(1)

    metrics = {}
    for file_stem, eval_set, team in submissions:
        result = evaluate_submission(conn, file_stem, eval_set, team)
        if result:
            metrics[file_stem] = result

    # Write to JSON output
    os.makedirs(args.output, exist_ok=True)
    with open(os.path.join(args.output, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    # Write to database for ranking stage
    store_metrics(conn, metrics)
    conn.close()

    print(f"Computed metrics for {len(metrics)} submissions")


if __name__ == "__main__":
    main()
