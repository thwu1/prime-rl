#!/usr/bin/env python3
"""Generate multi-source prediction market platform data with embedded integrity issues.

Data sources created:
1. SQLite database (/app/data/platform.db)
2. Parquet market feed (/app/data/market_feed/market_ticks.parquet)
3. NDJSON scoring pipeline logs (/app/data/logs/scoring_pipeline.ndjson)
"""
import sqlite3
import json
import random
import os
import math
from collections import defaultdict


random.seed(20250612)

DB_PATH = "/app/data/platform.db"
FEED_DIR = "/app/data/market_feed"
LOGS_DIR = "/app/data/logs"

for d in ["/app/data", FEED_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)


def logit(p):
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def probit(p):
    """Inverse standard normal CDF (Abramowitz & Stegun 26.2.23)."""
    p = max(1e-6, min(1 - 1e-6, p))
    if abs(p - 0.5) < 1e-10:
        return 0.0
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
        sign = -1
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        sign = 1
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return sign * (t - (c0 + c1 * t + c2 * t ** 2) / (1 + d1 * t + d2 * t ** 2 + d3 * t ** 3))


# ── Constants ────────────────────────────────────────────────────────────

FORECASTERS = [
    (1,  "ace_alpha",      0.88, 1),
    (2,  "bravo_brain",    0.84, 1),
    (3,  "charlie_calc",   0.78, 1),
    (4,  "delta_data",     0.74, 1),
    (5,  "echo_edge",      0.70, 1),
    (6,  "foxtrot_fox",    0.66, 1),
    (7,  "golf_guru",      0.62, 1),
    (8,  "hotel_hawk",     0.58, 1),
    (9,  "india_intel",    0.54, 1),
    (10, "juliet_judge",   0.50, 1),
    (11, "kilo_keen",      0.46, 1),
    (12, "lima_logic",     0.42, 1),
    (13, "mike_maven",     0.38, 1),
    (14, "november_node",  0.34, 1),
    (15, "oscar_oracle",   0.72, 1),
    (16, "shadow_fox",     -1,   1),   # sybil copy of foxtrot_fox
    (17, "papa_prime",     0.60, 1),
    (18, "quebec_quant",   0.56, 1),
    (19, "romeo_rank",     0.48, 0),   # unverified
    (20, "sierra_stats",   0.44, 0),   # unverified
]

CATEGORIES = ["politics", "finance", "sports", "technology", "entertainment"]
NUM_PROBLEMS = 50
LATE_PROBLEMS = {3, 7, 15, 22, 31, 38, 44, 48}
STALE_ODDS_PROBLEMS = {8, 17, 29, 36, 42}

