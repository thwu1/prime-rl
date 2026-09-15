#!/usr/bin/env python3
"""
Evaluate candidate parallelization strategies from /app/candidates.md
and write verdicts to /app/verdicts.json.

Each candidate is analyzed for:
- Correct handling of data boundaries (e.g. bin index clamping)
- Proper OpenMP data-sharing semantics (private vs firstprivate vs local)
- Race-freedom on shared accumulation variables
- Correct parallel reduction patterns
"""

import json
import os


def analyze_candidates():
    """Produce verdicts for all 12 candidate strategies."""
    verdicts = {}

    # --- histogram ---
    verdicts["histogram"] = {
        "A": {
            "correct": False,
            "flaw": (
                "Bin index computed as int(data[i]*NBINS) without clamping; "
                "when data[i]==1.0 the index equals NBINS, causing an "
                "out-of-bounds write to hist[256] (buffer overflow / undefined behavior)"
            ),
        },
        "B": {
            "correct": True,
            "flaw": "none",
        },
        "C": {
            "correct": False,
            "flaw": (
                "Bin index computed as int(data[i]*NBINS) without clamping; "
                "when data[i]==1.0 the index equals NBINS, writing past the "
                "per-thread histogram boundary into the adjacent thread's "
                "memory region, causing cross-thread corruption and a data race"
            ),
        },
    }

    # --- jacobi ---
    verdicts["jacobi"] = {
        "A": {
            "correct": False,
            "flaw": (
                "Stencil update reads and writes the same array u in-place "
                "inside a parallel for; neighboring rows updated by different "
                "threads create read-write data races on shared grid elements "
                "(no double buffering)"
            ),
        },
        "B": {
            "correct": False,
            "flaw": (
                "Sum accumulation uses '#pragma omp parallel for' without a "
                "reduction clause; multiple threads concurrently execute "
                "'sum += u[i]' on the shared variable sum, causing a data race"
            ),
        },
        "C": {
            "correct": True,
            "flaw": "none",
        },
    }

    # --- knn_search ---
    verdicts["knn_search"] = {
        "A": {
            "correct": False,
            "flaw": (
                "Work buffers dists and idx are declared before the parallel "
                "region and implicitly shared; all threads read and write the "
                "same vectors concurrently when processing different queries, "
                "causing data races"
            ),
        },
        "B": {
            "correct": False,
            "flaw": (
                "The 'private' clause default-constructs new std::vector "
                "instances for each thread (size 0, empty); accessing "
                "dists[i] and idx[i] in the loop body is an out-of-bounds "
                "access on empty vectors, causing undefined behavior"
            ),
        },
        "C": {
            "correct": True,
            "flaw": "none",
        },
    }

    # --- lu_factor ---
    verdicts["lu_factor"] = {
        "A": {
            "correct": False,
            "flaw": (
                "Shared variables maxrow and maxval are read and written by "
                "all threads in the parallel for without any synchronization; "
                "concurrent compare-and-update on these variables is a data "
                "race producing non-deterministic pivot selection"
            ),
        },
        "B": {
            "correct": False,
            "flaw": (
                "reduction(max:maxval) correctly reduces the maximum value "
                "across threads, but maxrow remains shared and is written by "
                "multiple threads without synchronization; the final maxrow "
                "may not correspond to the reduced maxval, and the concurrent "
                "writes to maxrow constitute a data race"
            ),
        },
        "C": {
            "correct": True,
            "flaw": "none",
        },
    }

    return verdicts


if __name__ == "__main__":
    verdicts = analyze_candidates()
    output_path = "/app/verdicts.json"
    with open(output_path, "w") as f:
        json.dump(verdicts, f, indent=2)
    print(f"Verdicts written to {output_path}")

    # Summary
    for prog, candidates in verdicts.items():
        correct_count = sum(1 for v in candidates.values() if v["correct"])
        buggy_count = len(candidates) - correct_count
        print(f"  {prog}: {correct_count} correct, {buggy_count} buggy")
