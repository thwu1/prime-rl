#!/usr/bin/env python3
"""Coverage analysis pipeline for fuzzer benchmarking data.

Reads experiment configuration from pipeline config JSON, loads coverage
data from both FCOV binary files and SQLite database, then computes
novelty coverage metrics, cross-benchmark rankings, pairwise statistical
comparisons, and coverage velocity measurements.
"""

import json
import math
import os
import struct
import sqlite3
from collections import defaultdict
from itertools import combinations


DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
CONFIG_PATH = "/tmp/pipeline_config.json"


def load_config():
    """Load pipeline configuration produced by extract_config.sh."""
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_meta():
    """Load experiment metadata."""
    with open(os.path.join(DATA_DIR, "meta.json")) as f:
        return json.load(f)


def parse_cov_file(path):
    """Parse a binary FCOV coverage file and return {timestamp: edge_set}."""
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"FCOV":
            raise ValueError(f"Invalid magic in {path}: {magic!r}")
        version, edge_space, num_snapshots = struct.unpack("<III", f.read(12))
        if version != 1:
            raise ValueError(f"Unsupported FCOV version: {version}")
        snapshots = {}
        for _ in range(num_snapshots):
            timestamp, num_edges = struct.unpack("<II", f.read(8))
            edges = set()
            if num_edges > 0:
                edges = set(struct.unpack(f"<{num_edges}I", f.read(4 * num_edges)))
            snapshots[timestamp] = edges
        return snapshots


def load_fcov_data(meta):
    """Load coverage data from FCOV binary files for fcov_benchmarks."""
    data = {}
    for fuzzer in meta["fuzzers"]:
        for benchmark in meta["fcov_benchmarks"]:
            for trial in range(meta["trials"]):
                path = os.path.join(
                    DATA_DIR, fuzzer, benchmark,
                    f"trial_{trial:02d}", "coverage.cov"
                )
                for ts, edges in parse_cov_file(path).items():
                    data[(fuzzer, benchmark, trial, ts)] = edges
    return data


def load_db_data(meta):
    """Load coverage data from SQLite database for db_benchmarks."""
    data = {}
    db_path = meta.get("db_path", os.path.join(DATA_DIR, "experiment.db"))
    db = sqlite3.connect(db_path)

    for fuzzer in meta["fuzzers"]:
        for benchmark in meta["db_benchmarks"]:
            for trial in range(meta["trials"]):
                for ts in meta["snapshots_seconds"]:
                    # Query edges at this exact snapshot time
                    cursor = db.execute(
                        "SELECT DISTINCT edge_id FROM coverage "
                        "WHERE benchmark = ? AND fuzzer = ? AND trial = ? "
                        "AND snapshot_time = ?",
                        (benchmark, fuzzer, trial, ts)
                    )
                    edges = set(row[0] for row in cursor.fetchall())
                    data[(fuzzer, benchmark, trial, ts)] = edges

    db.close()
    return data


