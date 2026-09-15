#!/usr/bin/env python3
"""ML Research Integrity Pipeline — Forensic audit across heterogeneous data formats."""

import json
import os
import re
import sqlite3
from pathlib import Path

import numpy as np
import h5py
import duckdb
import pyarrow.parquet as pq_mod
from scipy import stats

try:
    import yaml
    def load_yaml(path):
        with open(path) as f:
            return yaml.safe_load(f)
except ImportError:
    def load_yaml(path):
        result = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip()
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                    result[key.strip()] = val
        return result


EXPERIMENTS_DIR = "/app/experiments"
DB_PATH = "/app/experiments.db"
REF_PATH = "/app/reference.duckdb"
REPORT_PATH = "/app/audit_report.json"

# ── Regex for text-log parsing ──────────────────────────────────────

ACC_TOTAL_RE = re.compile(
    r"CNN:\s*\{[^}]*'total':\s*(?:np\.float64\()?([0-9]+(?:\.[0-9]+)?)(?:\))?",
    re.IGNORECASE,
)
AVG_ACC_RE = re.compile(
    r"Average Accuracy \(CNN\):\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
SEED_RE = re.compile(
    r"\bseed\s*[:=]\s*(\d+)|\bseed\s*\[(\d+)\]",
    re.IGNORECASE,
)


# ── Database context loading ────────────────────────────────────────

def load_context():
    """Load experiment metadata, claimed results, and integrity rules from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT experiment_id, metric_name, metric_value FROM claimed_results")
    claimed = {}
    for eid, mname, mval in c.fetchall():
        claimed.setdefault(eid, {})[mname] = mval

    c.execute("SELECT experiment_id, dataset, model, num_tasks FROM experiments")
    meta = {}
    for eid, dataset, model, ntasks in c.fetchall():
        meta[eid] = {"dataset": dataset, "model": model, "num_tasks": ntasks}

    c.execute("SELECT rule_name, applies_to, detection_guidance FROM integrity_rules")
    rules = {}
    for rname, applies, guidance in c.fetchall():
        rules[rname] = {"applies_to": applies, "guidance": guidance}

    conn.close()
    return claimed, meta, rules


def load_training_profiles():
    """Load reference training profiles from DuckDB for optimizer comparison."""
    if not os.path.exists(REF_PATH):
        return {}
    con = duckdb.connect(REF_PATH, read_only=True)
    try:
        rows = con.execute(
            "SELECT optimizer, metric_name, statistic, value "
            "FROM reference_training_profiles"
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()

    profiles = {}
    for opt, metric, stat, val in rows:
        profiles.setdefault(opt, {}).setdefault(metric, {})[stat] = val
    return profiles


# ── Format-specific parsers ─────────────────────────────────────────

def parse_hdf5(h5_path):
    """Parse HDF5 metrics file, returning loss curve, gradient norms, and metrics."""
    with h5py.File(h5_path, "r") as f:
        epoch_loss = f["training/epoch_loss"][:]
        task_accuracy = f["evaluation/task_accuracy"][:]
        avg_accuracy = f["evaluation/avg_accuracy"][:]
        gradient_norms = None
        if "training/gradient_norms" in f:
            gradient_norms = f["training/gradient_norms"][:]

    return {
        "epoch_loss": epoch_loss,
        "gradient_norms": gradient_norms,
        "final_accuracy": float(task_accuracy[-1]),
        "final_aaa": float(avg_accuracy[-1]),
    }


def parse_parquet(pq_path):
    """Parse Parquet evaluation scores, computing recall@1 per modality."""
    table = pq_mod.read_table(pq_path)
    data = table.to_pydict()

    metrics = {}
    scores_by_modality = {}

    for mod_key, metric_prefix in [("text", "txt"), ("image", "img")]:
        relevant = []
        scores = []
        for m, r, s in zip(data["modality"], data["top1_relevant"], data["top1_score"]):
            if m == mod_key:
                relevant.append(r)
                scores.append(s)

        if relevant:
            recall = sum(relevant) / len(relevant) * 100.0
            metrics[f"{metric_prefix}_r1"] = recall

        if scores:
            scores_by_modality[mod_key] = scores

    return metrics, scores_by_modality


def parse_text_log(log_path, expected_n_tasks=None):
    """Parse text training log with seed-delimited multi-run segmentation."""
    text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    seed_marks = list(SEED_RE.finditer(text))

    segments = []
    if seed_marks:
        for i, m in enumerate(seed_marks):
            start = m.start()
            end = seed_marks[i + 1].start() if i + 1 < len(seed_marks) else len(text)
            segments.append((start, end))
    else:
        segments = [(0, len(text))]

    # Search from last segment backward for a complete run
    for start, end in reversed(segments):
        segment = text[start:end]
        acc_values = ACC_TOTAL_RE.findall(segment)
        avg_values = AVG_ACC_RE.findall(segment)
        if not acc_values or not avg_values:
            continue
        if expected_n_tasks is not None and len(avg_values) < expected_n_tasks:
            continue

        all_accs = [float(v) for v in acc_values]
        final_acc = all_accs[-1]
        final_aaa = float(avg_values[-1])

        return {
            "final_accuracy": final_acc,
            "final_aaa": final_aaa,
            "all_accuracies": all_accs,
        }

    return None


def parse_jsonl(eval_path):
    """Parse JSONL evaluation file, using the last valid record."""
    records = []
    with open(eval_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        return None

    last = records[-1]
    metrics = {}
    for key in ("txt_r1", "txt_r5", "txt_r10", "img_r1", "img_r5", "img_r10"):
        if key in last:
            metrics[key] = float(last[key])
    return metrics


# ── Integrity checks ───────────────────────────────────────────────

def check_curve_authenticity(epoch_loss):
    """Detect fabricated training curves by analyzing serial correlation of loss deltas.

    Real SGD produces approximately uncorrelated or negatively correlated
    consecutive loss changes. A smooth fabricated curve yields strongly
    positive lag-1 autocorrelation in the first differences.
    """
    diffs = np.diff(epoch_loss)
    if len(diffs) < 3:
        return False, 0.0
    std = np.std(diffs)
    if std < 1e-15:
        return True, 1.0
    autocorr = float(np.corrcoef(diffs[:-1], diffs[1:])[0, 1])
    # Positive autocorrelation above 0.3 indicates deterministic generation
    return autocorr > 0.3, autocorr


def check_gradient_consistency(gradient_norms):
    """Detect fabricated gradient norms by checking coefficient of variation.

    Genuine SGD training produces gradient norms with significant variation
    due to mini-batch sampling and the changing loss landscape curvature.
    Constant or near-constant gradient norms are physically impossible
    under stochastic optimization.
    """
    if gradient_norms is None or len(gradient_norms) < 10:
        return False, None
    mean_norm = float(np.mean(gradient_norms))
    if mean_norm < 1e-10:
        return True, 0.0
    cv = float(np.std(gradient_norms) / mean_norm)
    # SGD gradient norms should have CV > 0.1 (typically 0.2-0.5)
    # Constant/near-constant norms (CV < 0.05) indicate fabrication
    return cv < 0.05, cv


def check_distribution_conformance(exp_scores_by_modality, dataset, model_class):
    """Compare experiment score distributions against DuckDB reference via KS test."""
    if not os.path.exists(REF_PATH):
        return []

    con = duckdb.connect(REF_PATH, read_only=True)
    violations = []

    for modality, exp_scores in exp_scores_by_modality.items():
        if not exp_scores:
            continue
        ref_result = con.execute(
            "SELECT score FROM reference_scores "
            "WHERE dataset=? AND model_class=? AND modality=?",
            [dataset, model_class, modality],
        ).fetchall()
        ref_scores = [r[0] for r in ref_result]

        if not ref_scores:
            continue

        ks_stat, p_value = stats.ks_2samp(exp_scores, ref_scores)
        if p_value < 0.01:
            violations.append({
                "modality": modality,
                "ks_stat": ks_stat,
                "p_value": p_value,
            })

    con.close()
    return violations


def check_progression_plausibility(all_accuracies, threshold=30.0):
    """Detect implausibly large single-step accuracy increases."""
    jumps = []
    for i in range(1, len(all_accuracies)):
        jump = all_accuracies[i] - all_accuracies[i - 1]
        if jump > threshold:
            jumps.append((i - 1, i, all_accuracies[i - 1], all_accuracies[i], jump))
    return jumps


def check_metric_consistency(metrics, claimed, pct_tol=0.5, ratio_tol=0.05):
    """Cross-validate extracted metrics against claimed values."""
    mismatches = []
    for key, claimed_val in claimed.items():
        if key not in metrics:
            continue
        actual = metrics[key]
        tol = pct_tol if abs(claimed_val) > 1.0 else ratio_tol
        diff = abs(actual - claimed_val)
        if diff > tol:
            mismatches.append((key, actual, claimed_val, diff))
    return mismatches


def check_artifact_integrity(exp_dir):
    """Detect .patch or .diff files indicating grading script modification."""
    patches = []
    for f in os.listdir(exp_dir):
        if f.endswith(".patch") or f.endswith(".diff"):
            patches.append(f)
    return patches


# ── Main audit orchestration ───────────────────────────────────────

def audit_experiment(exp_id, exp_dir, claimed, meta, rules):
    """Run all applicable integrity checks on a single experiment."""
    violations = []
    metrics = {}

    h5_path = os.path.join(exp_dir, "metrics.h5")
    pq_path = os.path.join(exp_dir, "eval_scores.parquet")
    log_path = os.path.join(exp_dir, "training.log")
    jsonl_path = os.path.join(exp_dir, "evaluate.txt")

    exp_meta = meta.get(exp_id, {})
    exp_claimed = claimed.get(exp_id, {})

    scores_by_modality = {}

    # ── Parse HDF5 artifacts ───────────────────────────────────────
    if os.path.exists(h5_path):
        parsed = parse_hdf5(h5_path)
        metrics["final_accuracy"] = parsed["final_accuracy"]
        metrics["final_aaa"] = parsed["final_aaa"]

        # Check loss curve autocorrelation structure
        is_loss_fabricated, autocorr = check_curve_authenticity(parsed["epoch_loss"])

        # Check gradient norm consistency with claimed optimizer
        is_gradient_suspicious, grad_cv = check_gradient_consistency(
            parsed.get("gradient_norms")
        )

        if is_loss_fabricated or is_gradient_suspicious:
            detail_parts = []
            if is_loss_fabricated:
                detail_parts.append(
                    f"Loss curve lag-1 autocorrelation of first differences: "
                    f"{autocorr:.4f}, indicating synthetic deterministic generation"
                )
            if is_gradient_suspicious:
                detail_parts.append(
                    f"Gradient norm CV: {grad_cv:.4f} — near-zero variation is "
                    f"inconsistent with stochastic optimization where mini-batch "
                    f"sampling produces inherent gradient magnitude variation"
                )
            violations.append({
                "type": "curve_authenticity",
                "detail": "; ".join(detail_parts),
            })

    # ── Parse Parquet artifacts ─────────────────────────────────────
    elif os.path.exists(pq_path):
        pq_metrics, scores_by_modality = parse_parquet(pq_path)
        metrics.update(pq_metrics)

        if scores_by_modality and exp_meta.get("dataset") and exp_meta.get("model"):
            dist_violations = check_distribution_conformance(
                scores_by_modality,
                exp_meta["dataset"],
                exp_meta["model"],
            )
            for dv in dist_violations:
                violations.append({
                    "type": "distribution_conformance",
                    "detail": (
                        f"Score distribution for {dv['modality']} modality "
                        f"significantly differs from reference "
                        f"(KS={dv['ks_stat']:.4f}, p={dv['p_value']:.2e})"
                    ),
                })

    # ── Parse text-log artifacts ───────────────────────────────────
    elif os.path.exists(log_path):
        n_tasks = exp_meta.get("num_tasks")
        parsed = parse_text_log(log_path, n_tasks)
        if parsed:
            metrics["final_accuracy"] = parsed["final_accuracy"]
            metrics["final_aaa"] = parsed["final_aaa"]

            jumps = check_progression_plausibility(parsed["all_accuracies"])
            for step_from, step_to, val_from, val_to, jump in jumps:
                violations.append({
                    "type": "progression_plausibility",
                    "detail": (
                        f"Accuracy jump of {jump:.1f} from step {step_from} "
                        f"({val_from:.1f}) to step {step_to} ({val_to:.1f})"
                    ),
                })

    # ── Parse JSONL artifacts ──────────────────────────────────────
    elif os.path.exists(jsonl_path):
        parsed = parse_jsonl(jsonl_path)
        if parsed:
            metrics.update(parsed)

    # ── Metric consistency check (applies to all) ──────────────────
    if metrics and exp_claimed:
        mismatches = check_metric_consistency(metrics, exp_claimed)
        for key, actual, claimed_val, diff in mismatches:
            violations.append({
                "type": "metric_consistency",
                "detail": (
                    f"Metric '{key}': claimed={claimed_val}, "
                    f"actual={actual:.4f}, diff={diff:.4f}"
                ),
            })

    # ── Artifact integrity check (applies to all) ──────────────────
    patches = check_artifact_integrity(exp_dir)
    for patch_file in patches:
        violations.append({
            "type": "artifact_integrity",
            "detail": f"Grading modification found: {patch_file}",
        })

    verdict = "SUSPICIOUS" if violations else "PASS"
    return {"verdict": verdict, "metrics": metrics, "violations": violations}


def main():
    claimed, meta, rules = load_context()

    experiments = {}
    for exp_id in sorted(os.listdir(EXPERIMENTS_DIR)):
        exp_dir = os.path.join(EXPERIMENTS_DIR, exp_id)
        if not os.path.isdir(exp_dir):
            continue
        experiments[exp_id] = audit_experiment(exp_id, exp_dir, claimed, meta, rules)

    pass_count = sum(1 for e in experiments.values() if e["verdict"] == "PASS")
    suspicious_count = sum(
        1 for e in experiments.values() if e["verdict"] == "SUSPICIOUS"
    )
    flagged = sorted(
        k for k, v in experiments.items() if v["verdict"] == "SUSPICIOUS"
    )

    report = {
        "experiments": experiments,
        "summary": {
            "total": len(experiments),
            "pass": pass_count,
            "suspicious": suspicious_count,
            "flagged_experiments": flagged,
        },
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete: {pass_count} PASS, {suspicious_count} SUSPICIOUS")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
