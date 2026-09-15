#!/usr/bin/env python3
"""Legacy rubric scoring pipeline.

This tool computes aggregate scores, category breakdowns, sensitivity
analysis, agreement metrics, and improvement recommendations from
hierarchical evaluation rubrics stored in a SQLite database.

Usage:
    python3 /app/legacy/scorer.py scores --rubric RUBRIC --grading GRADING
    python3 /app/legacy/scorer.py sensitivity --rubric RUBRIC
    python3 /app/legacy/scorer.py categories --rubric RUBRIC --grading GRADING
    python3 /app/legacy/scorer.py agreement --pair PAIR_ID
    python3 /app/legacy/scorer.py improvements --rubric RUBRIC --grading GRADING --k K
"""

import sqlite3
import json
import argparse
import sys

DB_PATH = "/app/data/rubrics.db"


def get_db():
    return sqlite3.connect(DB_PATH)


def get_leaves(conn, rubric_name):
    """Return leaf nodes: those with a non-null task_category."""
    rows = conn.execute(
        "SELECT node_id, weight, task_category "
        "FROM rubric_nodes "
        "WHERE rubric_name = ? AND task_category IS NOT NULL",
        (rubric_name,),
    ).fetchall()
    return rows


def get_grading_scores(conn, grading_id):
    """Return {node_id: score} for a grading."""
    rows = conn.execute(
        "SELECT node_id, score FROM gradings WHERE grading_id = ?",
        (grading_id,),
    ).fetchall()
    return dict(rows)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_root_score(conn, rubric_name, grading_id):
    leaves = get_leaves(conn, rubric_name)
    scores = get_grading_scores(conn, grading_id)
    total_weight = sum(w for _, w, _ in leaves)
    weighted_sum = sum(w * scores.get(nid, 0) for nid, w, _ in leaves)
    return weighted_sum / total_weight


def cmd_scores(args):
    conn = get_db()
    result = compute_root_score(conn, args.rubric, args.grading)
    print(json.dumps({"root_score": round(result, 6)}))


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

def compute_sensitivity(conn, rubric_name):
    leaves = get_leaves(conn, rubric_name)
    total_weight = sum(w for _, w, _ in leaves)
    return {nid: w / total_weight for nid, w, _ in leaves}


def cmd_sensitivity(args):
    conn = get_db()
    sens = compute_sensitivity(conn, args.rubric)
    sorted_items = sorted(sens.items(), key=lambda x: (-round(x[1], 9), x[0]))
    result = {k: round(v, 6) for k, v in sorted_items}
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Category analysis
# ---------------------------------------------------------------------------

def compute_categories(conn, rubric_name, grading_id):
    leaves = get_leaves(conn, rubric_name)
    scores = get_grading_scores(conn, grading_id)
    cats = {}
    for nid, _w, cat in leaves:
        if cat not in cats:
            cats[cat] = {"total": 0, "satisfied": 0}
        cats[cat]["total"] += 1
        cats[cat]["satisfied"] += scores.get(nid, 0)
    result = {}
    for cat in sorted(cats):
        c = cats[cat]
        result[cat] = round(c["satisfied"] / c["total"], 6) if c["total"] > 0 else 0.0
    return result


def cmd_categories(args):
    conn = get_db()
    result = compute_categories(conn, args.rubric, args.grading)
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

def compute_agreement(conn, pair_id):
    pair = conn.execute(
        "SELECT rubric_name, grading_id_1, grading_id_2 "
        "FROM agreement_pairs WHERE pair_id = ?",
        (pair_id,),
    ).fetchone()
    if not pair:
        raise ValueError(f"Unknown pair: {pair_id}")
    rubric_name, gid1, gid2 = pair

    g1 = get_grading_scores(conn, gid1)
    g2 = get_grading_scores(conn, gid2)
    leaves = get_leaves(conn, rubric_name)

    tp = fp = fn = tn = 0
    for nid, _, _ in leaves:
        pred, ref = g1.get(nid, 0), g2.get(nid, 0)
        if pred == 1 and ref == 1:
            tp += 1
        elif pred == 1 and ref == 0:
            fp += 1
        elif pred == 0 and ref == 1:
            fn += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    accuracy = (tp + tn) / n if n > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # Cohen's kappa
    p_o = accuracy
    p_e = 0.5  # base rate assumption for chance agreement
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1.0 else 1.0

    return {
        "cohens_kappa": round(kappa, 6),
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def cmd_agreement(args):
    conn = get_db()
    result = compute_agreement(conn, args.pair)
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Improvements
# ---------------------------------------------------------------------------

def cmd_improvements(args):
    conn = get_db()
    k = args.k
    sens = compute_sensitivity(conn, args.rubric)
    scores = get_grading_scores(conn, args.grading)
    current = compute_root_score(conn, args.rubric, args.grading)

    unsatisfied = [
        (nid, w) for nid, w in sens.items() if scores.get(nid, 0) == 0
    ]
    unsatisfied.sort(key=lambda x: (-round(x[1], 9), x[0]))
    selected = unsatisfied[:k]

    leaves_list = [nid for nid, _ in selected]
    new_score = current + sum(w for _, w in selected)

    print(json.dumps({
        "top_leaves": leaves_list,
        "improved_score": round(new_score, 6),
    }))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Legacy Rubric Scorer")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("scores")
    p.add_argument("--rubric", required=True)
    p.add_argument("--grading", required=True)

    p = sub.add_parser("sensitivity")
    p.add_argument("--rubric", required=True)

    p = sub.add_parser("categories")
    p.add_argument("--rubric", required=True)
    p.add_argument("--grading", required=True)

    p = sub.add_parser("agreement")
    p.add_argument("--pair", required=True)

    p = sub.add_parser("improvements")
    p.add_argument("--rubric", required=True)
    p.add_argument("--grading", required=True)
    p.add_argument("--k", required=True, type=int)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "scores": cmd_scores,
        "sensitivity": cmd_sensitivity,
        "categories": cmd_categories,
        "agreement": cmd_agreement,
        "improvements": cmd_improvements,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
