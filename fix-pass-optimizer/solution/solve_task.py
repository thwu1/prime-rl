#!/usr/bin/env python3

"""Fix all five bugs in the existing modules and implement evaluator.py."""

import sys


def apply_fix(filepath, old, new):
    """Replace exactly one occurrence of old with new in filepath."""
    with open(filepath, 'r') as f:
        content = f.read()
    if old not in content:
        print(f"WARNING: pattern not found in {filepath}: {old!r}",
              file=sys.stderr)
        return False
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"Fixed: {filepath}")
    return True


# =========================================================================
# Part 1: Fix the five bugs in existing modules
# =========================================================================

# Bug 1 — instrcount.py: count_instructions reads the original input IR
#          instead of the optimized output file.
apply_fix(
    '/app/src/instrcount.py',
    'return parse_instruction_count(ir_file)',
    'return parse_instruction_count(output_file)',
)

# Bug 2 — synergy_graph.py: build_synergy_graph adds edges in the wrong
#          direction (pass_b -> pass_a instead of pass_a -> pass_b).
apply_fix(
    '/app/src/synergy_graph.py',
    'graph[pass_b].add(pass_a)',
    'graph[pass_a].add(pass_b)',
)

# Bug 3 — ga.py: select sorts ascending, picking the LEAST fit individuals
#          instead of the fittest.
apply_fix(
    '/app/src/ga.py',
    'sorted(population, key=lambda ind: ind.fitness)',
    'sorted(population, key=lambda ind: ind.fitness, reverse=True)',
)

# Bug 4 — ga.py: crossover includes the crossover-point pass in both the
#          prefix and suffix of each child, causing duplication.
apply_fix(
    '/app/src/ga.py',
    'list(parent1_seq[:idx1+1]) + list(parent2_seq[idx2:])',
    'list(parent1_seq[:idx1]) + list(parent2_seq[idx2:])',
)
apply_fix(
    '/app/src/ga.py',
    'list(parent2_seq[:idx2+1]) + list(parent1_seq[idx1:])',
    'list(parent2_seq[:idx2]) + list(parent1_seq[idx1:])',
)

# Bug 5 — optimizer.py: compute_improvement computes
#          (optimized - baseline) / baseline instead of the correct
#          (baseline - optimized) / baseline, inverting the sign.
apply_fix(
    '/app/src/optimizer.py',
    'return (optimized_count - baseline_count) / baseline_count',
    'return (baseline_count - optimized_count) / baseline_count',
)

print("\nAll bugs fixed.\n")

# =========================================================================
# Part 2: Implement evaluator.py
# =========================================================================

EVALUATOR_CODE = '''\
"""Cross-benchmark evaluation and comparison module for the LLVM pass optimizer.

Implements evaluate_sequence, aggregate_improvements, rank_sequences,
and compare_strategies.
"""

import math
from typing import List, Dict, Tuple

from src.instrcount import count_instructions


def evaluate_sequence(sequence: List[str],
                      benchmark_files: List[str]) -> Dict[str, dict]:
    """Evaluate a single pass sequence across multiple benchmark programs."""
    results = {}
    for bench in benchmark_files:
        baseline = count_instructions(bench, [])
        try:
            optimized = count_instructions(bench, sequence)
        except RuntimeError:
            optimized = baseline
        if baseline == 0:
            improvement = 0.0
        else:
            improvement = float(baseline - optimized) / baseline
        results[bench] = {
            "baseline_count": baseline,
            "optimized_count": optimized,
            "improvement": improvement,
        }
    return results


def aggregate_improvements(results: Dict[str, dict],
                           method: str = "geometric_mean") -> float:
    """Aggregate per-benchmark improvements into a single score."""
    improvements = [r["improvement"] for r in results.values()]
    if not improvements:
        return 0.0

    if method == "arithmetic_mean":
        return sum(improvements) / len(improvements)
    elif method == "geometric_mean":
        product = 1.0
        for imp in improvements:
            product *= (1.0 + imp)
        return product ** (1.0 / len(improvements)) - 1.0
    else:
        raise ValueError(
            f"Unknown aggregation method: {method!r}. "
            f"Supported: 'arithmetic_mean', 'geometric_mean'"
        )


def rank_sequences(sequences: List[List[str]],
                   benchmark_files: List[str],
                   method: str = "geometric_mean"
                   ) -> List[Tuple[int, float, List[str]]]:
    """Rank pass sequences by their cross-benchmark performance."""
    scored = []
    for i, seq in enumerate(sequences):
        results = evaluate_sequence(seq, benchmark_files)
        agg = aggregate_improvements(results, method)
        scored.append((i, agg, seq))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def compare_strategies(seq_a: List[str],
                       seq_b: List[str],
                       benchmark_files: List[str]) -> Dict:
    """Compare two pass sequences head-to-head across benchmarks."""
    results_a = evaluate_sequence(seq_a, benchmark_files)
    results_b = evaluate_sequence(seq_b, benchmark_files)

    wins_a = 0
    wins_b = 0
    ties = 0

    for bench in benchmark_files:
        imp_a = results_a[bench]["improvement"]
        imp_b = results_b[bench]["improvement"]
        if imp_a > imp_b:
            wins_a += 1
        elif imp_b > imp_a:
            wins_b += 1
        else:
            ties += 1

    agg_a = aggregate_improvements(results_a, "geometric_mean")
    agg_b = aggregate_improvements(results_b, "geometric_mean")

    if agg_a > agg_b:
        better = "a"
    elif agg_b > agg_a:
        better = "b"
    else:
        better = "tie"

    return {
        "results_a": results_a,
        "results_b": results_b,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "better_overall": better,
    }
'''

with open('/app/src/evaluator.py', 'w') as f:
    f.write(EVALUATOR_CODE)

print("Evaluator implemented: /app/src/evaluator.py")
