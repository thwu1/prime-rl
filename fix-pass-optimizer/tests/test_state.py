
"""Tests for the LLVM pass sequence optimization framework.

Verifies instruction counting, synergy graph construction, GA operators,
improvement metric, cross-benchmark evaluator, and the end-to-end pipeline.
"""

import sys
sys.path.insert(0, '/app')

import math
import os
import random
import pytest

from src.instrcount import count_instructions, parse_instruction_count
from src.synergy_graph import build_synergy_graph, get_successors
from src.ga import Individual, select, crossover, mutate, initialize_population
from src.optimizer import compute_improvement, run_pipeline
from src.passes import AVAILABLE_PASSES, SYNERGY_PAIRS
from src.evaluator import (
    evaluate_sequence,
    aggregate_improvements,
    rank_sequences,
    compare_strategies,
)


BENCHMARK_DIR = "/app/benchmarks"
BENCHMARK_IR = os.path.join(BENCHMARK_DIR, "matmul.ll")


@pytest.fixture
def benchmark_files():
    """Collect all .ll benchmark files, asserting at least 3 exist."""
    files = sorted([
        os.path.join(BENCHMARK_DIR, f)
        for f in os.listdir(BENCHMARK_DIR)
        if f.endswith(".ll")
    ])
    assert len(files) >= 3, f"Expected >= 3 benchmark .ll files, found {len(files)}"
    return files


# ---------------------------------------------------------------------------
# Instruction counting
# ---------------------------------------------------------------------------

class TestInstrCount:
    def test_count_positive(self):
        """Unoptimized IR should have a positive instruction count."""
        count = count_instructions(BENCHMARK_IR, [])
        assert count > 0, f"Instruction count should be positive, got {count}"

    def test_count_reflects_optimization(self):
        """Optimization must change the instruction count."""
        unopt = count_instructions(BENCHMARK_IR, [])
        opt = count_instructions(
            BENCHMARK_IR, ["mem2reg", "instcombine", "simplifycfg"]
        )
        assert opt < unopt, (
            f"Optimized count ({opt}) should be less than unoptimized ({unopt}). "
            "Verify that count_instructions reads the optimized output, not the input."
        )

    def test_different_passes_different_counts(self):
        """More passes should reduce instructions further."""
        c1 = count_instructions(BENCHMARK_IR, ["mem2reg"])
        c2 = count_instructions(
            BENCHMARK_IR, ["mem2reg", "instcombine", "simplifycfg", "gvn"]
        )
        baseline = count_instructions(BENCHMARK_IR, [])
        assert c1 < baseline, (
            f"mem2reg should reduce count ({c1}) vs baseline ({baseline})"
        )
        assert c2 <= c1, (
            f"Additional passes should not increase count: {c2} > {c1}"
        )


# ---------------------------------------------------------------------------
# Synergy graph
# ---------------------------------------------------------------------------

class TestSynergyGraph:
    def test_edge_direction_simple(self):
        """Edges must go from the first pass to the second."""
        pairs = {("alpha", "beta"): 50, ("beta", "gamma"): 60}
        graph = build_synergy_graph(pairs)
        assert "beta" in graph.get("alpha", set()), (
            "Edge alpha->beta missing"
        )
        assert "gamma" in graph.get("beta", set()), (
            "Edge beta->gamma missing"
        )
        assert "alpha" not in graph.get("beta", set()), (
            "Reversed edge beta->alpha should not exist"
        )
        assert "beta" not in graph.get("gamma", set()), (
            "Reversed edge gamma->beta should not exist"
        )

    def test_real_synergy_data(self):
        """Check a known pair from the real synergy data."""
        graph = build_synergy_graph(SYNERGY_PAIRS)
        assert "instcombine" in graph.get("sroa", set()), (
            "Expected edge sroa->instcombine in synergy graph"
        )
        assert "sroa" not in graph.get("instcombine", set()), (
            "Unexpected reversed edge instcombine->sroa"
        )

    def test_threshold_filtering(self):
        """Pairs below threshold should be excluded."""
        pairs = {("a", "b"): 10, ("c", "d"): 50}
        graph = build_synergy_graph(pairs, threshold=30)
        assert "b" not in graph.get("a", set()), (
            "Edge a->b should be filtered by threshold"
        )
        assert "d" in graph.get("c", set()), (
            "Edge c->d should pass threshold"
        )


