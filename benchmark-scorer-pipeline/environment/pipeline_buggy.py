#!/usr/bin/env python3
"""Benchmark analysis pipeline - produces analysis.json from benchmark.db"""

import json
import math
import os
import random
import sqlite3
from itertools import combinations

DB_PATH = "/app/benchmark.db"
OUTPUT = "/app/output/draft_analysis.json"


def connect():
    return sqlite3.connect(DB_PATH)


def pass_rate(db, model_id, condition="with_paper", subset=None):
    """Compute pass@1 for a model under given condition."""
    c = db.cursor()
    if subset:
        ph = ",".join(["?"] * len(subset))
        c.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN {condition}=1 THEN 1 ELSE 0 END) "
            f"FROM results WHERE model_id=? AND snippet_id IN ({ph})",
            [model_id] + list(subset)
        )
    else:
        c.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN {condition}=1 THEN 1 ELSE 0 END) "
            f"FROM results WHERE model_id=?",
            [model_id]
        )
    total, passed = c.fetchone()
    return (passed or 0) / total if total else 0.0


def get_safe_ids(db, model_id):
    """Snippets not in model's training data."""
    c = db.cursor()
    c.execute("SELECT knowledge_cutoff FROM models WHERE model_id=?", [model_id])
    cutoff = c.fetchone()[0]
    c.execute(
        "SELECT s.snippet_id FROM snippets s "
        "JOIN papers p ON s.paper_id=p.paper_id "
        "WHERE p.repo_first_commit >= ?",
        [cutoff]
    )
    return [r[0] for r in c.fetchall()]


def bootstrap(db, model_id):
    """Bootstrap 95% CI for pass@1."""
    rng = random.Random(42)
    c = db.cursor()
    c.execute(
        "SELECT r.snippet_id, s.lines_of_code, r.with_paper "
        "FROM results r JOIN snippets s ON r.snippet_id=s.snippet_id "
        "WHERE r.model_id=?",
        [model_id]
    )
    rows = c.fetchall()
    scores = []
    for _ in range(1000):
        samp = [rng.choice(rows) for _ in range(len(rows))]
        t = sum(x[1] for x in samp)
        p = sum(x[1] for x in samp if x[2])
        scores.append(p / t if t else 0.0)
    scores.sort()
    lo = scores[int(0.025 * 1000)]
    hi = scores[int(0.975 * 1000)]
    return lo, hi


def main():
    db = connect()
    c = db.cursor()
    c.execute("SELECT model_id FROM models ORDER BY model_id")
    models = [r[0] for r in c.fetchall()]

    result = {}

    # R1: Scaled Pass@1
    result["scaled_pass1"] = {
        m: round(pass_rate(db, m), 6) for m in models
    }

    # R2: Contamination-safe
    cs = {}
    for m in models:
        sids = get_safe_ids(db, m)
        val = pass_rate(db, m, "with_paper", sids if sids else None)
        cs[m] = round(val, 6)
    result["contamination_safe_scaled_pass1"] = cs

    # R3: Ablation
    result["paper_ablation_impact"] = {
        m: round(pass_rate(db, m, "without_paper") - pass_rate(db, m, "with_paper"), 6)
        for m in models
    }

    # R4: Bootstrap
    result["bootstrap_ci"] = {}
    for m in models:
        lo, hi = bootstrap(db, m)
        result["bootstrap_ci"][m] = {"lower": round(lo, 6), "upper": round(hi, 6)}

    # R5: Ranking
    pairs = [(m, cs[m]) for m in models if cs[m] is not None]
    pairs.sort(key=lambda x: x[1])
    ranking = [{"rank": i + 1, "model_id": m, "contamination_safe_score": s}
               for i, (m, s) in enumerate(pairs)]
    nulls = [m for m in models if cs[m] is None]
    ranking += [{"rank": None, "model_id": m, "contamination_safe_score": None}
                for m in nulls]
    result["ranking"] = ranking

    # R6: Pairwise significance
    c.execute("SELECT snippet_id FROM snippets ORDER BY snippet_id")
    all_snippets = [r[0] for r in c.fetchall()]

    c.execute("SELECT model_id, snippet_id, with_paper FROM results")
    res_map = {}
    for mid, sid, wp in c.fetchall():
        res_map.setdefault(mid, {})[sid] = bool(wp)

    pairwise = {}
    for m1, m2 in combinations(models, 2):
        rng = random.Random(42)
        diffs = []
        for _ in range(1000):
            samp = [rng.choice(all_snippets) for _ in range(len(all_snippets))]
            n = len(samp)
            p1 = sum(1 for s in samp if res_map[m1].get(s, False))
            p2 = sum(1 for s in samp if res_map[m2].get(s, False))
            s1 = p1 / n if n else 0
            s2 = p2 / n if n else 0
            diffs.append(s1 - s2)
        diffs.sort()
        lo = diffs[int(0.025 * 1000)]
        hi = diffs[int(0.975 * 1000)]
        sig = lo > 0 or hi < 0
        pair_key = f"{m1}_vs_{m2}"
        pairwise[pair_key] = {
            "model_a": m1, "model_b": m2,
            "ci_lower": round(lo, 6), "ci_upper": round(hi, 6),
            "significant": sig
        }
    result["pairwise_significance"] = pairwise

    # R7: Jackknife stability
    c.execute("SELECT DISTINCT paper_id FROM papers ORDER BY paper_id")
    paper_ids = [r[0] for r in c.fetchall()]
    n = len(paper_ids)

    c.execute("SELECT snippet_id, paper_id FROM snippets")
    snip_papers = {r[0]: r[1] for r in c.fetchall()}

    jackknife = {}
    for mid in models:
        full_sids = list(snip_papers.keys())
        full_score = pass_rate(db, mid, "with_paper")

        loo_scores = {}
        for pid in paper_ids:
            remaining = [s for s in full_sids if snip_papers[s] != pid]
            loo_scores[pid] = pass_rate(db, mid, "with_paper", remaining)

        theta_bar = sum(loo_scores.values()) / n
        se = math.sqrt(sum((t - theta_bar) ** 2 for t in loo_scores.values()) / n)

        influence = {pid: abs(full_score - s) for pid, s in loo_scores.items()}
        most_influential = min(influence, key=influence.get)

        jackknife[mid] = {
            "jackknife_se": round(se, 6),
            "most_influential_paper": most_influential,
            "influence_magnitude": round(influence[most_influential], 6),
            "leave_one_out_scores": {pid: round(s, 6)
                                     for pid, s in sorted(loo_scores.items())}
        }
    result["jackknife_stability"] = jackknife

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(result, f, indent=2)
    db.close()


if __name__ == "__main__":
    main()
