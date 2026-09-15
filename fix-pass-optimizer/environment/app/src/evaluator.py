
"""Cross-benchmark evaluation and comparison module for the LLVM pass optimizer.

Provides functions to evaluate pass sequences across multiple LLVM IR
benchmark programs, aggregate per-benchmark results, rank sequences, and
compare optimization strategies head-to-head.

All four public functions must be implemented. Read the docstrings carefully
for the expected semantics, return types, and edge-case behavior.
"""

import math
from typing import List, Dict, Tuple

from src.instrcount import count_instructions


def evaluate_sequence(sequence: List[str],
                      benchmark_files: List[str]) -> Dict[str, dict]:
    """Evaluate a single pass sequence across multiple benchmark programs.

    For each benchmark file:
      1. Measure the baseline instruction count with an empty pass list.
      2. Measure the optimized instruction count with the given sequence.
      3. Compute the relative improvement:
             improvement = (baseline - optimized) / baseline
         If baseline is 0, set improvement to 0.0.

    If ``count_instructions`` raises ``RuntimeError`` for a benchmark
    (e.g. ``opt`` crashes on the given passes), record improvement as 0.0
    and set optimized_count equal to baseline_count for that benchmark.

    Args:
        sequence: List of LLVM pass names (strings).
        benchmark_files: List of absolute paths to ``.ll`` files.

    Returns:
        Dict mapping each benchmark file path to a dict with keys:
            ``"baseline_count"`` (int), ``"optimized_count"`` (int),
            ``"improvement"`` (float).
    """
    raise NotImplementedError("evaluate_sequence must be implemented")


def aggregate_improvements(results: Dict[str, dict],
                           method: str = "geometric_mean") -> float:
    """Aggregate per-benchmark improvements into a single score.

    Supported methods:

    ``"arithmetic_mean"``
        Simple average of all improvement values.

    ``"geometric_mean"``
        Uses the shifted-product formula standard in compiler benchmarking::

            product = (1 + imp_1) * (1 + imp_2) * ... * (1 + imp_n)
            aggregate = product ** (1/n) - 1

        This rewards consistency across benchmarks and correctly handles
        negative improvements (regressions).

    If *results* is empty, return 0.0.

    Args:
        results: Dict from ``evaluate_sequence`` — each value must contain
            an ``"improvement"`` key with a float value.
        method: ``"arithmetic_mean"`` or ``"geometric_mean"``.

    Returns:
        Aggregated improvement score (float).  Positive means net gain.

    Raises:
        ValueError: If *method* is not one of the two supported strings.
    """
    raise NotImplementedError("aggregate_improvements must be implemented")


def rank_sequences(sequences: List[List[str]],
                   benchmark_files: List[str],
                   method: str = "geometric_mean"
                   ) -> List[Tuple[int, float, List[str]]]:
    """Rank pass sequences by their cross-benchmark performance.

    For each sequence, call ``evaluate_sequence`` and then
    ``aggregate_improvements`` with the chosen *method*.  Return the
    sequences sorted **descending** by aggregate improvement (best first).

    Args:
        sequences: List of pass sequences (each a list of strings).
        benchmark_files: List of ``.ll`` file paths.
        method: Aggregation method forwarded to ``aggregate_improvements``.

    Returns:
        List of ``(original_index, aggregate_improvement, sequence)`` tuples
        sorted so that the highest aggregate improvement comes first.
    """
    raise NotImplementedError("rank_sequences must be implemented")


def compare_strategies(seq_a: List[str],
                       seq_b: List[str],
                       benchmark_files: List[str]) -> Dict:
    """Compare two pass sequences head-to-head across benchmarks.

    Evaluate both sequences on every benchmark.  For each benchmark,
    determine which sequence achieves a higher improvement (or if they
    tie).  Determine the overall winner by comparing their geometric-mean
    aggregate improvements.

    Args:
        seq_a: First pass sequence.
        seq_b: Second pass sequence.
        benchmark_files: List of ``.ll`` file paths.

    Returns:
        Dict with keys:

        ``"results_a"``
            Per-benchmark results for *seq_a* (from ``evaluate_sequence``).
        ``"results_b"``
            Per-benchmark results for *seq_b*.
        ``"wins_a"``
            Number of benchmarks where *seq_a* has strictly higher improvement.
        ``"wins_b"``
            Number of benchmarks where *seq_b* has strictly higher improvement.
        ``"ties"``
            Number of benchmarks where both have equal improvement.
        ``"better_overall"``
            ``"a"``, ``"b"``, or ``"tie"`` — determined by comparing the
            geometric-mean aggregate of each sequence's results.
    """
    raise NotImplementedError("compare_strategies must be implemented")