# ---------------------------------------------------------------------------
# Genetic algorithm operators
# ---------------------------------------------------------------------------

class TestGA:
    def test_selection_picks_fittest(self):
        """Selection must return the individuals with highest fitness."""
        pop = [
            Individual(sequence=["a"], fitness=10),
            Individual(sequence=["b"], fitness=50),
            Individual(sequence=["c"], fitness=30),
            Individual(sequence=["d"], fitness=5),
            Individual(sequence=["e"], fitness=45),
        ]
        selected = select(pop, 3)
        fitnesses = sorted([ind.fitness for ind in selected], reverse=True)
        assert fitnesses == [50, 45, 30], (
            f"Expected top-3 fitnesses [50, 45, 30], got {fitnesses}"
        )

    def test_selection_order(self):
        """First selected individual should have the highest fitness."""
        pop = [
            Individual(sequence=["x"], fitness=100),
            Individual(sequence=["y"], fitness=1),
            Individual(sequence=["z"], fitness=50),
        ]
        selected = select(pop, 2)
        assert selected[0].fitness >= selected[1].fitness, (
            "Selection should return individuals sorted best-first"
        )

    def test_crossover_no_duplication(self):
        """Crossover must not duplicate the crossover-point pass."""
        p1 = ["mem2reg", "instcombine", "simplifycfg"]
        p2 = ["gvn", "instcombine", "dse"]
        c1, c2 = crossover(p1, p2)
        assert c1.count("instcombine") == 1, (
            f"instcombine duplicated in child1: {c1}"
        )
        assert c2.count("instcombine") == 1, (
            f"instcombine duplicated in child2: {c2}"
        )

    def test_crossover_combined_length(self):
        """Crossover should conserve total element count across children."""
        p1 = ["mem2reg", "instcombine", "simplifycfg"]
        p2 = ["gvn", "instcombine", "dse"]
        c1, c2 = crossover(p1, p2)
        assert len(c1) + len(c2) == len(p1) + len(p2), (
            f"Combined length {len(c1)}+{len(c2)} != {len(p1)}+{len(p2)}"
        )

    def test_crossover_no_common_passes(self):
        """With no common passes, crossover should return copies of parents."""
        p1 = ["mem2reg", "sroa"]
        p2 = ["gvn", "dse"]
        c1, c2 = crossover(p1, p2)
        assert c1 == p1
        assert c2 == p2


# ---------------------------------------------------------------------------
# Improvement metric
# ---------------------------------------------------------------------------

class TestImprovement:
    def test_positive_when_optimized(self):
        """Improvement must be positive when instruction count decreases."""
        imp = compute_improvement(baseline_count=100, optimized_count=80)
        assert imp > 0, f"Expected positive improvement, got {imp}"
        assert abs(imp - 0.2) < 0.001, f"Expected ~0.2, got {imp}"

    def test_negative_when_worse(self):
        """Improvement must be negative when instruction count increases."""
        imp = compute_improvement(baseline_count=100, optimized_count=120)
        assert imp < 0, f"Expected negative improvement, got {imp}"

    def test_zero_when_same(self):
        """Improvement must be zero when counts are equal."""
        imp = compute_improvement(baseline_count=100, optimized_count=100)
        assert imp == 0.0, f"Expected 0.0, got {imp}"

    def test_zero_baseline(self):
        """Should return 0 when baseline is zero (avoid division by zero)."""
        imp = compute_improvement(baseline_count=0, optimized_count=50)
        assert imp == 0.0


# ---------------------------------------------------------------------------
# Cross-benchmark evaluator: evaluate_sequence
# ---------------------------------------------------------------------------

