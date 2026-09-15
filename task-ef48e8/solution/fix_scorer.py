#!/usr/bin/env python3
"""

Fix all bugs, replace methodologically unsound approaches, and implement
all missing features in the clinical evidence evaluation framework.

Issues addressed:
1. loader.py: SQL query filters out 'not-relevant' labels — this silently
   corrupts the IAA computation because Krippendorff's alpha requires all
   labels including "not-relevant" to establish the correct base rates for
   chance correction. The filter must be removed.
2. adjudicate.py: threshold comparison uses > instead of >= (off-by-one
   excludes sentences with exactly threshold annotator agreement).
3. metrics.py: lenient scoring evaluates predictions directly against the
   lenient gold set instead of filtering supplementary-only predictions
   and scoring against strict gold (the correct protocol).
4. metrics.py: IAA uses averaged pairwise Cohen's kappa — this is
   methodologically inappropriate for multi-annotator nominal data because
   (a) it's a pairwise metric averaged over pairs, not a true multi-rater
   statistic, (b) it doesn't properly account for the joint chance
   structure across all annotators. Replaced with Krippendorff's alpha
   via the coincidence matrix approach.
5. bootstrap.py: resamples per-case F1 values and averages them — this
   produces a CI for *macro* F1, not micro F1. The correct approach
   resamples cases and recomputes micro F1 from pooled counts each
   iteration.
6. pipeline.py: weighted alignment F1 not implemented.
7. validate/check_alpha.R: wrong table name ('annotations' instead of
   'annotator_labels') and wrong expected disagreement denominator
   (n^2 instead of n*(n-1)/2).
8. NEW: diagnostics module for threshold sensitivity + scoring consistency.
9. NEW: run_eval.py updated to output diagnostics section.
"""


def write_fixed_loader():
    """Fix SQL query to include all relevance labels."""
    code = '''"""
Data loader for the clinical evidence evaluation framework.

Reads gold annotation data from a SQLite database and submission
data from JSON files.
"""
import sqlite3
import json


def load_gold_from_db(db_path):
    """
    Load gold annotation data from SQLite database.

    Reads cases, note sentences, answer sentences with citations,
    and per-annotator relevance labels from the normalized schema.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cases = []
    case_rows = conn.execute(
        "SELECT case_id FROM cases ORDER BY case_id"
    ).fetchall()

    for case_row in case_rows:
        case_id = case_row["case_id"]

        note_sentences = [
            {"id": r["sentence_id"], "text": r["sentence_text"]}
            for r in conn.execute(
                "SELECT sentence_id, sentence_text FROM note_sentences "
                "WHERE case_id = ? ORDER BY sentence_id",
                (case_id,),
            )
        ]

        answer_sentences = []
        ans_rows = conn.execute(
            "SELECT answer_id, answer_text FROM answer_sentences "
            "WHERE case_id = ? ORDER BY answer_id",
            (case_id,),
        ).fetchall()
        for ar in ans_rows:
            citations = [
                r["evidence_id"]
                for r in conn.execute(
                    "SELECT evidence_id FROM answer_citations "
                    "WHERE case_id = ? AND answer_id = ? ORDER BY evidence_id",
                    (case_id, ar["answer_id"]),
                )
            ]
            answer_sentences.append(
                {
                    "id": ar["answer_id"],
                    "text": ar["answer_text"],
                    "citations": citations,
                }
            )

        # FIX: Load ALL annotator labels including not-relevant.
        # The original query filtered to only essential/supplementary,
        # which corrupts Krippendorff's alpha by removing base-rate
        # information needed for chance correction.
        annotators = {}
        label_rows = conn.execute(
            "SELECT annotator_id, sentence_id, relevance "
            "FROM annotator_labels "
            "WHERE case_id = ? "
            "ORDER BY annotator_id, sentence_id",
            (case_id,),
        ).fetchall()
        for lr in label_rows:
            ann_id = lr["annotator_id"]
            if ann_id not in annotators:
                annotators[ann_id] = []
            annotators[ann_id].append(
                {"sentence_id": lr["sentence_id"], "relevance": lr["relevance"]}
            )

        cases.append(
            {
                "case_id": case_id,
                "note_sentences": note_sentences,
                "answer_sentences": answer_sentences,
                "annotators": annotators,
            }
        )

    conn.close()
    return {"cases": cases}


def load_submission(filepath):
    """Load a JSON submission file."""
    with open(filepath) as f:
        return json.load(f)
'''
    with open("/app/scorer/loader.py", "w") as f:
        f.write(code)


