#!/usr/bin/env python3
"""Complete NIST GenAI Discriminator Evaluation — reference implementation.

Bypasses the broken pipeline and directly processes prediction files against
ground truth to produce correct validation, metrics, and ranking outputs.
"""

import json
import os
import glob

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
GROUND_TRUTH_PATH = os.path.join(DATA_DIR, "ground_truth.json")
PREDICTIONS_DIR = os.path.join(DATA_DIR, "predictions")

# Correct evaluation parameters (overriding broken config.json)
N_BINS = 10
COMPOSITE_WEIGHTS = (0.4, 0.3, 0.3)
OVER_DECEPTION_THRESHOLD = 0.5
ROUNDING = 6


def load_ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        data = json.load(f)
    return data["eval_sets"]


def validate_prediction_file(filepath):
    """Validate a prediction file against NIST submission format.
    Returns (valid, errors_list).
    """
    errors = []
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, [f"Invalid JSON: {e}"]

    for field in ["team", "docker_id", "input", "prediction_list", "execution_time"]:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if "prediction_list" not in data:
        return False, errors

    for i, entry in enumerate(data["prediction_list"]):
        for field in ["statement_id", "ai_likelihood_score", "believability_score"]:
            if field not in entry:
                errors.append(f"Entry {i}: missing field {field}")

        if "ai_likelihood_score" in entry:
            score = entry["ai_likelihood_score"]
            if not isinstance(score, (int, float)) or score < 0 or score > 1:
                errors.append(
                    f"Entry {i}: ai_likelihood_score {score} out of range [0,1]"
                )

        if "believability_score" in entry:
            score = entry["believability_score"]
            if not isinstance(score, (int, float)) or score < 0 or score > 1:
                errors.append(
                    f"Entry {i}: believability_score {score} out of range [0,1]"
                )

    return len(errors) == 0, errors


def compute_auc(positives, negatives):
    """Concordance probability (AUC-ROC via Mann-Whitney U).
    Tied pairs contribute 0.5.
    """
    if not positives or not negatives:
        return None
    concordant = 0.0
    total = len(positives) * len(negatives)
    for p in positives:
        for n in negatives:
            if p > n:
                concordant += 1.0
            elif p == n:
                concordant += 0.5
    return concordant / total


def compute_brier(predictions_labels):
    """Brier score: (1/n) * sum((pred - label)^2).
    Uses n denominator (population MSE), NOT n-1 (Bessel's correction).
    """
    n = len(predictions_labels)
    if n == 0:
        return 0.0
    return sum((p - y) ** 2 for p, y in predictions_labels) / n


def compute_ece(predictions_labels, n_bins=10):
    """Expected Calibration Error with equal-width binning.
    Standard: 10 bins (decile), scores of exactly 1.0 go in last bin.
    """
    bins = [[] for _ in range(n_bins)]
    for pred, label in predictions_labels:
        idx = min(int(pred * n_bins), n_bins - 1)
        bins[idx].append((pred, label))

    total = len(predictions_labels)
    ece = 0.0
    for bin_items in bins:
        if not bin_items:
            continue
        avg_conf = sum(p for p, _ in bin_items) / len(bin_items)
        avg_acc = sum(y for _, y in bin_items) / len(bin_items)
        ece += (len(bin_items) / total) * abs(avg_conf - avg_acc)
    return ece


