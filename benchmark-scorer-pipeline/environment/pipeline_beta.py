#!/usr/bin/env python3
"""Pipeline Beta — Count-based scoring with correct contamination handling, CSV output."""

import csv
import os
import random
import sqlite3

DB = "/app/benchmark.db"
OUT_DIR = "/app/outputs/beta"


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT model_id FROM models ORDER BY model_id")
    models = [r[0] for r in c.fetchall()]

    c.execute("SELECT snippet_id, paper_id, lines_of_code FROM snippets")
    snippets = {}
    paper_snippets = {}
    for sid, pid, loc in c.fetchall():
        snippets[sid] = {"paper_id": pid, "loc": loc}
        paper_snippets.setdefault(pid, []).append(sid)

    c.execute("SELECT paper_id, repo_first_commit FROM papers")
    papers = dict(c.fetchall())

    c.execute("SELECT model_id, knowledge_cutoff FROM models")
    cutoffs = dict(c.fetchall())

    c.execute("SELECT model_id, snippet_id, with_paper, without_paper FROM results")
    results = {}
    for mid, sid, wp, wop in c.fetchall():
        results.setdefault(mid, {})[sid] = {
            "with_paper": bool(wp), "without_paper": bool(wop)
        }

    conn.close()

    def count_rate(mid, cond, sids=None):
        """Simple count-based pass rate."""
        total = passed = 0
        target = sids if sids is not None else snippets.keys()
        for sid in target:
            total += 1
            if results[mid][sid][cond]:
                passed += 1
        return passed / total if total else 0.0

    os.makedirs(OUT_DIR, exist_ok=True)

    # scaled_pass1: count-based (not LOC-weighted)
    with open(f"{OUT_DIR}/scaled_pass1.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_id", "score"])
        for m in models:
            w.writerow([m, round(count_rate(m, "with_paper"), 6)])

    # contamination_safe: strict > comparison, handles null
    cs = {}
    for mid in models:
        cutoff = cutoffs[mid]
        safe = set()
        for pid, commit in papers.items():
            if commit > cutoff:
                safe.update(paper_snippets.get(pid, []))
        if not safe:
            cs[mid] = None
        else:
            cs[mid] = round(count_rate(mid, "with_paper", safe), 6)

    with open(f"{OUT_DIR}/contamination_safe.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_id", "score"])
        for m in models:
            w.writerow([m, cs[m] if cs[m] is not None else ""])

    # ablation: with_paper minus without_paper (count-based)
    with open(f"{OUT_DIR}/paper_ablation.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_id", "impact"])
        for m in models:
            w.writerow([m, round(count_rate(m, "with_paper") - count_rate(m, "without_paper"), 6)])

    # bootstrap: seed 42, 1000 iterations, snippet-level
    all_sids = sorted(snippets.keys())
    with open(f"{OUT_DIR}/bootstrap_ci.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model_id", "lower", "upper"])
        for mid in models:
            rng = random.Random(42)
            scores = []
            for _ in range(1000):
                sampled = [rng.choice(all_sids) for _ in range(len(all_sids))]
                t = p = 0
                for sid in sampled:
                    loc = snippets[sid]["loc"]
                    t += loc
                    if results[mid][sid]["with_paper"]:
                        p += loc
                scores.append(p / t if t else 0.0)
            scores.sort()
            lo = round(scores[int(0.025 * 1000)], 6)
            hi = round(scores[int(0.975 * 1000)], 6)
            w.writerow([mid, lo, hi])

    # ranking: descending, null last
    ranked = sorted(
        [(m, s) for m, s in cs.items() if s is not None],
        key=lambda x: -x[1],
    )
    ranking = []
    for i, (m, s) in enumerate(ranked):
        ranking.append({"rank": i + 1, "model_id": m, "contamination_safe_score": s})
    for m, s in cs.items():
        if s is None:
            ranking.append({"rank": None, "model_id": m, "contamination_safe_score": None})

    with open(f"{OUT_DIR}/ranking.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "model_id", "contamination_safe_score"])
        for r in ranking:
            w.writerow([
                r["rank"] if r["rank"] is not None else "",
                r["model_id"],
                r["contamination_safe_score"] if r["contamination_safe_score"] is not None else ""
            ])


if __name__ == "__main__":
    main()