def write_fixed_adjudicate():
    """Fix threshold comparison: > -> >="""
    code = '''"""
Multi-annotator adjudication module for clinical evidence labels.

Resolves disagreements between multiple annotators using majority vote
to produce a single gold-standard set of evidence labels per case.
"""


def adjudicate_annotations(cases, threshold=2):
    """
    Adjudicate multi-annotator evidence relevance labels using majority vote.
    """
    gold_map = {}

    for case in cases:
        case_id = case["case_id"]
        sentences = case["note_sentences"]
        annotators = case["annotators"]

        valid_ids = {s["id"] for s in sentences}
        relevance_map = {}
        strict_evidence = set()
        lenient_evidence = set()

        for sent in sentences:
            sid = sent["id"]

            labels = []
            for ann_name, ann_data in annotators.items():
                for ann_sent in ann_data:
                    if ann_sent["sentence_id"] == sid:
                        labels.append(ann_sent["relevance"])
                        break

            relevant_count = sum(
                1 for l in labels if l in ("essential", "supplementary")
            )

            # FIX: use >= instead of >
            if relevant_count >= threshold:
                essential_count = sum(1 for l in labels if l == "essential")
                if essential_count > relevant_count / 2:
                    relevance_map[sid] = "essential"
                    strict_evidence.add(sid)
                    lenient_evidence.add(sid)
                else:
                    relevance_map[sid] = "supplementary"
                    lenient_evidence.add(sid)
            else:
                relevance_map[sid] = "not-relevant"

        gold_map[case_id] = {
            "strict_evidence": strict_evidence,
            "lenient_evidence": lenient_evidence,
            "relevance_map": relevance_map,
            "valid_sentence_ids": valid_ids,
        }

    return gold_map
'''
    with open("/app/scorer/adjudicate.py", "w") as f:
        f.write(code)


