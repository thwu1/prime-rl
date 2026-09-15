#!/usr/bin/env python3
"""LegalCiteBench evaluation script.

Adapted from a prior evaluation pipeline that used a unified database schema
where ground truth was stored directly in the SQLite database.

NOTE: This script was written for an earlier data architecture and may not
work with the current data layout.
"""

import json
import re
import sqlite3
import sys

DB_PATH = "/app/citation_eval.db"
RESULTS_PATH = "/app/current_results.json"


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def extract_citations(text):
    """Extract legal citation strings from model output text."""
    patterns = [
        # US Reports: 466 U.S. 668
        r'\d+\s+U\.S\.\s+\d+',
        # Federal Reporter: 807 F.3d 619, 576 F.2d 236
        r'\d+\s+F\.(?:Supp\.)?(?:\d[a-z])?\s+\d+',
        # South Western Reporter: 973 S.W.2d 485
        r'\d+\s+S\.W\.(?:\d[a-z])?\s+\d+',
    ]

    found = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            citation = re.sub(r'\s+', ' ', match.group().strip())
            found.add(citation)
    return list(found)


def citation_match(pred, gt):
    """Check if predicted citation matches ground truth."""
    return pred.lower().strip() in gt.lower().strip()


def compute_f1(predicted, ground_truth):
    """Compute citation-level F1 score (0-100)."""
    if not predicted and not ground_truth:
        return 0.0
    matched = 0
    for p in predicted:
        for g in ground_truth:
            if citation_match(p, g):
                matched += 1
                break
    prec = matched / len(predicted) if predicted else 0
    rec = matched / len(ground_truth) if ground_truth else 0
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec) * 100


def score_cat3(output, variant, ground_truth):
    """Score a Cat3 instance (0-5)."""
    output_lower = output.lower()

    if variant == "true":
        if re.search(r'\b(error|incorrect|wrong)\b', output_lower):
            return 2
        elif re.search(r'\b(correct|accurate)\b', output_lower):
            return 5
        return 0

    elif variant == "fake":
        if not re.search(r'\b(error|incorrect|wrong)\b', output_lower):
            return 1
        match = re.search(
            r'The correct citation is:\s*(.+)$', ground_truth, re.IGNORECASE)
        if not match:
            return 2
        correct = match.group(1).strip()
        if correct.lower() in output_lower:
            return 5
        return 2

    return 0


def main():
    conn = connect_db()

    # Verify ground_truth table exists
    try:
        conn.execute("SELECT COUNT(*) FROM ground_truth").fetchone()
    except sqlite3.OperationalError:
        print("ERROR: 'ground_truth' table not found in database.",
              file=sys.stderr)
        print("The evaluation data may have been restructured. Ground truth",
              file=sys.stderr)
        print("annotations may be stored in a separate file.",
              file=sys.stderr)
        conn.close()
        sys.exit(1)

    cat1_f1, cat1_conc = [], []
    cat2_f1, cat2_conc = [], []
    cat3_scores = []

    for row in conn.execute(
            "SELECT i.instance_id, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat1'"):
        gt_rows = conn.execute(
            "SELECT gt_value FROM ground_truth WHERE instance_id = ?",
            (row['instance_id'],)).fetchall()
        gt = [r['gt_value'] for r in gt_rows]
        preds = extract_citations(row['response_text'])
        f1 = compute_f1(preds, gt)
        cat1_f1.append(f1)
        cat1_conc.append(len(preds) > 0)

    for row in conn.execute(
            "SELECT i.instance_id, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat2'"):
        gt_rows = conn.execute(
            "SELECT gt_value FROM ground_truth WHERE instance_id = ?",
            (row['instance_id'],)).fetchall()
        gt = [r['gt_value'] for r in gt_rows]
        preds = extract_citations(row['response_text'])
        f1 = compute_f1(preds, gt)
        cat2_f1.append(f1)
        cat2_conc.append(len(preds) > 0)

    for row in conn.execute(
            "SELECT i.instance_id, i.variant, r.response_text "
            "FROM instances i "
            "JOIN model_responses r ON i.instance_id = r.instance_id "
            "WHERE i.category = 'cat3'"):
        gt_row = conn.execute(
            "SELECT gt_value FROM ground_truth WHERE instance_id = ?",
            (row['instance_id'],)).fetchone()
        gt = gt_row['gt_value'] if gt_row else ""
        s = score_cat3(row['response_text'], row['variant'], gt)
        cat3_scores.append(s)

    conn.close()

    c1f1 = sum(cat1_f1) / len(cat1_f1) if cat1_f1 else 0
    c2f1 = sum(cat2_f1) / len(cat2_f1) if cat2_f1 else 0
    c3_raw = sum(cat3_scores) / len(cat3_scores) if cat3_scores else 0

    def mar(f1s, concs, theta=40):
        low = [(f, c) for f, c in zip(f1s, concs) if f <= theta]
        if not low:
            return 0.0
        return sum(1 for _, c in low if c) / len(low)

    results = {
        "cat1_mean_f1": round(c1f1, 4),
        "cat2_mean_f1": round(c2f1, 4),
        "cat3_mean_score": round(c3_raw, 4),
        "cat1_mar": round(mar(cat1_f1, cat1_conc), 4),
        "cat2_mar": round(mar(cat2_f1, cat2_conc), 4),
        "overall_mar": round(mar(cat1_f1 + cat2_f1, cat1_conc + cat2_conc), 4),
        "num_instances": len(cat1_f1) + len(cat2_f1) + len(cat3_scores),
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
