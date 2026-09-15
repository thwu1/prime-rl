
"""Tests for the novelty coverage fuzzer evaluation framework."""

import json
import struct
import os
import math
import pytest
from collections import defaultdict
from itertools import combinations


DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"

EXPECTED_NOVELTY = {
    "bloaty_fuzz_target": {
        "aflpp": {"novelty_score": 2257.7121, "total_edges": 3566, "unique_edges": 964, "rank": 1.0},
        "centipede": {"novelty_score": 1599.6651, "total_edges": 2907, "unique_edges": 735, "rank": 4.0},
        "libafl": {"novelty_score": 1705.3483, "total_edges": 2997, "unique_edges": 764, "rank": 3.0},
        "libfuzzer": {"novelty_score": 2153.8112, "total_edges": 3464, "unique_edges": 922, "rank": 2.0},
    },
    "freetype2_ftfuzzer": {
        "aflpp": {"novelty_score": 2147.5802, "total_edges": 3461, "unique_edges": 919, "rank": 2.0},
        "centipede": {"novelty_score": 1621.1779, "total_edges": 2899, "unique_edges": 708, "rank": 4.0},
        "libafl": {"novelty_score": 2232.6432, "total_edges": 3564, "unique_edges": 976, "rank": 1.0},
        "libfuzzer": {"novelty_score": 1667.0916, "total_edges": 2948, "unique_edges": 745, "rank": 3.0},
    },
    "harfbuzz_shaping": {
        "aflpp": {"novelty_score": 1610.9693, "total_edges": 2911, "unique_edges": 676, "rank": 4.0},
        "centipede": {"novelty_score": 2258.0819, "total_edges": 3563, "unique_edges": 959, "rank": 1.0},
        "libafl": {"novelty_score": 1726.8501, "total_edges": 2996, "unique_edges": 751, "rank": 3.0},
        "libfuzzer": {"novelty_score": 2140.9552, "total_edges": 3450, "unique_edges": 907, "rank": 2.0},
    },
    "libpng_read_fuzzer": {
        "aflpp": {"novelty_score": 1667.3282, "total_edges": 3029, "unique_edges": 730, "rank": 3.0},
        "centipede": {"novelty_score": 2124.2227, "total_edges": 3443, "unique_edges": 904, "rank": 2.0},
        "libafl": {"novelty_score": 2243.47, "total_edges": 3563, "unique_edges": 963, "rank": 1.0},
        "libfuzzer": {"novelty_score": 1612.1029, "total_edges": 2911, "unique_edges": 731, "rank": 4.0},
    },
}

EXPECTED_RANKING_ORDER = ["libafl", "aflpp", "centipede", "libfuzzer"]
EXPECTED_MEAN_RANKS = {"libafl": 2.0, "aflpp": 2.5, "centipede": 2.75, "libfuzzer": 2.75}
EXPECTED_TOTAL_NOVELTY = {"libafl": 7908.3116, "aflpp": 7683.5898, "centipede": 7603.1476, "libfuzzer": 7573.9609}

EXPECTED_VELOCITY = {
    ("bloaty_fuzz_target", "aflpp"): {"snapshots": [2086.8, 3382.8], "vel": 0.12},
    ("harfbuzz_shaping", "centipede"): {"snapshots": [2027.2, 3376.6], "vel": 0.1249},
    ("freetype2_ftfuzzer", "libafl"): {"snapshots": [1977.2, 3345.2], "vel": 0.1267},
    ("libpng_read_fuzzer", "libfuzzer"): {"snapshots": [1306.2, 2543.6], "vel": 0.1146},
}


def _load_json(name):
    path = os.path.join(OUTPUT_DIR, name)
    assert os.path.isfile(path), f"Missing output file: {name}"
    with open(path) as f:
        return json.load(f)


def _load_meta():
    with open(os.path.join(DATA_DIR, "meta.json")) as f:
        return json.load(f)


# ---- structural tests ----

class TestOutputFilesExist:
    def test_novelty_scores_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "novelty_scores.json"))

    def test_aggregate_ranking_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "aggregate_ranking.json"))

    def test_statistical_tests_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "statistical_tests.json"))

    def test_coverage_velocity_exists(self):
        assert os.path.isfile(os.path.join(OUTPUT_DIR, "coverage_velocity.json"))


