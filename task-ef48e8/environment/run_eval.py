#!/usr/bin/env python3
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
8. Output all scores as JSON
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


def build_alignment_gold(cases):
    """
    Extract gold alignment pairs from answer_sentence citations.

    Returns:
        dict mapping case_id -> {
            "alignments": set of (answer_id, evidence_id) tuples,
            "valid_answer_ids": set of answer sentence IDs,
            "valid_evidence_ids": set of evidence sentence IDs
        }
    """
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
        "--output",
        type=str,
        default="/app/output/scores.json",
        help="Path to output scores JSON file",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="/app/data/annotations.db",
        help="Path to SQLite annotation database",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="/app/data",
        help="Path to data directory",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_path = Path(args.output)

    # Step 1: Load data from SQLite database
    print("Loading annotation data from database...")
    gold = load_gold_from_db(args.db)
    sub_evidence = load_submission(data_dir / "submission_evidence.json")
    sub_alignment = load_submission(data_dir / "submission_alignment.json")
    cases = gold["cases"]

    # Step 2: Adjudicate multi-annotator labels
    print("Adjudicating multi-annotator labels...")
    evidence_gold = adjudicate_annotations(cases)

    # Step 3: Compute evidence identification scores
    print("Computing evidence identification scores...")
    evidence_scores = compute_evidence_scores(sub_evidence, evidence_gold)

    # Step 4: Compute bootstrap CIs for micro F1
    print("Computing bootstrap confidence intervals...")
    strict_ci = compute_bootstrap_ci(evidence_scores["strict"]["per_case"])
    lenient_ci = compute_bootstrap_ci(evidence_scores["lenient"]["per_case"])

    # Step 5: Build alignment gold and compute scores
    print("Computing alignment scores...")
    alignment_gold = build_alignment_gold(cases)
    alignment_scores = compute_alignment_scores(sub_alignment, alignment_gold)
    weighted_alignment_scores = compute_weighted_alignment_scores(
        sub_alignment, alignment_gold, evidence_gold
    )

    # Step 6: Compute inter-annotator agreement
    print("Computing inter-annotator agreement...")
    iaa_value = compute_iaa(cases)

    # Step 7: Run R cross-validation
    print("Running R cross-validation of IAA...")
    r_alpha = None
    r_result = subprocess.run(
        ["Rscript", "/app/validate/check_alpha.R"],
        capture_output=True,
        text=True,
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
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Scores saved to {output_path}")


if __name__ == "__main__":
    main()