def write_fixed_metrics():
    """Fix lenient scoring and replace pairwise kappa with Krippendorff's alpha."""
    code = '''"""
Metrics module for clinical evidence evaluation.

Computes precision/recall/F1 for evidence identification (strict and lenient)
and inter-annotator agreement via Krippendorff\'s alpha.
"""
import numpy as np
from collections import Counter


def compute_prf(predicted, gold):
    """Compute precision, recall, and F1 for two sets."""
    if len(predicted) == 0 and len(gold) == 0:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if len(predicted) == 0 or len(gold) == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = len(predicted & gold)
    p = tp / len(predicted)
    r = tp / len(gold)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return {"precision": p, "recall": r, "f1": f1}


def compute_evidence_scores(submission, gold_map):
    """
    Compute strict and lenient evidence identification scores.

    Strict: predictions scored against essential-only gold evidence.
    Lenient: supplementary predictions are filtered out before scoring
    against essential-only (strict) gold.
    """
    strict_case_metrics = []
    lenient_case_metrics = []

    for case in submission:
        case_id = case["case_id"]
        predicted = set(case["prediction"])
        gold = gold_map[case_id]

        strict_gold = gold["strict_evidence"]
        lenient_gold = gold["lenient_evidence"]

        # Strict scoring
        strict_result = compute_prf(predicted, strict_gold)
        strict_tp = len(predicted & strict_gold)
        strict_case_metrics.append({
            "tp": strict_tp,
            "pred_count": len(predicted),
            "gold_count": len(strict_gold),
            **strict_result,
        })

        # FIX: Lenient scoring - filter supplementary-only predictions,
        # then score against strict gold
        supplementary_only = lenient_gold - strict_gold
        filtered_predicted = predicted - supplementary_only
        lenient_result = compute_prf(filtered_predicted, strict_gold)
        lenient_tp = len(filtered_predicted & strict_gold)
        lenient_case_metrics.append({
            "tp": lenient_tp,
            "pred_count": len(filtered_predicted),
            "gold_count": len(strict_gold),
            **lenient_result,
        })

    def aggregate(case_metrics):
        micro_tp = sum(m["tp"] for m in case_metrics)
        micro_pred = sum(m["pred_count"] for m in case_metrics)
        micro_gold = sum(m["gold_count"] for m in case_metrics)

        micro_p = micro_tp / micro_pred if micro_pred > 0 else 0.0
        micro_r = micro_tp / micro_gold if micro_gold > 0 else 0.0
        micro_f1 = (
            2 * micro_p * micro_r / (micro_p + micro_r)
            if (micro_p + micro_r) > 0
            else 0.0
        )

        return {
            "micro_precision": micro_p,
            "micro_recall": micro_r,
            "micro_f1": micro_f1,
            "macro_precision": float(np.mean([m["precision"] for m in case_metrics])),
            "macro_recall": float(np.mean([m["recall"] for m in case_metrics])),
            "macro_f1": float(np.mean([m["f1"] for m in case_metrics])),
            "per_case": case_metrics,
        }

    return {
        "strict": aggregate(strict_case_metrics),
        "lenient": aggregate(lenient_case_metrics),
    }


def compute_iaa(cases):
    """
    Compute Krippendorff\'s alpha for inter-annotator agreement
    on evidence relevance labels (nominal data).

    Uses the coincidence matrix approach:
    1. Build coincidence matrix from annotator label co-occurrences
    2. Compute observed disagreement from off-diagonal entries
    3. Compute expected disagreement from marginals
    4. alpha = 1 - D_o / D_e
    """
    categories = ["essential", "supplementary", "not-relevant"]
    cat_idx = {c: i for i, c in enumerate(categories)}
    n_cats = len(categories)

    # Build coincidence matrix
    coincidence = np.zeros((n_cats, n_cats), dtype=float)

    for case in cases:
        annotators = case["annotators"]
        ann_names = sorted(annotators.keys())
        sentences = case["note_sentences"]

        for sent in sentences:
            sid = sent["id"]

            # Collect labels for this sentence
            labels = []
            for ann_name in ann_names:
                for ann_sent in annotators[ann_name]:
                    if ann_sent["sentence_id"] == sid:
                        labels.append(ann_sent["relevance"])
                        break

            m_u = len(labels)
            if m_u < 2:
                continue

            # Count labels
            label_counts = Counter(labels)

            for c in categories:
                n_c = label_counts.get(c, 0)
                # Diagonal
                coincidence[cat_idx[c]][cat_idx[c]] += n_c * (n_c - 1) / (m_u - 1)
                # Off-diagonal
                for k in categories:
                    if k != c:
                        n_k = label_counts.get(k, 0)
                        coincidence[cat_idx[c]][cat_idx[k]] += n_c * n_k / (m_u - 1)

    # Marginals
    n_c_marginals = np.sum(coincidence, axis=1)
    n_total = np.sum(n_c_marginals)

    if n_total < 2:
        return 0.0

    # Observed disagreement
    diag_sum = np.sum(np.diag(coincidence))
    d_observed = (n_total - diag_sum) / n_total

    # Expected disagreement
    d_expected = 0.0
    for i in range(n_cats):
        for j in range(i + 1, n_cats):
            d_expected += n_c_marginals[i] * n_c_marginals[j]
    d_expected /= (n_total * (n_total - 1) / 2)

    if d_expected == 0:
        return 1.0

    alpha = 1.0 - d_observed / d_expected
    return float(alpha)
'''
    with open("/app/scorer/metrics.py", "w") as f:
        f.write(code)