# ── SQLite Database ──────────────────────────────────────────────────────

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""CREATE TABLE forecasters (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    is_verified INTEGER NOT NULL DEFAULT 1
)""")

cur.execute("""CREATE TABLE problems (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    num_options INTEGER NOT NULL DEFAULT 2,
    correct_option_idx INTEGER NOT NULL,
    resolved_at TEXT NOT NULL,
    market_odds TEXT NOT NULL
)""")

cur.execute("""CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecaster_id INTEGER NOT NULL,
    problem_id INTEGER NOT NULL,
    probs TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    FOREIGN KEY (forecaster_id) REFERENCES forecasters(id),
    FOREIGN KEY (problem_id) REFERENCES problems(id)
)""")

cur.execute("""CREATE TABLE published_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    score REAL NOT NULL,
    rank INTEGER NOT NULL,
    method TEXT NOT NULL
)""")

cur.execute("""CREATE TABLE irt_item_params (
    problem_id INTEGER PRIMARY KEY,
    discrimination REAL NOT NULL,
    difficulty REAL NOT NULL,
    estimation_method TEXT NOT NULL DEFAULT '2PL',
    FOREIGN KEY (problem_id) REFERENCES problems(id)
)""")

cur.execute("""CREATE TABLE irt_abilities (
    forecaster_id INTEGER PRIMARY KEY,
    ability REAL NOT NULL,
    standard_error REAL NOT NULL,
    FOREIGN KEY (forecaster_id) REFERENCES forecasters(id)
)""")

cur.execute("CREATE INDEX idx_pred_forecaster ON predictions(forecaster_id)")
cur.execute("CREATE INDEX idx_pred_problem ON predictions(problem_id)")

# Insert forecasters
for fid, uname, _, verified in FORECASTERS:
    cur.execute("INSERT INTO forecasters VALUES (?, ?, ?, ?)",
                (fid, uname, "2024-01-15T10:00:00Z", verified))

# ── Generate Problems ────────────────────────────────────────────────────

problems_meta = []
true_market_odds = {}

for i in range(1, NUM_PROBLEMS + 1):
    correct = random.randint(0, 1)
    cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
    mp0_true = round(0.25 + random.random() * 0.50, 4)
    true_market_odds[i] = [mp0_true, round(1.0 - mp0_true, 4)]

    if i in STALE_ODDS_PROBLEMS:
        shift = random.choice([-1, 1]) * (0.10 + random.random() * 0.10)
        mp0_stale = round(max(0.10, min(0.90, mp0_true + shift)), 4)
        market_odds = [mp0_stale, round(1.0 - mp0_stale, 4)]
    else:
        market_odds = true_market_odds[i]

    day = 10 + ((i - 1) % 20)
    resolved_at = "2025-03-{:02d}T18:00:00Z".format(day)

    cur.execute("INSERT INTO problems VALUES (?, ?, ?, ?, ?, ?, ?)",
                (i, "Will event {} occur by the deadline?".format(i), cat, 2,
                 correct, resolved_at, json.dumps(market_odds)))
    problems_meta.append({
        "id": i, "correct": correct, "market_odds": market_odds,
        "true_market_odds": true_market_odds[i], "resolved_at": resolved_at,
    })

# ── Generate Predictions ─────────────────────────────────────────────────

foxtrot_probs = {}
all_predictions = []

for prob in problems_meta:
    pid = prob["id"]
    correct = prob["correct"]

    for fid, uname, skill, _ in FORECASTERS:
        if uname == "oscar_oracle" and pid in LATE_PROBLEMS:
            submitted_at = prob["resolved_at"].replace("18:00:00", "19:30:00")
        else:
            submitted_at = prob["resolved_at"].replace("18:00:00", "08:00:00")

        if skill < 0:
            base_p0 = foxtrot_probs[pid]
            noise = random.gauss(0, 0.008)
            p0 = max(0.01, min(0.99, base_p0 + noise))
        else:
            if random.random() < skill:
                if correct == 0:
                    p0 = 0.55 + random.random() * 0.38
                else:
                    p0 = 0.07 + random.random() * 0.38
            else:
                if correct == 0:
                    p0 = 0.07 + random.random() * 0.38
                else:
                    p0 = 0.55 + random.random() * 0.38

        p0 = round(p0, 6)
        probs = [p0, round(1.0 - p0, 6)]

        if uname == "foxtrot_fox":
            foxtrot_probs[pid] = p0

        cur.execute(
            "INSERT INTO predictions (forecaster_id, problem_id, probs, submitted_at) "
            "VALUES (?, ?, ?, ?)",
            (fid, pid, json.dumps(probs), submitted_at))
        all_predictions.append((fid, uname, pid, probs, correct, submitted_at))

# ── Published Rankings (BUG: single-class Brier for id >= 11) ────────────

prob_correct = {p["id"]: p["correct"] for p in problems_meta}

cur.execute("""
    SELECT p.forecaster_id, p.problem_id, p.probs, f.username
    FROM predictions p JOIN forecasters f ON p.forecaster_id = f.id
