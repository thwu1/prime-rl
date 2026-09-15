#!/usr/bin/env python3

"""Correct benchmark analysis: all seven metrics implemented correctly."""

import json
import math
import os
import random
import sqlite3
from itertools import combinations

DB = "/app/benchmark.db"


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT paper_id, repo_first_commit FROM papers")
    papers = dict(c.fetchall())

    c.execute("SELECT snippet_id, paper_id, lines_of_code FROM snippets")
    snippets = {}
    paper_snippets = {}
    for sid, pid, loc in c.fetchall():
        snippets[sid] = {"paper_id": pid, "loc": loc}
        paper_snippets.setdefault(pid, []).append(sid)

    c.execute("SELECT model_id, knowledge_cutoff FROM models")
    models = dict(c.fetchall())

    c.execute("SELECT model_id, snippet_id, with_paper, without_paper FROM results")
    results = {}
    for mid, sid, wp, wop in c.fetchall():
        results.setdefault(mid, {})[sid] = {
            "with_paper": bool(wp), "without_paper": bool(wop)
        }

    conn.close()

    paper_ids = sorted(papers.keys())
    model_ids = sorted(models.keys())
    all_sids = list(snippets.keys())

    def loc_weighted(mid, cond, sids=None):
        total = passed = 0
        for sid, info in snippets.items():
            if sids is not None and sid not in sids:
                continue
            loc = info["loc"]
            total += loc
            if results[mid][sid][cond]:
                passed += loc
        if total == 0:
            return None
        return passed / total

    out = {}

    # R1: scaled_pass1 — LOC-weighted success rate
    out["scaled_pass1"] = {
        m: round(loc_weighted(m, "with_paper"), 6) for m in model_ids
    }

    # R2: contamination_safe — strict > comparison, null when no safe snippets
    cs = {}
    for mid, cutoff in models.items():
        safe = set()
        for pid, commit in papers.items():
            if commit > cutoff:
                safe.update(paper_snippets.get(pid, []))
        if not safe:
            cs[mid] = None
        else:
            v = loc_weighted(mid, "with_paper", safe)
            cs[mid] = round(v, 6) if v is not None else None
    out["contamination_safe_scaled_pass1"] = cs

    # R3: paper_ablation — LOC-weighted, with minus without
    out["paper_ablation_impact"] = {
        m: round(loc_weighted(m, "with_paper") - loc_weighted(m, "without_paper"), 6)
        for m in model_ids
    }

    # R4: bootstrap — paper-level stratified, seed 2024, 10000 iters
    out["bootstrap_ci"] = {}
    for mid in model_ids:
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
            "upper": round(scores[int(0.975 * 10000)], 6)
        }

    # R5: ranking — descending by contamination-safe, null last
    ranked = sorted(
        [(m, s) for m, s in cs.items() if s is not None],
        key=lambda x: -x[1]
    )
    ranking = [{"rank": i + 1, "model_id": m, "contamination_safe_score": s}
               for i, (m, s) in enumerate(ranked)]
    ranking += [{"rank": None, "model_id": m, "contamination_safe_score": None}
                for m, s in cs.items() if s is None]
    out["ranking"] = ranking

    # R6: pairwise significance — paired paper-level bootstrap, Bonferroni correction
    n_pairs = len(model_ids) * (len(model_ids) - 1) // 2
    alpha_corrected = 0.05 / n_pairs
    lo_pct = alpha_corrected / 2
    hi_pct = 1 - alpha_corrected / 2
    lo_idx = int(lo_pct * 10000)
    hi_idx = int(hi_pct * 10000)

    pairwise = {}
    for m1, m2 in combinations(model_ids, 2):
        rng = random.Random(2024)
        diffs = []
        for _ in range(10000):
            sampled = [rng.choice(paper_ids) for _ in range(len(paper_ids))]
            t = 0
            p1 = p2 = 0
            for pid in sampled:
                for sid in paper_snippets[pid]:
                    loc = snippets[sid]["loc"]
                    t += loc
                    if results[m1][sid]["with_paper"]:
                        p1 += loc
                    if results[m2][sid]["with_paper"]:
                        p2 += loc
            s1 = p1 / t if t else 0.0
            s2 = p2 / t if t else 0.0
            diffs.append(s1 - s2)
        diffs.sort()
        lo = diffs[lo_idx]
        hi = diffs[hi_idx]
        sig = lo > 0 or hi < 0
        pair_key = f"{m1}_vs_{m2}"
        pairwise[pair_key] = {
            "model_a": m1,
            "model_b": m2,
            "ci_lower": round(lo, 6),
            "ci_upper": round(hi, 6),
            "significant": sig
        }
    out["pairwise_significance"] = pairwise

    # R7: jackknife stability — leave-one-paper-out analysis
    n = len(paper_ids)
    jackknife = {}
    for mid in model_ids:
        full_score = loc_weighted(mid, "with_paper")
        loo_scores = {}
        for pid in paper_ids:
            remaining_sids = set(sid for sid in all_sids
                                 if snippets[sid]["paper_id"] != pid)
            loo_scores[pid] = loc_weighted(mid, "with_paper", remaining_sids)

        theta_bar = sum(loo_scores.values()) / n
        variance = (n - 1) / n * sum((t - theta_bar) ** 2
                                      for t in loo_scores.values())
        se = math.sqrt(variance)

        influence = {pid: abs(full_score - s) for pid, s in loo_scores.items()}
        most_influential = max(influence, key=influence.get)

        jackknife[mid] = {
            "jackknife_se": round(se, 6),
            "most_influential_paper": most_influential,
            "influence_magnitude": round(influence[most_influential], 6),
            "leave_one_out_scores": {pid: round(s, 6)
                                     for pid, s in sorted(loo_scores.items())}
        }
    out["jackknife_stability"] = jackknife

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/analysis.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