class TestEvaluateSequence:
    def test_returns_all_benchmarks(self, benchmark_files):
        """evaluate_sequence must return a result for every benchmark."""
        results = evaluate_sequence(["mem2reg"], benchmark_files)
        assert set(results.keys()) == set(benchmark_files)

    def test_result_dict_structure(self, benchmark_files):
        """Each result must have baseline_count, optimized_count, improvement."""
        results = evaluate_sequence(["mem2reg"], benchmark_files)
        for path, result in results.items():
            assert "baseline_count" in result, f"Missing baseline_count for {path}"
            assert "optimized_count" in result, f"Missing optimized_count for {path}"
            assert "improvement" in result, f"Missing improvement for {path}"
            assert isinstance(result["baseline_count"], int)
            assert isinstance(result["optimized_count"], int)
            assert isinstance(result["improvement"], float)

    def test_known_passes_produce_improvement(self, benchmark_files):
        """Standard passes on unoptimized IR must show positive improvement."""
        results = evaluate_sequence(
            ["mem2reg", "instcombine", "simplifycfg"], benchmark_files
        )
        for path, result in results.items():
            assert result["improvement"] > 0, (
                f"Expected positive improvement on {os.path.basename(path)}, "
                f"got {result['improvement']}"
            )
            assert result["optimized_count"] < result["baseline_count"], (
                f"Optimized ({result['optimized_count']}) should be < "
                f"baseline ({result['baseline_count']}) for {os.path.basename(path)}"
            )

    def test_empty_sequence_no_change(self, benchmark_files):
        """An empty pass sequence must yield zero improvement."""
        results = evaluate_sequence([], benchmark_files)
        for path, result in results.items():
            assert result["improvement"] == 0.0, (
                f"Empty sequence should give 0 improvement on {os.path.basename(path)}"
            )
            assert result["optimized_count"] == result["baseline_count"]


# ---------------------------------------------------------------------------
# Cross-benchmark evaluator: aggregate_improvements
# ---------------------------------------------------------------------------

class TestAggregateImprovements:
    def test_arithmetic_mean(self):
        """Arithmetic mean of [0.1, 0.3, 0.2] should be 0.2."""
        results = {
            "a.ll": {"improvement": 0.1},
            "b.ll": {"improvement": 0.3},
            "c.ll": {"improvement": 0.2},
        }
        agg = aggregate_improvements(results, "arithmetic_mean")
        assert abs(agg - 0.2) < 1e-9, f"Expected 0.2, got {agg}"

    def test_geometric_mean(self):
        """Geometric mean of [0.1, 0.2] via shifted-product formula."""
        results = {
            "a.ll": {"improvement": 0.1},
            "b.ll": {"improvement": 0.2},
        }
        expected = math.sqrt(1.1 * 1.2) - 1.0
        agg = aggregate_improvements(results, "geometric_mean")
        assert abs(agg - expected) < 1e-9, f"Expected {expected}, got {agg}"

    def test_geometric_mean_with_negative(self):
        """Geometric mean must handle negative improvements (regressions)."""
        results = {
            "a.ll": {"improvement": 0.5},
            "b.ll": {"improvement": -0.1},
        }
        expected = math.sqrt(1.5 * 0.9) - 1.0
        agg = aggregate_improvements(results, "geometric_mean")
        assert abs(agg - expected) < 1e-9, f"Expected {expected}, got {agg}"

    def test_single_benchmark(self):
        """With one benchmark, both methods should return the same value."""
        results = {"a.ll": {"improvement": 0.3}}
        am = aggregate_improvements(results, "arithmetic_mean")
        gm = aggregate_improvements(results, "geometric_mean")
        assert abs(am - 0.3) < 1e-9
        assert abs(gm - 0.3) < 1e-9

    def test_invalid_method_raises_valueerror(self):
        """Unsupported method names must raise ValueError."""
        with pytest.raises(ValueError):
            aggregate_improvements({"a.ll": {"improvement": 0.1}}, "median")


# ---------------------------------------------------------------------------
# Cross-benchmark evaluator: rank_sequences
# ---------------------------------------------------------------------------

class TestRankSequences:
    def test_ranking_order(self, benchmark_files):
        """Better sequences must appear first in ranking."""
        sequences = [
            [],
            ["mem2reg"],
            ["mem2reg", "instcombine", "simplifycfg"],
        ]
        ranking = rank_sequences(sequences, benchmark_files)
        assert len(ranking) == 3
        # Aggregate improvements should be in descending order
        assert ranking[0][1] >= ranking[1][1] >= ranking[2][1], (
            f"Ranking not descending: {[r[1] for r in ranking]}"
        )

    def test_original_index_preserved(self, benchmark_files):
        """Each tuple must carry the correct original index."""
        sequences = [["mem2reg"], ["instcombine"]]
        ranking = rank_sequences(sequences, benchmark_files)
        indices = {r[0] for r in ranking}
        assert indices == {0, 1}, f"Expected indices {{0, 1}}, got {indices}"

    def test_empty_sequence_ranked_last(self, benchmark_files):
        """The empty sequence (no optimization) should rank last."""
        sequences = [
            [],
            ["mem2reg", "instcombine", "simplifycfg"],
        ]
        ranking = rank_sequences(sequences, benchmark_files)
        assert ranking[-1][2] == [], (
            f"Expected empty sequence last, got {ranking[-1][2]}"
        )