def write_fixed_bootstrap():
    """Fix bootstrap to resample cases and compute micro F1 from pooled counts."""
    code = '''"""
Bootstrap confidence interval computation for evaluation metrics.

Computes bootstrap CIs for micro-averaged F1 scores using
case-level resampling.
"""
import numpy as np


def compute_bootstrap_ci(per_case_data, n_bootstrap=2000, seed=42, confidence=0.95):
    """
    Compute bootstrap confidence interval for micro-averaged F1.

    Uses case-level resampling: resample cases with replacement,
    pool raw counts, compute micro F1 from pooled counts.
    """
    rng = np.random.RandomState(seed)
    n = len(per_case_data)
    bootstrap_f1s = []

    for _ in range(n_bootstrap):
        indices = rng.choice(n, size=n, replace=True)

        # FIX: resample cases and recompute micro F1 from pooled counts
        boot_tp = sum(per_case_data[i]["tp"] for i in indices)
        boot_pred = sum(per_case_data[i]["pred_count"] for i in indices)
        boot_gold = sum(per_case_data[i]["gold_count"] for i in indices)

        boot_p = boot_tp / boot_pred if boot_pred > 0 else 0.0
        boot_r = boot_tp / boot_gold if boot_gold > 0 else 0.0
        boot_f1 = (
            2 * boot_p * boot_r / (boot_p + boot_r)
            if (boot_p + boot_r) > 0
            else 0.0
        )
        bootstrap_f1s.append(boot_f1)

    alpha = 1 - confidence
    lower = float(np.percentile(bootstrap_f1s, 100 * alpha / 2))
    upper = float(np.percentile(bootstrap_f1s, 100 * (1 - alpha / 2)))
    return {"lower": lower, "upper": upper}
'''
    with open("/app/scorer/bootstrap.py", "w") as f:
        f.write(code)


def write_fixed_pipeline():
    """Implement weighted alignment F1 with relevance-tier partial credit."""
    code = '''"""
Pipeline module for evidence-answer alignment scoring.

Computes standard (unweighted) and weighted alignment precision/recall/F1.
"""
import numpy as np


def compute_alignment_scores(submission, gold_map):
    """
    Compute standard (unweighted) alignment P/R/F1.
    """
    case_metrics = []

    for case in submission:
        case_id = case["case_id"]
        gold_aligns = gold_map[case_id]["alignments"]

        predicted_aligns = set()
        for alignment in case["prediction"]:
            answer_id = alignment["answer_id"]
            for evidence_id in alignment["evidence_id"]:
                predicted_aligns.add((answer_id, evidence_id))

        tp = len(predicted_aligns & gold_aligns)
        p = tp / len(predicted_aligns) if predicted_aligns else 0.0
        r = tp / len(gold_aligns) if gold_aligns else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        case_metrics.append({
            "tp": tp,
            "pred_count": len(predicted_aligns),
            "gold_count": len(gold_aligns),
            "precision": p,
            "recall": r,
            "f1": f1,
        })

    micro_tp = sum(m["tp"] for m in case_metrics)
    micro_pred = sum(m["pred_count"] for m in case_metrics)
    micro_gold = sum(m["gold_count"] for m in case_metrics)

    micro_p = micro_tp / micro_pred if micro_pred > 0 else 0.0
    micro_r = micro_tp / micro_gold if micro_gold > 0 else 0.0
    micro_f1 = (
        2 * micro_p * micro_r / (micro_p + micro_r)
        if (micro_p + micro_r) > 0
        else 0.0
    )

    return {
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f1,
        "macro_precision": float(np.mean([m["precision"] for m in case_metrics])),
        "macro_recall": float(np.mean([m["recall"] for m in case_metrics])),
        "macro_f1": float(np.mean([m["f1"] for m in case_metrics])),
    }


def compute_weighted_alignment_scores(submission, gold_map, evidence_gold_map):
    """
    Compute weighted alignment P/R/F1 using evidence relevance tiers.

    Weight for each alignment pair based on evidence relevance:
    - essential: weight 1.0
    - supplementary: weight 0.5
    """
    case_metrics = []

    total_weighted_tp = 0.0
    total_pred_count = 0
    total_gold_weight = 0.0

    for case in submission:
        case_id = case["case_id"]
        gold_aligns = gold_map[case_id]["alignments"]
        relevance_map = evidence_gold_map[case_id]["relevance_map"]

        def get_weight(evidence_id):
            rel = relevance_map.get(evidence_id, "not-relevant")
            if rel == "essential":
                return 1.0
            elif rel == "supplementary":
                return 0.5
            return 0.0

        gold_weight = sum(get_weight(e) for (_, e) in gold_aligns)

        predicted_aligns = set()
        for alignment in case["prediction"]:
            answer_id = alignment["answer_id"]
            for evidence_id in alignment["evidence_id"]:
                predicted_aligns.add((answer_id, evidence_id))

        correct = predicted_aligns & gold_aligns
        weighted_tp = sum(get_weight(e) for (_, e) in correct)

        pred_count = len(predicted_aligns)

        w_p = weighted_tp / pred_count if pred_count > 0 else 0.0
        w_r = weighted_tp / gold_weight if gold_weight > 0 else 0.0
        w_f1 = 2 * w_p * w_r / (w_p + w_r) if (w_p + w_r) > 0 else 0.0

        case_metrics.append({
            "weighted_tp": weighted_tp,
            "pred_count": pred_count,
            "gold_weight": gold_weight,
            "precision": w_p,
            "recall": w_r,
            "f1": w_f1,
        })

        total_weighted_tp += weighted_tp
        total_pred_count += pred_count
        total_gold_weight += gold_weight

    micro_p = total_weighted_tp / total_pred_count if total_pred_count > 0 else 0.0
    micro_r = total_weighted_tp / total_gold_weight if total_gold_weight > 0 else 0.0
    micro_f1 = (
        2 * micro_p * micro_r / (micro_p + micro_r)
        if (micro_p + micro_r) > 0
        else 0.0
    )

    return {
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f1,
        "macro_precision": float(np.mean([m["precision"] for m in case_metrics])),
        "macro_recall": float(np.mean([m["recall"] for m in case_metrics])),
        "macro_f1": float(np.mean([m["f1"] for m in case_metrics])),
    }
'''
    with open("/app/scorer/pipeline.py", "w") as f:
        f.write(code)