def compute_novelty_scores(data, meta, config):
    """Compute per-benchmark novelty coverage scores for each fuzzer."""
    alpha = config["tversky_alpha"]
    beta = config["tversky_beta"]
    final_ts = max(meta["snapshots_seconds"])
    num_fuzzers = len(meta["fuzzers"])
    num_trials = meta["trials"]

    results = {}
    rarity_cache = {}

    for benchmark in meta["benchmarks"]:
        results[benchmark] = {}

        # Collect per-trial and union edge sets for each fuzzer
        trial_edges = {}
        fuzzer_edges = {}
        for fuzzer in meta["fuzzers"]:
            all_edges = set()
            for t in range(num_trials):
                edges = data.get((fuzzer, benchmark, t, final_ts), set())
                trial_edges[(fuzzer, t)] = edges
                all_edges |= edges
            fuzzer_edges[fuzzer] = all_edges

        # Compute union of all edges across all fuzzers
        all_edges = set()
        for f in meta["fuzzers"]:
            all_edges |= fuzzer_edges[f]

        # Determine which fuzzers cover each edge and compute rarity
        edge_covering = {}
        for e in all_edges:
            covering = frozenset(
                f for f in meta["fuzzers"] if e in fuzzer_edges[f]
            )
            edge_covering[e] = covering
            # Edge coverage frequency across fuzzers
            rarity_cache[(benchmark, e)] = len(covering) / num_fuzzers

        # Score each fuzzer
        for fuzzer in meta["fuzzers"]:
            score = 0.0
            unique = 0
            for e in fuzzer_edges[fuzzer]:
                r = rarity_cache[(benchmark, e)]
                trials_hit = sum(
                    1 for t in range(num_trials)
                    if e in trial_edges[(fuzzer, t)]
                )
                c = trials_hit / num_trials
                score += (r ** alpha) * (c ** beta)
                if len(edge_covering[e]) == 1:
                    unique += 1

            results[benchmark][fuzzer] = {
                "novelty_score": round(score, 4),
                "total_edges": len(fuzzer_edges[fuzzer]),
                "unique_edges": unique,
            }

        # Assign ranks within this benchmark (ascending sort = lowest score gets rank 1)
        scored = [
            (f, results[benchmark][f]["novelty_score"])
            for f in meta["fuzzers"]
        ]
        scored.sort(key=lambda x: x[1])

        pos = 0
        while pos < len(scored):
            end = pos
            while end < len(scored) and scored[end][1] == scored[pos][1]:
                end += 1
            avg_rank = sum(range(pos + 1, end + 1)) / (end - pos)
            for k in range(pos, end):
                results[benchmark][scored[k][0]]["rank"] = round(avg_rank, 1)
            pos = end

    return results, rarity_cache


def compute_aggregate_ranking(scores, meta):
    """Compute cross-benchmark aggregate ranking from per-benchmark scores."""
    ranks = defaultdict(list)
    totals = defaultdict(float)
    per_bench = defaultdict(dict)

    for b in meta["benchmarks"]:
        for f in meta["fuzzers"]:
            ranks[f].append(scores[b][f]["rank"])
            totals[f] += scores[b][f]["novelty_score"]
            per_bench[f][b] = scores[b][f]["rank"]

    ranking = []
    for f in meta["fuzzers"]:
        ranking.append({
            "fuzzer": f,
            "mean_rank": round(sum(ranks[f]) / len(ranks[f]), 2),
            "total_novelty": round(totals[f], 4),
            "per_benchmark_ranks": dict(per_bench[f]),
        })

    ranking.sort(key=lambda x: (x["mean_rank"], -x["total_novelty"]))
    return ranking


def _normal_cdf(x):
    """Abramowitz & Stegun approximation of the standard normal CDF."""
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(
        -x * x / 2
    )
    return 0.5 * (1.0 + sign * y)


def _mann_whitney(x, y):
    """Two-sided Mann-Whitney U test with normal approximation and tie correction."""
    nx, ny = len(x), len(y)
    combined = [(v, "x") for v in x] + [(v, "y") for v in y]
    combined.sort(key=lambda t: t[0])

    ranks = [0.0] * len(combined)
    i = 0
    tie_groups = []
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[k] = avg
        if j - i > 1:
            tie_groups.append(j - i)
        i = j

    rx = sum(ranks[i] for i in range(len(combined)) if combined[i][1] == "x")
    u1 = rx - nx * (nx + 1) / 2
    u2 = nx * ny - u1
    U = min(u1, u2)

    mu = nx * ny / 2
    n = nx + ny
    tie_adj = sum(t ** 3 - t for t in tie_groups) / (n * (n - 1)) if n > 1 else 0
    var_term = (n + 1) - tie_adj
    sigma = math.sqrt(nx * ny / 12 * var_term) if var_term > 0 else 0

    if sigma == 0:
        return U, 1.0
    z = (U - mu) / sigma
    return U, 2 * (1 - _normal_cdf(abs(z)))