def evaluate_submission(pred_data, ground_truth_sets):
    """Evaluate a single validated prediction file."""
    eval_set_name = pred_data["input"]
    if eval_set_name not in ground_truth_sets:
        return None

    gt = ground_truth_sets[eval_set_name]["labels"]
    team = pred_data["team"]

    matched = []
    for entry in pred_data["prediction_list"]:
        nid = entry["statement_id"]
        if nid in gt:
            matched.append({
                "ai_likelihood": entry["ai_likelihood_score"],
                "believability": entry["believability_score"],
                "true_source": gt[nid]["true_source"],
                "human_believability": gt[nid]["human_believability"],
            })

    if not matched:
        return None

    pos_scores = [d["ai_likelihood"] for d in matched if d["true_source"] == "ai"]
    neg_scores = [d["ai_likelihood"] for d in matched if d["true_source"] == "human"]
    pred_labels = [
        (d["ai_likelihood"], 1 if d["true_source"] == "ai" else 0)
        for d in matched
    ]

    auc = compute_auc(pos_scores, neg_scores)
    brier = compute_brier(pred_labels)
    ece = compute_ece(pred_labels, N_BINS)

    bel_all = [d["believability"] for d in matched]
    bel_human = [d["believability"] for d in matched if d["true_source"] == "human"]
    bel_ai = [d["believability"] for d in matched if d["true_source"] == "ai"]

    over_deception = auc is not None and auc < OVER_DECEPTION_THRESHOLD

    if auc is not None:
        w_disc, w_acc, w_cal = COMPOSITE_WEIGHTS
        composite = w_disc * auc + w_acc * (1 - brier) + w_cal * (1 - ece)
    else:
        composite = None

    def safe_mean(lst):
        return sum(lst) / len(lst) if lst else None

    return {
        "eval_set": eval_set_name,
        "team": team,
        "n_predictions": len(matched),
        "auc_roc": round(auc, ROUNDING) if auc is not None else None,
        "brier_score": round(brier, ROUNDING),
        "ece": round(ece, ROUNDING),
        "mean_believability": round(safe_mean(bel_all), ROUNDING) if bel_all else None,
        "max_believability": round(max(bel_all), ROUNDING) if bel_all else None,
        "mean_human_believability": (
            round(safe_mean(bel_human), ROUNDING) if bel_human else None
        ),
        "mean_ai_believability": (
            round(safe_mean(bel_ai), ROUNDING) if bel_ai else None
        ),
        "over_deception": over_deception,
        "composite_score": (
            round(composite, ROUNDING) if composite is not None else None
        ),
    }


def main():
    ground_truth_sets = load_ground_truth()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Phase 1: Validate all prediction files
    validation_report = {}
    valid_predictions = {}

    for filepath in sorted(glob.glob(os.path.join(PREDICTIONS_DIR, "*.json"))):
        stem = os.path.basename(filepath).replace(".json", "")
        valid, errors = validate_prediction_file(filepath)
        validation_report[stem] = {"valid": valid, "errors": errors}
        if valid:
            with open(filepath) as f:
                valid_predictions[stem] = json.load(f)

    with open(os.path.join(OUTPUT_DIR, "validation_report.json"), "w") as f:
        json.dump(validation_report, f, indent=2)

    # Phase 2: Compute metrics for valid submissions only
    metrics = {}
    for stem, pred_data in valid_predictions.items():
        result = evaluate_submission(pred_data, ground_truth_sets)
        if result:
            metrics[stem] = result

    with open(os.path.join(OUTPUT_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    # Phase 3: Generate rankings (descending composite, exclude nulls)
    rankable = [
        (stem, m) for stem, m in metrics.items()
        if m["composite_score"] is not None
    ]
    rankable.sort(key=lambda x: x[1]["composite_score"], reverse=True)

    rankings = []
    for i, (stem, m) in enumerate(rankable):
        rankings.append({
            "rank": i + 1,
            "name": stem,
            "team": m["team"],
            "eval_set": m["eval_set"],
            "composite_score": m["composite_score"],
            "auc_roc": m["auc_roc"],
            "brier_score": m["brier_score"],
            "ece": m["ece"],
        })

    with open(os.path.join(OUTPUT_DIR, "rankings.json"), "w") as f:
        json.dump(rankings, f, indent=2)

    print(
        f"Evaluation complete: {len(validation_report)} files validated, "
        f"{len(metrics)} metrics computed, {len(rankings)} ranked"
    )


if __name__ == "__main__":
    main()