# ---------------------------------------------------------------------------
# Cross-benchmark evaluator: compare_strategies
# ---------------------------------------------------------------------------

class TestCompareStrategies:
    def test_result_structure(self, benchmark_files):
        """compare_strategies must return all required keys."""
        result = compare_strategies(
            ["mem2reg"], ["mem2reg", "instcombine"], benchmark_files
        )
        for key in ("results_a", "results_b", "wins_a", "wins_b",
                     "ties", "better_overall"):
            assert key in result, f"Missing key '{key}'"

    def test_wins_sum_to_benchmark_count(self, benchmark_files):
        """wins_a + wins_b + ties must equal number of benchmarks."""
        result = compare_strategies(
            ["mem2reg"], ["mem2reg", "instcombine", "simplifycfg"],
            benchmark_files
        )
        total = result["wins_a"] + result["wins_b"] + result["ties"]
        assert total == len(benchmark_files), (
            f"wins_a({result['wins_a']}) + wins_b({result['wins_b']}) + "
            f"ties({result['ties']}) = {total} != {len(benchmark_files)}"
        )

    def test_better_overall_valid(self, benchmark_files):
        """better_overall must be 'a', 'b', or 'tie'."""
        result = compare_strategies(
            ["mem2reg"], ["mem2reg", "instcombine", "simplifycfg"],
            benchmark_files
        )
        assert result["better_overall"] in ("a", "b", "tie")

    def test_stronger_sequence_wins_overall(self, benchmark_files):
        """A non-empty sequence must beat the empty sequence overall."""
        result = compare_strategies(
            [], ["mem2reg", "instcombine", "simplifycfg"], benchmark_files
        )
        assert result["better_overall"] == "b", (
            f"Expected 'b' to win overall, got '{result['better_overall']}'"
        )


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_pipeline_finds_improvement(self):
        """The full pipeline should find positive improvement on unoptimized IR."""
        config = {
            "population_size": 15,
            "generations": 3,
            "selection_size": 4,
            "mutation_rate": 0.3,
            "min_length": 3,
            "max_length": 8,
            "seed": 42,
        }
        results = run_pipeline(BENCHMARK_IR, config)
        assert results["improvement"] > 0, (
            f"Pipeline should find positive improvement, got {results['improvement']}"
        )
        assert results["optimized_count"] < results["baseline_count"], (
            f"Optimized ({results['optimized_count']}) should be less than "
            f"baseline ({results['baseline_count']})"
        )
        assert len(results["best_sequence"]) > 0, (
            "Should find a non-empty pass sequence"
        )
        for pass_name in results["best_sequence"]:
            assert pass_name in AVAILABLE_PASSES, f"Unknown pass: {pass_name}"

    def test_evaluator_with_pipeline_result(self, benchmark_files):
        """The evaluator should correctly process pipeline-discovered sequences."""
        config = {
            "population_size": 10,
            "generations": 2,
            "selection_size": 3,
            "mutation_rate": 0.3,
            "min_length": 3,
            "max_length": 6,
            "seed": 42,
        }
        pipeline_result = run_pipeline(BENCHMARK_IR, config)
        best_seq = pipeline_result["best_sequence"]

        # Evaluate the pipeline's best sequence across all benchmarks
        eval_results = evaluate_sequence(best_seq, benchmark_files)
        agg = aggregate_improvements(eval_results, "geometric_mean")

        # The pipeline found improvement on matmul; that benchmark should
        # show positive improvement in the evaluator too
        matmul_result = eval_results[BENCHMARK_IR]
        assert matmul_result["improvement"] > 0, (
            f"Pipeline found improvement on matmul but evaluator disagrees: "
            f"{matmul_result}"
        )
        assert isinstance(agg, float)
        for bench, res in eval_results.items():
            assert res["baseline_count"] > 0
            assert isinstance(res["improvement"], float)
