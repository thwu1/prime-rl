#!/usr/bin/env python3
"""Solution: complete forecaster ranking audit pipeline.

Implements all seven required analyses from first principles.
"""

import json
import os
import math
from collections import defaultdict


def load_data():
    with open("/app/data/problems.json") as f:
        problems = json.load(f)
    with open("/app/data/predictions.json") as f:
        predictions = json.load(f)
    return problems, predictions


# ── 1. Brier scores ──────────────────────────────────────────────────────

def compute_brier(problems, predictions):
    prob_map = {p["problem_id"]: p for p in problems}
    user_scores = defaultdict(list)

    for pred in predictions:
        c = prob_map[pred["problem_id"]]["correct_option_idx"]
        brier = sum(
            (pred["probs"][j] - (1 if j == c else 0)) ** 2
            for j in range(len(pred["probs"]))
        )
        user_scores[pred["username"]].append(brier)

    means = {u: sum(s) / len(s) for u, s in user_scores.items()}
    ranked = sorted(means.items(), key=lambda x: x[1])
    return [
        {"username": u, "brier_score": round(s, 8), "rank": i + 1}
        for i, (u, s) in enumerate(ranked)
    ]


# ── 2. CRRA returns ─────────────────────────────────────────────────────

def _crra_return_for_r(problems, predictions, r):
    prob_map = {p["problem_id"]: p for p in problems}
    user_rets = defaultdict(list)

    for pred in predictions:
        prob = prob_map[pred["problem_id"]]
        c = prob["correct_option_idx"]
        probs = pred["probs"]
        odds = prob["market_odds"]

        edges = [probs[k] / max(odds[k], 0.001) for k in range(len(probs))]
        k_star = edges.index(max(edges))

        if r == 0:
            net = (1.0 / odds[k_star] - 1.0) if k_star == c else -1.0
        else:
            p_s, o_s = probs[k_star], odds[k_star]
            kelly = max(0.0, (p_s - o_s) / (1.0 - o_s)) if o_s < 1.0 else 0.0
            f = min(kelly / r, 1.0)
            net = f * (1.0 / o_s - 1.0) if k_star == c else -f

        user_rets[pred["username"]].append(net)

    return {u: sum(v) / len(v) for u, v in user_rets.items()}


def compute_crra(problems, predictions):
    r0 = _crra_return_for_r(problems, predictions, 0.0)
    r05 = _crra_return_for_r(problems, predictions, 0.5)
    r1 = _crra_return_for_r(problems, predictions, 1.0)

    usernames = sorted(r05, key=lambda u: r05[u], reverse=True)
    return [
        {
            "username": u,
            "return_r0": round(r0[u], 8),
            "return_r05": round(r05[u], 8),
            "return_r1": round(r1[u], 8),
            "rank": i + 1,
        }
        for i, u in enumerate(usernames)
    ]


# ── 3. Bradley-Terry (MM algorithm) ─────────────────────────────────────

def compute_bt(problems, predictions):
    prob_map = {p["problem_id"]: p for p in problems}

    # Build correct-outcome probability per (problem, user)
    user_pc = defaultdict(dict)
    for pred in predictions:
        c = prob_map[pred["problem_id"]]["correct_option_idx"]
        user_pc[pred["problem_id"]][pred["username"]] = pred["probs"][c]

    usernames = sorted({p["username"] for p in predictions})
    n = len(usernames)
    uid = {u: i for i, u in enumerate(usernames)}

    wins = [[0.0] * n for _ in range(n)]
    comps = [[0] * n for _ in range(n)]

    for pid, up in user_pc.items():
        ul = list(up.keys())
        for a in range(len(ul)):
            for b in range(a + 1, len(ul)):
                ia, ib = uid[ul[a]], uid[ul[b]]
                pa, pb = up[ul[a]], up[ul[b]]
                comps[ia][ib] += 1
                comps[ib][ia] += 1
                if pa > pb:
                    wins[ia][ib] += 1
                elif pb > pa:
                    wins[ib][ia] += 1
                else:
                    wins[ia][ib] += 0.5
                    wins[ib][ia] += 0.5

    # MM iterations
    theta = [1.0] * n
    for _ in range(1000):
        old = theta[:]
        new_t = [0.0] * n
        for i in range(n):
            wi = sum(wins[i])
            denom = sum(
                comps[i][j] / (theta[i] + theta[j])
                for j in range(n) if j != i and comps[i][j] > 0
            )
            new_t[i] = wi / denom if denom > 0 and wi > 0 else theta[i]

        s = sum(new_t)
        theta = [t * n / s for t in new_t]

        if max(abs(theta[i] - old[i]) for i in range(n)) < 1e-12:
            break

    ranked = sorted(
        [(usernames[i], theta[i]) for i in range(n)],
        key=lambda x: x[1],
        reverse=True,
    )
    return [
        {"username": u, "skill": round(sk, 8), "rank": i + 1}
        for i, (u, sk) in enumerate(ranked)
    ]


# ── 4. Spearman rank correlations ───────────────────────────────────────

