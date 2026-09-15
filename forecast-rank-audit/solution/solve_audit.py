#!/usr/bin/env python3
"""Reference solution: forensic audit of prediction market scoring pipeline.

Cross-references SQLite, Parquet market feed, and NDJSON pipeline logs to
discover data integrity issues, scoring bugs, and IRT parameter errors.
"""

import sqlite3
import json
import math
import os
from collections import defaultdict

DB_PATH = "/app/data/platform.db"
PARQUET_PATH = "/app/data/market_feed/market_ticks.parquet"
LOGS_PATH = "/app/data/logs/scoring_pipeline.ndjson"
RESULTS_DIR = "/app/results"


def logit(p):
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # ── Phase 1: Read all data sources ───────────────────────────────────

    # Read Parquet market feed
    import pyarrow.parquet as pq
    table = pq.read_table(PARQUET_PATH)
    feed = table.to_pydict()
    closing_prices = {}
    for i in range(len(feed["problem_id"])):
        if feed["hours_before_close"][i] == 0:
            closing_prices[feed["problem_id"][i]] = feed["mid_price"][i]

    # Read NDJSON pipeline logs
    log_entries = []
    with open(LOGS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                log_entries.append(json.loads(line))

    # ── Phase 2: Discover data integrity issues ──────────────────────────

    issues, late_pred_ids = discover_issues(conn, closing_prices)

    # ── Phase 3: Compute corrected rankings ──────────────────────────────

    clean_data = get_clean_data(conn, late_pred_ids)
    brier_scores = compute_full_brier(clean_data)
    log_scores = compute_log_score(clean_data)

    # IRT 2-PL with logit link (correct)
    correctness_matrix, forecaster_list, problem_list = build_correctness(conn, late_pred_ids)
    irt_items, irt_abilities = estimate_irt_logit(correctness_matrix, forecaster_list, problem_list)
    irt_ability_map = {a["username"]: a["ability"] for a in irt_abilities}

    rankings = aggregate_rankings(brier_scores, log_scores, irt_ability_map)

    # ── Phase 4: Identify platform bugs ──────────────────────────────────

    bugs = identify_platform_bugs(conn, log_entries, closing_prices)

    # ── Phase 5: IRT analysis ────────────────────────────────────────────

    irt_analysis = build_irt_analysis(conn, irt_items, irt_abilities)

    # ── Phase 6: Robustness analysis ─────────────────────────────────────

    robustness = analyze_robustness(brier_scores, log_scores, irt_ability_map)

    # ── Write outputs ────────────────────────────────────────────────────

    for fname, data in [
        ("data_issues.json", issues),
        ("corrected_rankings.json", rankings),
        ("platform_bugs.json", bugs),
        ("irt_analysis.json", irt_analysis),
        ("robustness.json", robustness),
    ]:
        with open(os.path.join(RESULTS_DIR, fname), "w") as f:
            json.dump(data, f, indent=2)
        print("Wrote {}".format(fname))

    conn.close()


# ── Data issue discovery ─────────────────────────────────────────────────

def discover_issues(conn, closing_prices):
    cur = conn.cursor()
    issues = []

    # Issue 1: Late submissions
    cur.execute("""
        SELECT f.username, p.problem_id, p.submitted_at, pr.resolved_at, p.id
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        JOIN problems pr ON p.problem_id = pr.id
        WHERE p.submitted_at > pr.resolved_at
    """)
    late_rows = cur.fetchall()
    late_pred_ids = set()

    if late_rows:
        affected_users = sorted(set(r[0] for r in late_rows))
        affected_problems = sorted(set(r[1] for r in late_rows))
        late_pred_ids = {r[4] for r in late_rows}
        issues.append({
            "issue_type": "late_submissions",
            "description": (
                "Found {} predictions submitted after problem resolution (submitted_at > "
                "resolved_at). Affected forecaster(s): {}. These predictions have look-ahead "
                "bias and must be excluded from fair scoring.".format(
                    len(late_rows), affected_users)
            ),
            "affected_entities": affected_users,
            "evidence": {
                "count": len(late_rows),
                "affected_problems": affected_problems,
                "example": {
                    "username": late_rows[0][0],
                    "problem_id": late_rows[0][1],
                    "submitted_at": late_rows[0][2],
                    "resolved_at": late_rows[0][3],
                },
            },
        })

    # Issue 2: Sybil detection via cosine similarity
    cur.execute("""
        SELECT f.username, p.problem_id, p.probs
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        ORDER BY f.username, p.problem_id
    """)
    rows = cur.fetchall()

    user_vecs_raw = defaultdict(dict)
    for uname, pid, probs_str in rows:
        probs = json.loads(probs_str)
        user_vecs_raw[uname][pid] = probs[0]

    users = sorted(user_vecs_raw.keys())
    all_pids = sorted(set().union(*(set(v.keys()) for v in user_vecs_raw.values())))
    vecs = {u: [user_vecs_raw[u].get(pid, 0.5) for pid in all_pids] for u in users}

    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            sim = cosine_sim(vecs[users[i]], vecs[users[j]])
            if sim > 0.99:
                issues.append({
                    "issue_type": "sybil_duplicate_accounts",
                    "description": (
                        "Forecasters '{}' and '{}' have cosine similarity {:.6f} on their "
                        "prediction vectors, indicating they are likely the same entity.".format(
                            users[i], users[j], sim)
                    ),
                    "affected_entities": [users[i], users[j]],
                    "evidence": {"cosine_similarity": round(sim, 6)},
                })

    # Issue 3: Stale market odds (cross-reference Parquet vs SQLite)
    cur.execute("SELECT id, market_odds FROM problems")
    stale_problems = []
    for pid, odds_str in cur.fetchall():
        sqlite_odds = json.loads(odds_str)[0]
        if pid in closing_prices:
            parquet_close = closing_prices[pid]
            diff = abs(parquet_close - sqlite_odds)
            if diff > 0.05:
                stale_problems.append({
                    "problem_id": pid,
                    "sqlite_odds": round(sqlite_odds, 6),
                    "parquet_closing": round(parquet_close, 6),
                    "difference": round(diff, 6),
                })

    if stale_problems:
        issues.append({
            "issue_type": "stale_market_odds",
            "description": (
                "Market odds in SQLite differ from Parquet market feed closing prices for "
                "{} problems. The platform loaded cached/stale odds instead of the actual "
                "closing prices from the exchange feed.".format(len(stale_problems))
            ),
            "affected_entities": [sp["problem_id"] for sp in stale_problems],
            "evidence": {
                "discrepancies": stale_problems,
                "source": "market_feed/market_ticks.parquet (hours_before_close=0)",
            },
        })

    return issues, late_pred_ids


# ── Clean data extraction ────────────────────────────────────────────────

def get_clean_data(conn, exclude_pred_ids):
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.forecaster_id, p.problem_id, p.probs, f.username,
               pr.correct_option_idx, pr.market_odds
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        JOIN problems pr ON p.problem_id = pr.id
    """)
    rows = cur.fetchall()

    clean = []
    for pred_id, fid, pid, probs_str, uname, correct, odds_str in rows:
        if pred_id in exclude_pred_ids:
            continue
        clean.append({
            "problem_id": pid,
            "probs": json.loads(probs_str),
            "username": uname,
            "correct": correct,
            "market_odds": json.loads(odds_str),
        })
    return clean


# ── Scoring methods ──────────────────────────────────────────────────────

def compute_full_brier(clean_data):
    user_scores = defaultdict(list)
    for pred in clean_data:
        c = pred["correct"]
        probs = pred["probs"]
        brier = sum((probs[j] - (1 if j == c else 0)) ** 2 for j in range(len(probs)))
        user_scores[pred["username"]].append(brier)
    return {u: sum(s) / len(s) for u, s in user_scores.items()}


def compute_log_score(clean_data):
    user_scores = defaultdict(list)
    for pred in clean_data:
        c = pred["correct"]
        p_correct = max(pred["probs"][c], 1e-10)
        user_scores[pred["username"]].append(-math.log(p_correct))
    return {u: sum(s) / len(s) for u, s in user_scores.items()}


# ── IRT 2-PL estimation (logit link) ────────────────────────────────────

def build_correctness(conn, exclude_pred_ids):
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.forecaster_id, f.username, p.problem_id,
               p.probs, pr.correct_option_idx
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        JOIN problems pr ON p.problem_id = pr.id
    """)
    rows = cur.fetchall()

    correctness = {}
    forecasters_seen = {}
    problems_seen = set()

    for pred_id, fid, uname, pid, probs_str, correct_idx in rows:
        if pred_id in exclude_pred_ids:
            continue
        probs = json.loads(probs_str)
        predicted = probs.index(max(probs))
        correctness[(fid, pid)] = 1 if predicted == correct_idx else 0
        forecasters_seen[fid] = uname
        problems_seen.add(pid)

    forecaster_list = sorted(forecasters_seen.items())
    problem_list = sorted(problems_seen)
    return correctness, forecaster_list, problem_list