""")
rows = cur.fetchall()

fid_preds = defaultdict(list)
for fid, pid, probs_str, uname in rows:
    fid_preds[(fid, uname)].append((pid, json.loads(probs_str)))

published_scores = {}
for (fid, uname), preds in fid_preds.items():
    scores = []
    for pid, probs in preds:
        c = prob_correct[pid]
        if fid >= 11:
            brier = (probs[0] - (1 if c == 0 else 0)) ** 2  # BUG: single-class
        else:
            brier = sum((probs[j] - (1 if j == c else 0)) ** 2 for j in range(2))
        scores.append(brier)
    published_scores[uname] = sum(scores) / len(scores)

ranked = sorted(published_scores.items(), key=lambda x: x[1])
for rank, (uname, score) in enumerate(ranked, 1):
    cur.execute(
        "INSERT INTO published_rankings (username, score, rank, method) VALUES (?, ?, ?, ?)",
        (uname, round(score, 8), rank, "brier"))

# ── IRT Parameters (BUG: probit link function instead of logit) ──────────

correctness = {}
for fid, uname, pid, probs, correct, submitted_at in all_predictions:
    predicted = 0 if probs[0] > 0.5 else 1
    correctness[(fid, pid)] = 1 if predicted == correct else 0

# Per-forecaster total scores for point-biserial computation
total_scores = {}
for fid, _, _, _ in FORECASTERS:
    total_scores[fid] = sum(correctness.get((fid, p), 0) for p in range(1, NUM_PROBLEMS + 1))

mean_total = sum(total_scores.values()) / len(total_scores)
var_total = sum((t - mean_total) ** 2 for t in total_scores.values()) / len(total_scores)
sd_total = max(var_total ** 0.5, 0.01)

for pid in range(1, NUM_PROBLEMS + 1):
    responses = [correctness.get((fid, pid), 0) for fid, _, _, _ in FORECASTERS]
    p_val = sum(responses) / len(responses)
    p_clamped = max(0.02, min(0.98, p_val))

    correct_group = [total_scores[fid] for fid, _, _, _ in FORECASTERS
                     if correctness.get((fid, pid)) == 1]
    incorrect_group = [total_scores[fid] for fid, _, _, _ in FORECASTERS
                       if correctness.get((fid, pid)) == 0]

    if correct_group and incorrect_group:
        mc = sum(correct_group) / len(correct_group)
        mi = sum(incorrect_group) / len(incorrect_group)
        rpb = (mc - mi) * (p_clamped * (1 - p_clamped)) ** 0.5 / sd_total
    else:
        rpb = 0.5

    disc = max(0.3, min(2.5, abs(rpb) * 2.5))
    difficulty_buggy = -probit(p_clamped)  # BUG: probit instead of logit

    cur.execute("INSERT INTO irt_item_params VALUES (?, ?, ?, ?)",
                (pid, round(disc, 4), round(difficulty_buggy, 4), "2PL"))

for fid, uname, _, _ in FORECASTERS:
    prop_correct = total_scores[fid] / NUM_PROBLEMS
    ability_buggy = probit(max(0.02, min(0.98, prop_correct)))  # BUG: probit
    se = round(0.2 + random.random() * 0.3, 4)
    cur.execute("INSERT INTO irt_abilities VALUES (?, ?, ?)",
                (fid, round(ability_buggy, 4), se))

conn.commit()
conn.close()

# ── Parquet Market Feed ──────────────────────────────────────────────────

import pyarrow as pa
import pyarrow.parquet as pq

feed_data = {
    "problem_id": [],
    "tick_seq": [],
    "hours_before_close": [],
    "mid_price": [],
    "bid_price": [],
    "ask_price": [],
    "volume": [],
}

for prob in problems_meta:
    pid = prob["id"]
    true_close = prob["true_market_odds"][0]
    sqlite_odds = prob["market_odds"][0]

    for tick in range(25):
        hrs_before = 24 - tick
        if pid in STALE_ODDS_PROBLEMS:
            if hrs_before == 0:
                price = true_close
            elif hrs_before == 4:
                price = sqlite_odds
            elif hrs_before < 4:
                frac = (4.0 - hrs_before) / 4.0
                target = sqlite_odds + frac * (true_close - sqlite_odds)
                noise = random.gauss(0, 0.006)
                price = max(0.05, min(0.95, target + noise))
            else:
                noise = random.gauss(0, 0.012)
                price = max(0.05, min(0.95, sqlite_odds + noise))
        else:
            if hrs_before == 0:
                price = true_close
            else:
                noise = random.gauss(0, 0.008 * (hrs_before / 24.0))
                price = max(0.05, min(0.95, true_close + noise))

        spread = random.uniform(0.003, 0.008)
        feed_data["problem_id"].append(pid)
        feed_data["tick_seq"].append(tick)
        feed_data["hours_before_close"].append(hrs_before)
        feed_data["mid_price"].append(round(price, 6))
        feed_data["bid_price"].append(round(price - spread / 2, 6))
        feed_data["ask_price"].append(round(price + spread / 2, 6))
        feed_data["volume"].append(random.randint(10, 500))

table = pa.table(feed_data)
pq.write_table(table, os.path.join(FEED_DIR, "market_ticks.parquet"))

# ── Scoring Pipeline Logs (NDJSON) ───────────────────────────────────────

log_entries = [
    {"ts": "2025-03-30T02:00:00Z", "level": "INFO", "step": "pipeline_init",
     "msg": "Scoring pipeline v3.2.1 starting",
     "details": {"run_id": "run-20250330-001", "config_version": "3.2.1"}},
    {"ts": "2025-03-30T02:00:01Z", "level": "INFO", "step": "data_load",
     "msg": "Loading predictions from platform.db",
     "details": {"forecasters": 20, "problems": 50, "total_predictions": 1000}},
    {"ts": "2025-03-30T02:00:02Z", "level": "INFO", "step": "data_validation",
     "msg": "Running data quality checks",
     "details": {"null_probs": 0, "out_of_range": 0, "schema_valid": True}},
    {"ts": "2025-03-30T02:00:02Z", "level": "DEBUG", "step": "timestamp_check",
     "msg": "Submission timestamps within expected window",
     "details": {"earliest": "2025-03-10T08:00:00Z", "latest": "2025-03-29T19:30:00Z"}},
    {"ts": "2025-03-30T02:00:03Z", "level": "INFO", "step": "market_odds_load",
     "msg": "Loading market odds from external feed",
     "details": {"source": "market_feed/market_ticks.parquet", "status": "partial"}},
    {"ts": "2025-03-30T02:00:03Z", "level": "WARNING", "step": "market_odds_load",
     "msg": "Feed timeout for 5 problems, falling back to cached odds from T-4h",
     "details": {"cached_problem_ids": sorted(STALE_ODDS_PROBLEMS),
                 "cache_age_hours": 4, "reason": "exchange_api_timeout"}},
    {"ts": "2025-03-30T02:00:04Z", "level": "INFO", "step": "brier_compute",
     "msg": "Computing Brier scores for batch 1 (forecaster_id 1-10)",
     "config": {"forecaster_id_range": "1-10", "formula": "full_multiclass",
                "num_classes": 2}},
    {"ts": "2025-03-30T02:00:04Z", "level": "INFO", "step": "brier_compute",
     "msg": "Computing Brier scores for batch 2 (forecaster_id 11-20)",
     "config": {"forecaster_id_range": "11-20", "formula": "single_class",
                "target_class": 0}},
    {"ts": "2025-03-30T02:00:05Z", "level": "INFO", "step": "brier_aggregate",
     "msg": "Aggregating Brier scores across batches",
     "details": {"total_forecasters": 20, "batches_merged": 2}},
    {"ts": "2025-03-30T02:00:06Z", "level": "INFO", "step": "log_score_compute",
     "msg": "Computing logarithmic scoring rule",
     "config": {"base": "natural", "epsilon": 1e-10}},
    {"ts": "2025-03-30T02:00:07Z", "level": "INFO", "step": "bt_estimation",
     "msg": "Fitting Generalized Bradley-Terry model",
     "config": {"method": "MM", "max_iterations": 2000, "tolerance": 1e-12}},
    {"ts": "2025-03-30T02:00:09Z", "level": "INFO", "step": "bt_estimation",
     "msg": "Bradley-Terry converged",
     "details": {"iterations": 342, "final_diff": 8.7e-13}},
    {"ts": "2025-03-30T02:00:10Z", "level": "INFO", "step": "irt_estimation",
     "msg": "Starting IRT 2-PL parameter estimation",
     "config": {"model": "2PL", "link_function": "probit",
                "optimizer": "EM", "max_iterations": 500,
                "convergence_threshold": 1e-6}},
    {"ts": "2025-03-30T02:00:15Z", "level": "INFO", "step": "irt_estimation",
     "msg": "IRT estimation converged",
     "details": {"iterations": 127, "final_log_likelihood": -4521.3,
                 "mean_ability": 0.02, "sd_ability": 0.61}},
    {"ts": "2025-03-30T02:00:16Z", "level": "INFO", "step": "ranking_aggregate",
     "msg": "Building composite rankings",
     "config": {"methods": ["brier", "log_score"],
                "aggregation": "weighted_average",
                "weights": {"brier": 0.6, "log_score": 0.4}}},
    {"ts": "2025-03-30T02:00:17Z", "level": "INFO", "step": "output_write",
     "msg": "Writing published_rankings to database",
     "details": {"rows_written": 20, "table": "published_rankings"}},
    {"ts": "2025-03-30T02:00:17Z", "level": "INFO", "step": "irt_output_write",
     "msg": "Writing IRT parameters to database",
     "details": {"item_params": 50, "abilities": 20,
                 "tables": ["irt_item_params", "irt_abilities"]}},
    {"ts": "2025-03-30T02:00:18Z", "level": "INFO", "step": "pipeline_complete",
     "msg": "Scoring pipeline completed successfully",
     "details": {"duration_sec": 18, "status": "success"}},
]

with open(os.path.join(LOGS_DIR, "scoring_pipeline.ndjson"), "w") as f:
    for entry in log_entries:
        f.write(json.dumps(entry) + "\n")

print("Generated database at {}".format(DB_PATH))
print("Generated Parquet feed at {}/market_ticks.parquet".format(FEED_DIR))
print("Generated logs at {}/scoring_pipeline.ndjson".format(LOGS_DIR))
print("  {} forecasters, {} problems".format(len(FORECASTERS), NUM_PROBLEMS))
print("  Late submissions: oscar_oracle on problems {}".format(sorted(LATE_PROBLEMS)))
print("  Sybil pair: foxtrot_fox / shadow_fox")
print("  Stale odds: problems {}".format(sorted(STALE_ODDS_PROBLEMS)))
print("  Scoring bug: single-class Brier for forecaster ids >= 11")
print("  IRT bug: probit link function instead of logit")