def _spearman(rx, ry):
    n = len(rx)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1.0 - 6.0 * d2 / (n * (n ** 2 - 1))


def compute_correlations(brier, crra, bt):
    br = {e["username"]: e["rank"] for e in brier}
    cr = {e["username"]: e["rank"] for e in crra}
    btr = {e["username"]: e["rank"] for e in bt}

    users = sorted(br)
    bv = [br[u] for u in users]
    cv = [cr[u] for u in users]
    tv = [btr[u] for u in users]

    return {
        "brier_crra": round(_spearman(bv, cv), 6),
        "brier_bt": round(_spearman(bv, tv), 6),
        "crra_bt": round(_spearman(cv, tv), 6),
    }


# ── 5. Sybil detection ──────────────────────────────────────────────────

def detect_sybils(problems, predictions):
    prob_ids = sorted({p["problem_id"] for p in problems})
    uv = defaultdict(dict)
    for pred in predictions:
        uv[pred["username"]][pred["problem_id"]] = pred["probs"][0]

    users = sorted(uv)
    vecs = {u: [uv[u].get(pid, 0.5) for pid in prob_ids] for u in users}

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    pairs = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            sim = cosine(vecs[users[i]], vecs[users[j]])
            if sim > 0.99:
                pairs.append({
                    "pair": [users[i], users[j]],
                    "cosine_similarity": round(sim, 8),
                })
    return pairs


# ── 6. Borda consensus ──────────────────────────────────────────────────

def compute_consensus(brier, crra, bt):
    n = len(brier)
    crra_data = {e["username"]: e for e in crra}

    # CRRA r=0 ranking
    c0_sorted = sorted(crra_data.values(), key=lambda x: x["return_r0"], reverse=True)
    c0_rank = {e["username"]: i + 1 for i, e in enumerate(c0_sorted)}

    # CRRA r=0.5 ranking
    c05_rank = {e["username"]: e["rank"] for e in crra}

    # CRRA r=1.0 ranking
    c1_sorted = sorted(crra_data.values(), key=lambda x: x["return_r1"], reverse=True)
    c1_rank = {e["username"]: i + 1 for i, e in enumerate(c1_sorted)}

    br = {e["username"]: e["rank"] for e in brier}
    btr = {e["username"]: e["rank"] for e in bt}

    borda = {}
    for u in br:
        borda[u] = (
            (n - br[u] + 1)
            + (n - c0_rank[u] + 1)
            + (n - c05_rank[u] + 1)
            + (n - c1_rank[u] + 1)
            + (n - btr[u] + 1)
        )

    ranked = sorted(borda.items(), key=lambda x: x[1], reverse=True)
    return [
        {"username": u, "borda_points": p, "rank": i + 1}
        for i, (u, p) in enumerate(ranked)
    ]


# ── 7. Murphy decomposition ─────────────────────────────────────────────

def compute_murphy(problems, predictions):
    prob_map = {p["problem_id"]: p for p in problems}
    user_pairs = defaultdict(list)

    for pred in predictions:
        c = prob_map[pred["problem_id"]]["correct_option_idx"]
        user_pairs[pred["username"]].append((pred["probs"][0], 1 if c == 0 else 0))

    results = []
    for username in sorted(user_pairs):
        pairs = user_pairs[username]
        N = len(pairs)
        o_bar = sum(o for _, o in pairs) / N
        unc = o_bar * (1.0 - o_bar)

        bins = [[] for _ in range(10)]
        for f_val, o_val in pairs:
            idx = min(int(f_val * 10), 9)
            bins[idx].append((f_val, o_val))

        rel = 0.0
        res = 0.0
        for b in bins:
            if not b:
                continue
            nk = len(b)
            fk = sum(x[0] for x in b) / nk
            ok = sum(x[1] for x in b) / nk
            rel += nk * (fk - ok) ** 2
            res += nk * (ok - o_bar) ** 2
        rel /= N
        res /= N

        results.append({
            "username": username,
            "reliability": round(rel, 8),
            "resolution": round(res, 8),
            "uncertainty": round(unc, 8),
            "brier_class0": round(rel - res + unc, 8),
        })

    return results


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    problems, predictions = load_data()
    os.makedirs("/app/results", exist_ok=True)

    brier = compute_brier(problems, predictions)
    crra = compute_crra(problems, predictions)
    bt = compute_bt(problems, predictions)
    corr = compute_correlations(brier, crra, bt)
    sybils = detect_sybils(problems, predictions)
    consensus = compute_consensus(brier, crra, bt)
    murphy = compute_murphy(problems, predictions)

    outputs = {
        "brier_rankings.json": brier,
        "crra_returns.json": crra,
        "bt_rankings.json": bt,
        "rank_correlations.json": corr,
        "sybil_report.json": sybils,
        "consensus_ranking.json": consensus,
        "calibration_decomposition.json": murphy,
    }

    for fname, data in outputs.items():
        with open(f"/app/results/{fname}", "w") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote /app/results/{fname}")


if __name__ == "__main__":
    main()