def write_fixed_r_script():
    """Fix R cross-validation script: table name and denominator formula."""
    code = '''#!/usr/bin/env Rscript
# Independent R computation of Krippendorff's alpha for cross-validation.

# FIX: correct table name (annotator_labels, not annotations)
data <- read.csv(pipe('sqlite3 -header -csv /app/data/annotations.db "SELECT case_id, annotator_id, sentence_id, relevance FROM annotator_labels"'),
                 stringsAsFactors = FALSE)

categories <- c("essential", "supplementary", "not-relevant")
n_cats <- length(categories)

coincidence <- matrix(0, nrow = n_cats, ncol = n_cats)
rownames(coincidence) <- categories
colnames(coincidence) <- categories

data$unit_id <- paste(data$case_id, data$sentence_id, sep = "_")
units <- unique(data$unit_id)

for (u in units) {
    unit_labels <- data$relevance[data$unit_id == u]
    m_u <- length(unit_labels)
    if (m_u < 2) next

    for (c_name in categories) {
        n_c <- sum(unit_labels == c_name)
        coincidence[c_name, c_name] <- coincidence[c_name, c_name] +
            n_c * (n_c - 1) / (m_u - 1)
        for (k_name in categories) {
            if (k_name != c_name) {
                n_k <- sum(unit_labels == k_name)
                coincidence[c_name, k_name] <- coincidence[c_name, k_name] +
                    n_c * n_k / (m_u - 1)
            }
        }
    }
}

n_marginals <- rowSums(coincidence)
n_total <- sum(n_marginals)

diag_sum <- sum(diag(coincidence))
D_o <- (n_total - diag_sum) / n_total

# FIX: correct denominator (n*(n-1)/2, not n^2)
D_e <- 0
for (i in 1:(n_cats - 1)) {
    for (j in (i + 1):n_cats) {
        D_e <- D_e + n_marginals[i] * n_marginals[j]
    }
}
D_e <- D_e / (n_total * (n_total - 1) / 2)

alpha <- 1 - D_o / D_e

dir.create("/app/output", showWarnings = FALSE, recursive = TRUE)
writeLines(sprintf("%.6f", alpha), "/app/output/alpha_validation.txt")
cat("R-computed alpha:", alpha, "\\n")
'''
    with open("/app/validate/check_alpha.R", "w") as f:
        f.write(code)


