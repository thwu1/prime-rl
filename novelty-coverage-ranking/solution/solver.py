#!/usr/bin/env python3

"""Complete novelty coverage evaluation framework.

Reads heterogeneous coverage data (FCOV binary + SQLite incremental),
extracts Tversky-index parameters from the database, and computes
novelty scores, aggregate rankings, pairwise statistical tests, and
coverage velocity for a multi-fuzzer benchmarking experiment.
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


def load_meta():
    with open(os.path.join(DATA_DIR, "meta.json")) as f:
        return json.load(f)


def load_config_from_db(db_path):
    """Read Tversky parameters directly from SQLite config table."""
    db = sqlite3.connect(db_path)
    alpha = float(db.execute("SELECT value FROM config WHERE key='tversky_alpha'").fetchone()[0])
    beta = float(db.execute("SELECT value FROM config WHERE key='tversky_beta'").fetchone()[0])
    db.close()
    return {"tversky_alpha": alpha, "tversky_beta": beta}


def parse_cov_file(path):
    """Parse a binary FCOV coverage file (cumulative format)."""
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"FCOV":
            raise ValueError(f"Invalid magic: {magic!r}")
        version, edge_space, num_snapshots = struct.unpack("<III", f.read(12))
        if version != 1:
            raise ValueError(f"Unsupported version: {version}")
        snapshots = {}
        for _ in range(num_snapshots):
            timestamp, num_edges = struct.unpack("<II", f.read(8))
            edges = set(struct.unpack(f"<{num_edges}I", f.read(4 * num_edges))) if num_edges else set()
            snapshots[timestamp] = edges
        return snapshots


def load_fcov_data(meta):
    """Load coverage data from FCOV binary files."""
    data = {}
    for fuzzer in meta["fuzzers"]:
        for benchmark in meta.get("fcov_benchmarks", []):
            for trial in range(meta["trials"]):
                path = os.path.join(
                    DATA_DIR, fuzzer, benchmark,
                    f"trial_{trial:02d}", "coverage.cov"
                )
                for ts, edges in parse_cov_file(path).items():
                    data[(fuzzer, benchmark, trial, ts)] = edges
    return data


def load_db_data(meta):
    """Load coverage data from SQLite using cumulative semantics.

    The database stores edges per measurement interval (incremental), so
    to get cumulative coverage at time T, we query snapshot_time <= T.
    """
    data = {}
    db_path = meta.get("db_path", os.path.join(DATA_DIR, "experiment.db"))
    db = sqlite3.connect(db_path)

    for fuzzer in meta["fuzzers"]:
        for benchmark in meta.get("db_benchmarks", []):
            for trial in range(meta["trials"]):
                for ts in meta["snapshots_seconds"]:
                    cursor = db.execute(
                        "SELECT DISTINCT edge_id FROM coverage "
                        "WHERE benchmark = ? AND fuzzer = ? AND trial = ? "
                        "AND snapshot_time <= ?",
                        (benchmark, fuzzer, trial, ts)
                    )
                    edges = set(row[0] for row in cursor.fetchall())
                    data[(fuzzer, benchmark, trial, ts)] = edges

    db.close()
    return data


def compute_novelty_scores(data, meta, config):
    """Compute per-benchmark novelty coverage scores with correct rarity formula."""
    alpha = config["tversky_alpha"]
    beta = config["tversky_beta"]
    final_ts = max(meta["snapshots_seconds"])
    F = len(meta["fuzzers"])
    T = meta["trials"]

    results = {}
    rarity_map = {}

    for benchmark in meta["benchmarks"]:
        results[benchmark] = {}

        fuzzer_trial_edges = {}
        fuzzer_all_edges = {}
        for fuzzer in meta["fuzzers"]:
            all_edges = set()
            for trial in range(T):
                edges = data.get((fuzzer, benchmark, trial, final_ts), set())
                fuzzer_trial_edges[(fuzzer, trial)] = edges
                all_edges |= edges
            fuzzer_all_edges[fuzzer] = all_edges

        all_edges_union = set()
        for f in meta["fuzzers"]:
            all_edges_union |= fuzzer_all_edges[f]

        edge_fuzzers = {}
        for e in all_edges_union:
            covering = frozenset(f for f in meta["fuzzers"] if e in fuzzer_all_edges[f])
            edge_fuzzers[e] = covering
            rarity_map[(benchmark, e)] = (F - len(covering)) / (F - 1) if F > 1 else 0.0

        for fuzzer in meta["fuzzers"]:
            novelty_score = 0.0
            unique_edges = 0
            for e in fuzzer_all_edges[fuzzer]:
                rarity = rarity_map[(benchmark, e)]
                trials_with_e = sum(1 for t in range(T) if e in fuzzer_trial_edges[(fuzzer, t)])
                consistency = trials_with_e / T
                novelty_score += (rarity ** alpha) * (consistency ** beta)
                if len(edge_fuzzers[e]) == 1:
                    unique_edges += 1

            results[benchmark][fuzzer] = {
                "novelty_score": round(novelty_score, 4),
                "total_edges": len(fuzzer_all_edges[fuzzer]),
                "unique_edges": unique_edges,
            }

        # Sort DESCENDING by novelty score (highest = rank 1)
        scores_list = [(f, results[benchmark][f]["novelty_score"]) for f in meta["fuzzers"]]
        scores_list.sort(key=lambda x: -x[1])

        i = 0
        while i < len(scores_list):
            j = i
            while j < len(scores_list) and scores_list[j][1] == scores_list[i][1]:
                j += 1
            avg_rank = sum(range(i + 1, j + 1)) / (j - i)
            for k in range(i, j):
                results[benchmark][scores_list[k][0]]["rank"] = round(avg_rank, 1)
            i = j

    return results, rarity_map


def compute_aggregate_ranking(novelty_scores, meta):
    """Compute cross-benchmark aggregate ranking with per_benchmark_ranks."""
    fuzzer_ranks = defaultdict(list)
    fuzzer_total = defaultdict(float)
    fuzzer_per_bench = defaultdict(dict)

    for benchmark in meta["benchmarks"]:
        for fuzzer in meta["fuzzers"]:
            rank = novelty_scores[benchmark][fuzzer]["rank"]
            fuzzer_ranks[fuzzer].append(rank)
            fuzzer_total[fuzzer] += novelty_scores[benchmark][fuzzer]["novelty_score"]
            fuzzer_per_bench[fuzzer][benchmark] = rank

    ranking = []
    for fuzzer in meta["fuzzers"]:
        mean_rank = sum(fuzzer_ranks[fuzzer]) / len(fuzzer_ranks[fuzzer])
        ranking.append({
            "fuzzer": fuzzer,
            "mean_rank": round(mean_rank, 2),
            "total_novelty": round(fuzzer_total[fuzzer], 4),
            "per_benchmark_ranks": dict(fuzzer_per_bench[fuzzer]),
        })

    ranking.sort(key=lambda x: (x["mean_rank"], -x["total_novelty"]))
    return ranking


def _normal_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2)
    return 0.5 * (1.0 + sign * y)


def _mann_whitney_u(x, y):
    nx, ny = len(x), len(y)
    combined = [(v, "x") for v in x] + [(v, "y") for v in y]
    combined.sort(key=lambda t: t[0])

    ranks = [0.0] * len(combined)
    i = 0
    tie_counts = []
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[k] = avg_rank
        if j - i > 1:
            tie_counts.append(j - i)
        i = j

    rank_sum_x = sum(ranks[i] for i in range(len(combined)) if combined[i][1] == "x")
    u_x = rank_sum_x - nx * (nx + 1) / 2
    u_y = nx * ny - u_x
    U = min(u_x, u_y)

    mu = nx * ny / 2
    n = nx + ny
    tie_corr = sum(t ** 3 - t for t in tie_counts) / (n * (n - 1)) if n > 1 else 0
    var_term = (n + 1) - tie_corr
    sigma = math.sqrt(nx * ny / 12 * var_term) if var_term > 0 else 0

    if sigma == 0:
        return U, 1.0
    z = (U - mu) / sigma
    return U, 2 * (1 - _normal_cdf(abs(z)))


def compute_statistical_tests(data, rarity_map, meta, config):
    alpha_tv = config["tversky_alpha"]
    final_ts = max(meta["snapshots_seconds"])
    T = meta["trials"]

    trial_scores = {}
    for benchmark in meta["benchmarks"]:
        for fuzzer in meta["fuzzers"]:
            for trial in range(T):
                edges = data.get((fuzzer, benchmark, trial, final_ts), set())
                score = sum(rarity_map.get((benchmark, e), 0.0) ** alpha_tv for e in edges)
                trial_scores[(fuzzer, benchmark, trial)] = score

    all_tests = []
    sorted_fuzzers = sorted(meta["fuzzers"])
    for benchmark in meta["benchmarks"]:
        for fi, fj in combinations(sorted_fuzzers, 2):
            x = [trial_scores[(fi, benchmark, t)] for t in range(T)]
            y = [trial_scores[(fj, benchmark, t)] for t in range(T)]
            U, p = _mann_whitney_u(x, y)
            all_tests.append((benchmark, fi, fj, U, p))

    m = len(all_tests)
    sorted_by_p = sorted(range(m), key=lambda i: all_tests[i][4])
    corrected_p = [0.0] * m
    for rank_idx, test_idx in enumerate(sorted_by_p):
        corrected_p[test_idx] = all_tests[test_idx][4] * m / (rank_idx + 1)
    for rank_idx in range(len(sorted_by_p) - 2, -1, -1):
        idx = sorted_by_p[rank_idx]
        next_idx = sorted_by_p[rank_idx + 1]
        corrected_p[idx] = min(corrected_p[idx], corrected_p[next_idx])
    corrected_p = [min(p, 1.0) for p in corrected_p]

    results = {}
    for i, (benchmark, fi, fj, U, p) in enumerate(all_tests):
        if benchmark not in results:
            results[benchmark] = {}
        results[benchmark][f"{fi}_vs_{fj}"] = {
            "u_statistic": U,
            "p_value": round(p, 6),
            "p_value_corrected": round(corrected_p[i], 6),
            "significant": corrected_p[i] < 0.05,
        }
    return results


def compute_coverage_velocity(data, meta):
    """Compute coverage velocity with correct interval divisor."""
    T = meta["trials"]
    snapshots = sorted(meta["snapshots_seconds"])

    results = {}
    for benchmark in meta["benchmarks"]:
        results[benchmark] = {}
        for fuzzer in meta["fuzzers"]:
            snapshot_means = []
            for ts in snapshots:
                counts = [len(data.get((fuzzer, benchmark, t, ts), set())) for t in range(T)]
                mean_edges = sum(counts) / len(counts)
                snapshot_means.append({"time": ts, "mean_edges": round(mean_edges, 2)})

            velocities = []
            for i in range(len(snapshots) - 1):
                t1, t2 = snapshots[i], snapshots[i + 1]
                e1 = snapshot_means[i]["mean_edges"]
                e2 = snapshot_means[i + 1]["mean_edges"]
                vel = (e2 - e1) / (t2 - t1)
                velocities.append({
                    "interval": [t1, t2],
                    "edges_per_second": round(vel, 4),
                })

            results[benchmark][fuzzer] = {
                "snapshots": snapshot_means,
                "velocities": velocities,
            }
    return results


def main():
    meta = load_meta()
    config = load_config_from_db(meta.get("db_path", os.path.join(DATA_DIR, "experiment.db")))

    print("Loading FCOV data...")
    data = load_fcov_data(meta)

    print("Loading database data...")
    db_data = load_db_data(meta)
    data.update(db_data)

    print("Computing novelty scores...")
    novelty_scores, rarity_map = compute_novelty_scores(data, meta, config)

    print("Computing aggregate ranking...")
    ranking = compute_aggregate_ranking(novelty_scores, meta)

    print("Computing statistical tests...")
    stats = compute_statistical_tests(data, rarity_map, meta, config)

    print("Computing coverage velocity...")
    velocity = compute_coverage_velocity(data, meta)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for name, obj in [
        ("novelty_scores.json", novelty_scores),
        ("aggregate_ranking.json", ranking),
        ("statistical_tests.json", stats),
        ("coverage_velocity.json", velocity),
    ]:
        with open(os.path.join(OUTPUT_DIR, name), "w") as f:
            json.dump(obj, f, indent=2)
        print(f"  Wrote {name}")

    print("Done.")


if __name__ == "__main__":
    main()
