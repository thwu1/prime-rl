#!/usr/bin/env python3
"""Pipeline Gamma — Paper-stratified bootstrap with LOC weighting."""

import json
import os
import random
import sqlite3

DB = "/app/benchmark.db"


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
    paper_ids = sorted(papers.keys())

    c.execute("SELECT model_id, knowledge_cutoff FROM models")
    cutoffs = dict(c.fetchall())

    c.execute("SELECT model_id, snippet_id, with_paper, without_paper FROM results")
    results = {}
    for mid, sid, wp, wop in c.fetchall():
        results.setdefault(mid, {})[sid] = {
            "with_paper": bool(wp), "without_paper": bool(wop)
        }

    conn.close()

    def loc_weighted(mid, cond, sids=None):
        total = passed = 0
        for sid, info in snippets.items():
            if sids is not None and sid not in sids:
                continue
            loc = info["loc"]
            total += loc
            if results[mid][sid][cond]:
                passed += loc
        return passed / total if total else 0.0

    out = {}

    # scaled_pass1: LOC-weighted
    out["scaled_pass1"] = {
        m: round(loc_weighted(m, "with_paper"), 6) for m in models
    }

    # contamination_safe: strict > comparison but no null handling
    cs = {}
    for mid in models:
        cutoff = cutoffs[mid]
        safe = set()
        for pid, commit in papers.items():
            if commit > cutoff:
                safe.update(paper_snippets.get(pid, []))
        # No null check — returns 0.0 when safe is empty
        cs[mid] = round(loc_weighted(mid, "with_paper", safe), 6)
    out["contamination_safe_scaled_pass1"] = cs

    # ablation: with_paper minus without_paper, LOC-weighted
    out["paper_ablation_impact"] = {
        m: round(loc_weighted(m, "with_paper") - loc_weighted(m, "without_paper"), 6)
        for m in models
    }

    # bootstrap: paper-level stratified, seed 2024, 10000 iters
    out["bootstrap_ci"] = {}
    for mid in models:
        rng = random.Random(2024)
        scores = []
        for _ in range(10000):
            sampled = [rng.choice(paper_ids) for _ in range(len(paper_ids))]
            t = p = 0
            for pid in sampled:
                for sid in paper_snippets[pid]:
                    loc = snippets[sid]["loc"]
                    t += loc
                    if results[mid][sid]["with_paper"]:
                        p += loc
            scores.append(p / t if t else 0.0)
        scores.sort()
        out["bootstrap_ci"][mid] = {
            "lower": round(scores[int(0.025 * 10000)], 6),
            "upper": round(scores[int(0.975 * 10000)], 6),
        }

    # ranking: descending but ranks ALL models (no null handling)
    ranked = sorted(cs.items(), key=lambda x: -x[1])
    ranking = [
        {"rank": i + 1, "model_id": m, "contamination_safe_score": s}
        for i, (m, s) in enumerate(ranked)
    ]
    out["ranking"] = ranking

    os.makedirs("/app/outputs", exist_ok=True)
    with open("/app/outputs/gamma.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