def write_diagnostics_module():
    """Create the pipeline diagnostics module."""
    code = '''"""
Pipeline diagnostics module.

Evaluates pipeline behavior via threshold sensitivity analysis
and scoring consistency validation.
"""
from scorer.adjudicate import adjudicate_annotations


def compute_threshold_sensitivity(cases, thresholds=None):
    """
    Compute how the adjudication threshold affects evidence counts.

    Re-runs adjudication at each threshold and reports total strict
    and lenient evidence sentence counts across all cases.
    """
    if thresholds is None:
        thresholds = [1, 2, 3]

    results = {}
    for t in thresholds:
        gold = adjudicate_annotations(cases, threshold=t)
        total_strict = sum(len(v["strict_evidence"]) for v in gold.values())
        total_lenient = sum(len(v["lenient_evidence"]) for v in gold.values())
        results[str(t)] = {
            "total_strict_evidence": total_strict,
            "total_lenient_evidence": total_lenient,
        }
    return results


def compute_scoring_consistency(evidence_scores):
    """
    Verify the invariant that lenient F1 >= strict F1.

    This must hold because lenient scoring removes supplementary-only
    predictions (reducing false positives) while preserving true positives.
    """
    strict = evidence_scores["strict"]
    lenient = evidence_scores["lenient"]
    return {
        "lenient_gte_strict_micro_f1": bool(
            lenient["micro_f1"] >= strict["micro_f1"] - 1e-10
        ),
        "lenient_gte_strict_macro_f1": bool(
            lenient["macro_f1"] >= strict["macro_f1"] - 1e-10
        ),
    }
'''
    with open("/app/scorer/diagnostics.py", "w") as f:
        f.write(code)