def estimate_irt_logit(correctness, forecaster_list, problem_list):
    """Estimate IRT 2-PL parameters using logit link function."""
    fids = [fid for fid, _ in forecaster_list]

    # Per-forecaster total scores
    total_scores = {}
    for fid, uname in forecaster_list:
        total_scores[fid] = sum(correctness.get((fid, p), 0) for p in problem_list)
    mean_total = sum(total_scores.values()) / len(total_scores)
    var_total = sum((t - mean_total) ** 2 for t in total_scores.values()) / len(total_scores)
    sd_total = max(var_total ** 0.5, 0.01)

    item_params = []
    for pid in problem_list:
        responses = [correctness.get((fid, pid), 0) for fid in fids]
        p_val = sum(responses) / len(responses)
        p_clamped = max(0.02, min(0.98, p_val))

        # Difficulty using LOGIT (correct link function)
        difficulty = -logit(p_clamped)

        # Discrimination via point-biserial correlation
        correct_group = [total_scores[fid] for fid in fids if correctness.get((fid, pid)) == 1]
        incorrect_group = [total_scores[fid] for fid in fids if correctness.get((fid, pid)) == 0]

        if correct_group and incorrect_group:
            mc = sum(correct_group) / len(correct_group)
            mi = sum(incorrect_group) / len(incorrect_group)
            rpb = (mc - mi) * (p_clamped * (1 - p_clamped)) ** 0.5 / sd_total
        else:
            rpb = 0.5

        discrimination = max(0.3, min(2.5, abs(rpb) * 2.5))

        item_params.append({
            "problem_id": pid,
            "difficulty": round(difficulty, 4),
            "discrimination": round(discrimination, 4),
        })

    # Abilities using LOGIT
    abilities = []
    for fid, uname in forecaster_list:
        prop_correct = total_scores[fid] / len(problem_list)
        prop_clamped = max(0.02, min(0.98, prop_correct))
        ability = logit(prop_clamped)
        abilities.append({"username": uname, "ability": round(ability, 4)})

    return item_params, abilities