class TestNoveltyScoresStructure:
    def test_has_all_benchmarks(self):
        data = _load_json("novelty_scores.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            assert b in data, f"Missing benchmark {b}"

    def test_has_all_fuzzers_per_benchmark(self):
        data = _load_json("novelty_scores.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            for f in meta["fuzzers"]:
                assert f in data[b], f"Missing fuzzer {f} in {b}"

    def test_required_fields(self):
        data = _load_json("novelty_scores.json")
        meta = _load_meta()
        required = {"novelty_score", "total_edges", "unique_edges", "rank"}
        for b in meta["benchmarks"]:
            for f in meta["fuzzers"]:
                assert required <= set(data[b][f].keys()), \
                    f"Missing fields for {f}/{b}: {required - set(data[b][f].keys())}"


class TestNoveltyScoresValues:
    @pytest.mark.parametrize("benchmark", list(EXPECTED_NOVELTY.keys()))
    def test_novelty_scores_match(self, benchmark):
        data = _load_json("novelty_scores.json")
        for fuzzer, expected in EXPECTED_NOVELTY[benchmark].items():
            actual = data[benchmark][fuzzer]
            assert abs(actual["novelty_score"] - expected["novelty_score"]) < 0.1, \
                f"{benchmark}/{fuzzer}: novelty_score {actual['novelty_score']} != {expected['novelty_score']}"
            assert actual["total_edges"] == expected["total_edges"], \
                f"{benchmark}/{fuzzer}: total_edges {actual['total_edges']} != {expected['total_edges']}"
            assert actual["unique_edges"] == expected["unique_edges"], \
                f"{benchmark}/{fuzzer}: unique_edges {actual['unique_edges']} != {expected['unique_edges']}"
            assert abs(actual["rank"] - expected["rank"]) < 0.01, \
                f"{benchmark}/{fuzzer}: rank {actual['rank']} != {expected['rank']}"

    def test_scores_positive(self):
        data = _load_json("novelty_scores.json")
        for b in data:
            for f in data[b]:
                assert data[b][f]["novelty_score"] >= 0

    def test_ranks_valid(self):
        """Ranks per benchmark must average to (|F|+1)/2."""
        data = _load_json("novelty_scores.json")
        meta = _load_meta()
        nf = len(meta["fuzzers"])
        for b in meta["benchmarks"]:
            ranks = [data[b][f]["rank"] for f in meta["fuzzers"]]
            assert abs(sum(ranks) - nf * (nf + 1) / 2) < 0.01, \
                f"Ranks for {b} don't sum to {nf * (nf + 1) / 2}: {ranks}"

    def test_unique_edges_le_total(self):
        data = _load_json("novelty_scores.json")
        for b in data:
            for f in data[b]:
                assert data[b][f]["unique_edges"] <= data[b][f]["total_edges"]


class TestAggregateRanking:
    def test_ranking_order(self):
        data = _load_json("aggregate_ranking.json")
        order = [entry["fuzzer"] for entry in data]
        assert order == EXPECTED_RANKING_ORDER, f"Order {order} != {EXPECTED_RANKING_ORDER}"

    def test_mean_ranks(self):
        data = _load_json("aggregate_ranking.json")
        for entry in data:
            expected = EXPECTED_MEAN_RANKS[entry["fuzzer"]]
            assert abs(entry["mean_rank"] - expected) < 0.01, \
                f"{entry['fuzzer']}: mean_rank {entry['mean_rank']} != {expected}"

    def test_total_novelty(self):
        data = _load_json("aggregate_ranking.json")
        for entry in data:
            expected = EXPECTED_TOTAL_NOVELTY[entry["fuzzer"]]
            assert abs(entry["total_novelty"] - expected) < 0.5, \
                f"{entry['fuzzer']}: total_novelty {entry['total_novelty']} != {expected}"

    def test_has_per_benchmark_ranks(self):
        data = _load_json("aggregate_ranking.json")
        meta = _load_meta()
        for entry in data:
            assert "per_benchmark_ranks" in entry
            for b in meta["benchmarks"]:
                assert b in entry["per_benchmark_ranks"]

    def test_sorted_by_mean_rank(self):
        data = _load_json("aggregate_ranking.json")
        for i in range(len(data) - 1):
            r1 = data[i]["mean_rank"]
            r2 = data[i + 1]["mean_rank"]
            assert r1 <= r2, "Not sorted by ascending mean_rank"
            if abs(r1 - r2) < 0.001:
                assert data[i]["total_novelty"] >= data[i + 1]["total_novelty"], \
                    "Tied mean_rank not broken by descending total_novelty"


class TestStatisticalTests:
    def test_has_all_benchmarks(self):
        data = _load_json("statistical_tests.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            assert b in data

    def test_has_all_pairs(self):
        data = _load_json("statistical_tests.json")
        meta = _load_meta()
        sf = sorted(meta["fuzzers"])
        for b in meta["benchmarks"]:
            for fi, fj in combinations(sf, 2):
                key = f"{fi}_vs_{fj}"
                assert key in data[b], f"Missing {key} in {b}"

    def test_required_fields(self):
        data = _load_json("statistical_tests.json")
        meta = _load_meta()
        required = {"u_statistic", "p_value", "p_value_corrected", "significant"}
        for b in meta["benchmarks"]:
            for key, val in data[b].items():
                assert required <= set(val.keys()), \
                    f"Missing fields for {b}/{key}: {required - set(val.keys())}"

    def test_p_values_valid(self):
        data = _load_json("statistical_tests.json")
        for b in data:
            for key, val in data[b].items():
                assert 0 <= val["p_value"] <= 1.0, f"p_value out of range: {val['p_value']}"
                assert 0 <= val["p_value_corrected"] <= 1.0, \
                    f"p_value_corrected out of range: {val['p_value_corrected']}"
                assert val["p_value_corrected"] >= val["p_value"] - 1e-6, \
                    "Corrected p should be >= raw p (BH correction)"

    def test_significance_consistent(self):
        data = _load_json("statistical_tests.json")
        for b in data:
            for key, val in data[b].items():
                if val["p_value_corrected"] < 0.05:
                    assert val["significant"] is True
                else:
                    assert val["significant"] is False

    def test_u_statistic_nonnegative(self):
        data = _load_json("statistical_tests.json")
        for b in data:
            for key, val in data[b].items():
                assert val["u_statistic"] >= 0

    def test_all_significant_for_this_dataset(self):
        """With 5 trials and large effect sizes, all pairs should be significant."""
        data = _load_json("statistical_tests.json")
        for b in data:
            for key, val in data[b].items():
                assert val["significant"] is True, \
                    f"{b}/{key} should be significant but p_corr={val['p_value_corrected']}"


class TestCoverageVelocity:
    def test_has_all_benchmarks(self):
        data = _load_json("coverage_velocity.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            assert b in data

    def test_has_all_fuzzers(self):
        data = _load_json("coverage_velocity.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            for f in meta["fuzzers"]:
                assert f in data[b]

    def test_snapshot_count(self):
        data = _load_json("coverage_velocity.json")
        meta = _load_meta()
        n_snap = len(meta["snapshots_seconds"])
        for b in meta["benchmarks"]:
            for f in meta["fuzzers"]:
                assert len(data[b][f]["snapshots"]) == n_snap
                assert len(data[b][f]["velocities"]) == n_snap - 1

    def test_snapshots_ascending(self):
        data = _load_json("coverage_velocity.json")
        for b in data:
            for f in data[b]:
                times = [s["time"] for s in data[b][f]["snapshots"]]
                assert times == sorted(times)

    def test_mean_edges_nonnegative(self):
        data = _load_json("coverage_velocity.json")
        for b in data:
            for f in data[b]:
                for s in data[b][f]["snapshots"]:
                    assert s["mean_edges"] >= 0

    @pytest.mark.parametrize("key", list(EXPECTED_VELOCITY.keys()))
    def test_velocity_values(self, key):
        benchmark, fuzzer = key
        data = _load_json("coverage_velocity.json")
        actual = data[benchmark][fuzzer]
        expected = EXPECTED_VELOCITY[key]

        for i, exp_mean in enumerate(expected["snapshots"]):
            assert abs(actual["snapshots"][i]["mean_edges"] - exp_mean) < 0.5, \
                f"{benchmark}/{fuzzer} snap {i}: {actual['snapshots'][i]['mean_edges']} != {exp_mean}"

        assert abs(actual["velocities"][0]["edges_per_second"] - expected["vel"]) < 0.001, \
            f"{benchmark}/{fuzzer} velocity: {actual['velocities'][0]['edges_per_second']} != {expected['vel']}"


class TestCrossConsistency:
    """Verify consistency across output files."""

    def test_ranking_matches_scores(self):
        """Aggregate ranking must use correct per-benchmark ranks from novelty_scores."""
        scores = _load_json("novelty_scores.json")
        ranking = _load_json("aggregate_ranking.json")
        for entry in ranking:
            f = entry["fuzzer"]
            for b, r in entry["per_benchmark_ranks"].items():
                assert abs(r - scores[b][f]["rank"]) < 0.01, \
                    f"Rank mismatch for {f}/{b}: ranking says {r}, scores say {scores[b][f]['rank']}"

    def test_total_novelty_matches_scores(self):
        scores = _load_json("novelty_scores.json")
        ranking = _load_json("aggregate_ranking.json")
        meta = _load_meta()
        for entry in ranking:
            f = entry["fuzzer"]
            total = sum(scores[b][f]["novelty_score"] for b in meta["benchmarks"])
            assert abs(entry["total_novelty"] - total) < 0.5, \
                f"total_novelty mismatch for {f}: {entry['total_novelty']} vs {total}"

    def test_coverage_velocity_edges_plausible(self):
        """Mean edges at final snapshot should roughly match total_edges / trials."""
        vel = _load_json("coverage_velocity.json")
        scores = _load_json("novelty_scores.json")
        meta = _load_meta()
        for b in meta["benchmarks"]:
            for f in meta["fuzzers"]:
                final_mean = vel[b][f]["snapshots"][-1]["mean_edges"]
                total = scores[b][f]["total_edges"]
                assert final_mean <= total, \
                    f"Mean edges ({final_mean}) > total edges ({total}) for {f}/{b}"