def write_updated_run_eval():
    """Update run_eval.py to include diagnostics output."""
    code = '''#!/usr/bin/env python3
"""
Clinical Evidence Evaluation Framework

Runs the complete evaluation pipeline:
1. Load annotation data from SQLite database
2. Adjudicate multi-annotator labels into gold standard
3. Score evidence identification submissions (strict + lenient)
4. Compute bootstrap confidence intervals for micro F1
5. Score evidence-answer alignment submissions (standard + weighted)
6. Compute inter-annotator agreement
7. Cross-validate IAA via R module
8. Compute pipeline diagnostics
9. Output all scores as JSON
"""
import json
import argparse
import subprocess
import os
from pathlib import Path

from scorer.loader import load_gold_from_db, load_submission
from scorer.adjudicate import adjudicate_annotations
from scorer.metrics import compute_evidence_scores, compute_iaa
from scorer.pipeline import compute_alignment_scores, compute_weighted_alignment_scores
from scorer.bootstrap import compute_bootstrap_ci
from scorer.diagnostics import compute_threshold_sensitivity, compute_scoring_consistency


def build_alignment_gold(cases):
    """Extract gold alignment pairs from answer_sentence citations."""
    gold_map = {}
    for case in cases:
        case_id = case["case_id"]
        alignments = set()
        valid_answer_ids = set()
        valid_evidence_ids = {s["id"] for s in case["note_sentences"]}

        for ans in case["answer_sentences"]:
            aid = ans["id"]
            valid_answer_ids.add(aid)
            for cid in ans["citations"]:
                alignments.add((aid, cid))

        gold_map[case_id] = {
            "alignments": alignments,
            "valid_answer_ids": valid_answer_ids,
            "valid_evidence_ids": valid_evidence_ids,
        }
    return gold_map


def main():
    parser = argparse.ArgumentParser(description="Clinical Evidence Evaluation")
    parser.add_argument(
        "--output", type=str, default="/app/output/scores.json",
        help="Path to output scores JSON file",
    )
    parser.add_argument(
        "--db", type=str, default="/app/data/annotations.db",
        help="Path to SQLite annotation database",
    )
    parser.add_argument(
        "--data-dir", type=str, default="/app/data",
        help="Path to data directory",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_path = Path(args.output)

    # Step 1: Load data
    print("Loading annotation data from database...")
    gold = load_gold_from_db(args.db)
    sub_evidence = load_submission(data_dir / "submission_evidence.json")
    sub_alignment = load_submission(data_dir / "submission_alignment.json")
    cases = gold["cases"]

    # Step 2: Adjudicate
    print("Adjudicating multi-annotator labels...")
    evidence_gold = adjudicate_annotations(cases)

    # Step 3: Evidence identification scores
    print("Computing evidence identification scores...")
    evidence_scores = compute_evidence_scores(sub_evidence, evidence_gold)

    # Step 4: Bootstrap CIs
    print("Computing bootstrap confidence intervals...")
    strict_ci = compute_bootstrap_ci(evidence_scores["strict"]["per_case"])
    lenient_ci = compute_bootstrap_ci(evidence_scores["lenient"]["per_case"])

    # Step 5: Alignment scores
    print("Computing alignment scores...")
    alignment_gold = build_alignment_gold(cases)
    alignment_scores = compute_alignment_scores(sub_alignment, alignment_gold)
    weighted_alignment_scores = compute_weighted_alignment_scores(
        sub_alignment, alignment_gold, evidence_gold
    )

    # Step 6: IAA
    print("Computing inter-annotator agreement...")
    iaa_value = compute_iaa(cases)

    # Step 7: R cross-validation
    print("Running R cross-validation of IAA...")
    r_alpha = None
    r_result = subprocess.run(
        ["Rscript", "/app/validate/check_alpha.R"],
        capture_output=True, text=True,
    )
    if r_result.returncode == 0:
        r_output_path = "/app/output/alpha_validation.txt"
        if os.path.exists(r_output_path):
            with open(r_output_path) as f:
                try:
                    r_alpha = float(f.read().strip())
                except ValueError:
                    r_alpha = None
    else:
        print(f"R validation failed: {r_result.stderr}")

    # Step 8: Pipeline diagnostics
    print("Computing pipeline diagnostics...")
    threshold_sensitivity = compute_threshold_sensitivity(cases)
    scoring_consistency = compute_scoring_consistency(evidence_scores)

    # Build output
    output = {
        "evidence_identification": {
            "strict": {
                "micro_precision": evidence_scores["strict"]["micro_precision"],
                "micro_recall": evidence_scores["strict"]["micro_recall"],
                "micro_f1": evidence_scores["strict"]["micro_f1"],
                "macro_precision": evidence_scores["strict"]["macro_precision"],
                "macro_recall": evidence_scores["strict"]["macro_recall"],
                "macro_f1": evidence_scores["strict"]["macro_f1"],
                "bootstrap_ci_micro_f1_lower": strict_ci["lower"],
                "bootstrap_ci_micro_f1_upper": strict_ci["upper"],
            },
            "lenient": {
                "micro_precision": evidence_scores["lenient"]["micro_precision"],
                "micro_recall": evidence_scores["lenient"]["micro_recall"],
                "micro_f1": evidence_scores["lenient"]["micro_f1"],
                "macro_precision": evidence_scores["lenient"]["macro_precision"],
                "macro_recall": evidence_scores["lenient"]["macro_recall"],
                "macro_f1": evidence_scores["lenient"]["macro_f1"],
                "bootstrap_ci_micro_f1_lower": lenient_ci["lower"],
                "bootstrap_ci_micro_f1_upper": lenient_ci["upper"],
            },
        },
        "evidence_alignment": {
            "standard": alignment_scores,
            "weighted": weighted_alignment_scores,
        },
        "inter_annotator_agreement": {
            "krippendorff_alpha": iaa_value,
            "r_validated_alpha": r_alpha,
        },
        "diagnostics": {
            "threshold_sensitivity": threshold_sensitivity,
            "scoring_consistency": scoring_consistency,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Scores saved to {output_path}")


if __name__ == "__main__":
    main()
'''
    with open("/app/run_eval.py", "w") as f:
        f.write(code)


if __name__ == "__main__":
    print("Fixing loader.py: removing relevance filter from SQL query")
    write_fixed_loader()

    print("Fixing adjudicate.py: threshold comparison > -> >=")
    write_fixed_adjudicate()

    print("Fixing metrics.py: lenient scoring + replacing kappa with Krippendorff's alpha")
    write_fixed_metrics()

    print("Fixing bootstrap.py: case-level resampling for micro F1")
    write_fixed_bootstrap()

    print("Fixing pipeline.py: implementing weighted alignment F1")
    write_fixed_pipeline()

    print("Fixing check_alpha.R: table name + denominator formula")
    write_fixed_r_script()

    print("Creating diagnostics module")
    write_diagnostics_module()

    print("Updating run_eval.py with diagnostics output")
    write_updated_run_eval()

    print("All fixes applied successfully.")