# ── Ranking aggregation ──────────────────────────────────────────────────

def aggregate_rankings(brier_scores, log_scores, irt_abilities):
    users = sorted(brier_scores.keys())

    brier_ranked = sorted(users, key=lambda u: brier_scores[u])
    log_ranked = sorted(users, key=lambda u: log_scores[u])
    irt_ranked = sorted(users, key=lambda u: irt_abilities.get(u, 0), reverse=True)

    brier_rank = {u: i + 1 for i, u in enumerate(brier_ranked)}
    log_rank = {u: i + 1 for i, u in enumerate(log_ranked)}
    irt_rank = {u: i + 1 for i, u in enumerate(irt_ranked)}

    n = len(users)
    borda = {}
    for u in users:
        borda[u] = (
            (n - brier_rank[u] + 1)
            + (n - log_rank[u] + 1)
            + (n - irt_rank[u] + 1)
        )

    final_ranked = sorted(users, key=lambda u: borda[u], reverse=True)

    result = []
    for rank, u in enumerate(final_ranked, 1):
        result.append({
            "username": u,
            "brier_score": round(brier_scores[u], 6),
            "log_score": round(log_scores[u], 6),
            "irt_ability": round(irt_abilities.get(u, 0.0), 6),
            "brier_rank": brier_rank[u],
            "log_rank": log_rank[u],
            "irt_rank": irt_rank[u],
            "borda_points": borda[u],
            "final_rank": rank,
        })
    return result


# ── Platform bug identification ──────────────────────────────────────────