def compute_stats(data, rarity_cache, meta, config):
    """Compute pairwise Mann-Whitney U tests with BH FDR correction."""
    alpha = config["tversky_alpha"]
    final_ts = max(meta["snapshots_seconds"])
    T = meta["trials"]

    # Per-trial novelty scores using rarity only
    trial_scores = {}
    for b in meta["benchmarks"]:
        for f in meta["fuzzers"]:
            for t in range(T):
                edges = data.get((f, b, t, final_ts), set())
                trial_scores[(f, b, t)] = sum(
                    rarity_cache.get((b, e), 0.0) ** alpha for e in edges
                )

    # Pairwise tests across all benchmarks
    tests = []
    sf = sorted(meta["fuzzers"])
    for b in meta["benchmarks"]:
        for fi, fj in combinations(sf, 2):
            x = [trial_scores[(fi, b, t)] for t in range(T)]
            y = [trial_scores[(fj, b, t)] for t in range(T)]
            U, p = _mann_whitney(x, y)
            tests.append((b, fi, fj, U, p))

    # Benjamini-Hochberg correction
    m = len(tests)
    order = sorted(range(m), key=lambda i: tests[i][4])
    adj_p = [0.0] * m
    for rank_i, test_i in enumerate(order):
        adj_p[test_i] = tests[test_i][4] * m / (rank_i + 1)
    for ri in range(len(order) - 2, -1, -1):
        adj_p[order[ri]] = min(adj_p[order[ri]], adj_p[order[ri + 1]])
    adj_p = [min(p, 1.0) for p in adj_p]

    results = {}
    for i, (b, fi, fj, U, p) in enumerate(tests):
        results.setdefault(b, {})
        results[b][f"{fi}_vs_{fj}"] = {
            "u_statistic": U,
            "p_value": round(p, 6),
            "p_value_corrected": round(adj_p[i], 6),
            "significant": adj_p[i] < 0.05,
        }
    return results


def compute_velocity(data, meta):
    """Compute coverage velocity between time snapshots."""
    T = meta["trials"]
    snaps = sorted(meta["snapshots_seconds"])

    results = {}
    for b in meta["benchmarks"]:
        results[b] = {}
        for f in meta["fuzzers"]:
            snap_data = []
            for ts in snaps:
                counts = [len(data.get((f, b, t, ts), set())) for t in range(T)]
                mean_e = sum(counts) / len(counts)
                snap_data.append({"time": ts, "mean_edges": round(mean_e, 2)})

            vels = []
            for i in range(len(snaps) - 1):
                t1, t2 = snaps[i], snaps[i + 1]
                e1, e2 = snap_data[i]["mean_edges"], snap_data[i + 1]["mean_edges"]
                v = (e2 - e1) / t2
                vels.append({
                    "interval": [t1, t2],
                    "edges_per_second": round(v, 4),
                })

            results[b][f] = {"snapshots": snap_data, "velocities": vels}
    return results


def main():
    config = load_config()
    meta = load_meta()

    print("Loading FCOV data...")
    data = load_fcov_data(meta)

    print("Loading database data...")
    db_data = load_db_data(meta)
    data.update(db_data)

    print("Computing novelty scores...")
    scores, rarity_cache = compute_novelty_scores(data, meta, config)

    print("Computing aggregate ranking...")
    ranking = compute_aggregate_ranking(scores, meta)

    print("Computing statistical tests...")
    stats = compute_stats(data, rarity_cache, meta, config)

    print("Computing coverage velocity...")
    velocity = compute_velocity(data, meta)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, obj in [
        ("novelty_scores.json", scores),
        ("aggregate_ranking.json", ranking),
        ("statistical_tests.json", stats),
        ("coverage_velocity.json", velocity),
    ]:
        with open(os.path.join(OUTPUT_DIR, name), "w") as f:
            json.dump(obj, f, indent=2)
        print(f"  Wrote {name}")

    print("Analysis complete.")


if __name__ == "__main__":
    main()