def identify_platform_bugs(conn, log_entries, closing_prices):
    cur = conn.cursor()
    bugs = []

    # Bug 1: Brier formula inconsistency (recompute and compare)
    cur.execute("""
        SELECT f.username, f.id, p.probs, pr.correct_option_idx
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        JOIN problems pr ON p.problem_id = pr.id
    """)
    rows = cur.fetchall()

    user_scores = defaultdict(list)
    user_fid = {}
    for uname, fid, probs_str, correct in rows:
        probs = json.loads(probs_str)
        brier = sum((probs[j] - (1 if j == correct else 0)) ** 2 for j in range(len(probs)))
        user_scores[uname].append(brier)
        user_fid[uname] = fid
    correct_all = {u: sum(s) / len(s) for u, s in user_scores.items()}

    cur.execute("SELECT username, score, rank FROM published_rankings WHERE method = 'brier'")
    published = {r[0]: {"score": r[1], "rank": r[2]} for r in cur.fetchall()}

    half_brier_users = []
    full_brier_users = []
    for u in correct_all:
        if u in published:
            pub = published[u]["score"]
            correct = correct_all[u]
            if abs(pub - correct / 2) < 0.03:
                half_brier_users.append(u)
            elif abs(pub - correct) < 0.05:
                full_brier_users.append(u)

    # Corroborate with pipeline logs
    brier_log_entries = [e for e in log_entries if e.get("step") == "brier_compute"]
    log_evidence = []
    for entry in brier_log_entries:
        config = entry.get("config", {})
        if "formula" in config:
            log_evidence.append({
                "forecaster_range": config.get("forecaster_id_range"),
                "formula": config["formula"],
            })

    if half_brier_users:
        bugs.append({
            "bug_type": "inconsistent_brier_formula",
            "description": (
                "Published rankings use inconsistent Brier score computation. "
                "Forecasters with id 1-10 use the correct full multi-class Brier, but "
                "forecasters with id 11-20 use single-class Brier (approximately half "
                "the correct value). Pipeline logs confirm two separate batches with "
                "different formulas: {}.".format(log_evidence)
            ),
            "affected_entities": sorted(half_brier_users),
            "impact": (
                "{} forecasters have artificially lower (better) scores due to "
                "single-class instead of full multi-class Brier".format(len(half_brier_users))
            ),
        })

    # Bug 2: IRT probit link function
    irt_log = [e for e in log_entries
               if e.get("step") == "irt_estimation" and "config" in e]
    irt_link = None
    for entry in irt_log:
        lf = entry.get("config", {}).get("link_function")
        if lf:
            irt_link = lf

    # Compare published IRT abilities with logit-estimated ones
    cur.execute("""
        SELECT f.username, ia.ability
        FROM irt_abilities ia JOIN forecasters f ON ia.forecaster_id = f.id
    """)
    published_abilities = dict(cur.fetchall())

    bugs.append({
        "bug_type": "irt_wrong_link_function",
        "description": (
            "Published IRT 2-PL parameters were estimated using the probit (normal CDF) "
            "link function instead of the standard logit (logistic) link. Pipeline logs "
            "confirm link_function='{}'. This compresses ability estimates toward zero "
            "by a factor of approximately 1/1.702, distorting the ability scale and "
            "underestimating the range of forecaster skill differences.".format(
                irt_link or "probit")
        ),
        "affected_entities": sorted(published_abilities.keys()),
        "impact": (
            "All {} forecaster ability estimates are on a compressed scale; "
            "extreme abilities (both high and low) are underestimated".format(
                len(published_abilities))
        ),
    })

    # Bug 3: Late data inclusion
    cur.execute("""
        SELECT f.username, COUNT(*)
        FROM predictions p
        JOIN forecasters f ON p.forecaster_id = f.id
        JOIN problems pr ON p.problem_id = pr.id
        WHERE p.submitted_at > pr.resolved_at
        GROUP BY f.username
    """)
    late_users = cur.fetchall()
    if late_users:
        bugs.append({
            "bug_type": "tainted_data_inclusion",
            "description": (
                "Published rankings included predictions submitted after problem "
                "resolution. {} has {} post-resolution predictions with "
                "hindsight-biased data.".format(late_users[0][0], late_users[0][1])
            ),
            "affected_entities": [r[0] for r in late_users],
            "impact": "Scores computed from tainted data with look-ahead bias",
        })

    # Bug 4: Stale market odds
    stale_log = [e for e in log_entries
                 if e.get("step") == "market_odds_load" and e.get("level") == "WARNING"]
    cached_ids = []
    for entry in stale_log:
        cached_ids = entry.get("details", {}).get("cached_problem_ids", [])

    if cached_ids:
        bugs.append({
            "bug_type": "stale_cached_market_odds",
            "description": (
                "Pipeline used cached market odds from T-4h for problems {} due to "
                "exchange API timeout. Parquet feed confirms the actual closing prices "
                "differ significantly from the cached values in SQLite.".format(cached_ids)
            ),
            "affected_entities": cached_ids,
            "impact": (
                "Any scoring method using market odds (e.g. CRRA returns) would be "
                "computed with incorrect odds for these {} problems".format(len(cached_ids))
            ),
        })

    return bugs


# ── IRT analysis output ──────────────────────────────────────────────────

def build_irt_analysis(conn, irt_items, irt_abilities):
    cur = conn.cursor()
    cur.execute("""
        SELECT f.username, ia.ability
        FROM irt_abilities ia JOIN forecasters f ON ia.forecaster_id = f.id
    """)
    published_abilities = dict(cur.fetchall())

    cur.execute("SELECT problem_id, difficulty, discrimination FROM irt_item_params")
    published_items = {r[0]: {"difficulty": r[1], "discrimination": r[2]}
                       for r in cur.fetchall()}

    ability_map = {a["username"]: a["ability"] for a in irt_abilities}
    common = set(ability_map.keys()) & set(published_abilities.keys())

    agent_range = max(ability_map[u] for u in common) - min(ability_map[u] for u in common)
    pub_range = max(published_abilities[u] for u in common) - min(published_abilities[u] for u in common)

    comparison_examples = []
    for u in sorted(common)[:5]:
        comparison_examples.append({
            "username": u,
            "published_ability": round(published_abilities[u], 4),
            "corrected_ability": round(ability_map[u], 4),
            "ratio": round(ability_map[u] / published_abilities[u], 3)
            if abs(published_abilities[u]) > 0.01 else None,
        })

    return {
        "item_parameters": irt_items,
        "abilities": irt_abilities,
        "published_comparison": {
            "description": (
                "Published IRT parameters were estimated with probit (normal CDF) link "
                "function instead of the standard logit (logistic) link. The probit link "
                "compresses ability estimates by approximately 1/1.702. Re-estimated "
                "ability range ({:.3f}) is {:.1f}x wider than published range ({:.3f}).".format(
                    agent_range, agent_range / max(pub_range, 0.001), pub_range)
            ),
            "link_function_error": "probit used instead of logit",
            "compression_factor": 1.702,
            "corrected_range": round(agent_range, 4),
            "published_range": round(pub_range, 4),
            "examples": comparison_examples,
        },
    }


# ── Robustness analysis ─────────────────────────────────────────────────

def analyze_robustness(brier_scores, log_scores, irt_abilities):
    users = sorted(brier_scores.keys())

    brier_ranked = sorted(users, key=lambda u: brier_scores[u])
    log_ranked = sorted(users, key=lambda u: log_scores[u])
    irt_ranked = sorted(users, key=lambda u: irt_abilities.get(u, 0), reverse=True)

    brier_rank = {u: i + 1 for i, u in enumerate(brier_ranked)}
    log_rank = {u: i + 1 for i, u in enumerate(log_ranked)}
    irt_rank = {u: i + 1 for i, u in enumerate(irt_ranked)}

    rank_variance = {}
    for u in users:
        ranks = [brier_rank[u], log_rank[u], irt_rank[u]]
        mean_r = sum(ranks) / len(ranks)
        var = sum((r - mean_r) ** 2 for r in ranks) / len(ranks)
        rank_variance[u] = round(var, 4)

    values = sorted(rank_variance.values())
    median_var = values[len(values) // 2]
    sensitive = sorted(u for u in users if rank_variance[u] > median_var)

    return {
        "rank_variance": rank_variance,
        "sensitive_forecasters": sensitive,
        "methods_used": ["brier", "log_score", "irt_2pl_logit"],
        "median_variance": round(median_var, 4),
    }


if __name__ == "__main__":
    main()
