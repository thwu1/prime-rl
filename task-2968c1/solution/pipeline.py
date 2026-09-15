#!/usr/bin/env python3
"""
Pipeline: greybox fuzzing + Ochiai fault localization + delta debugging.

Discovers bugs in target.py by differential testing against reference.py,
localizes faulty lines, and minimizes failure-inducing inputs.
"""
import sys
import os
import json

sys.path.insert(0, '/app')

from coverage_tracker import CoverageTracker
from greybox_fuzzer import GreyboxFuzzer, AFLFastSchedule
from fault_localizer import OchiaiLocalizer
from delta_debugger import ddmin

import target
import reference

TARGET_FILE = os.path.abspath(target.__file__)
NUM_FUZZ_ITERATIONS = 40000


def load_seeds():
    with open('/app/seeds.json') as f:
        return json.load(f)


def make_run_func(tracker, localizer):
    """Build the runner that the fuzzer calls on each input."""

    def run_func(inp):
        # Run target with coverage tracking
        t_result, t_exc, coverage = tracker.track_file(
            target.execute, TARGET_FILE, inp
        )

        # Run reference without coverage
        try:
            r_result = reference.execute(inp)
            r_exc = None
        except Exception as e:
            r_result = None
            r_exc = e

        # Build output strings for comparison
        if t_exc is not None:
            t_str = f"ERROR:{type(t_exc).__name__}:{t_exc}"
        else:
            t_str = str(t_result)

        if r_exc is not None:
            r_str = f"ERROR:{type(r_exc).__name__}:{r_exc}"
        else:
            r_str = str(r_result)

        # Classify outcome
        if t_str == r_str:
            outcome = 'pass'
        else:
            outcome = 'fail'

        # Feed coverage into localizer
        localizer.add_run(coverage, outcome)

        info = {'target_output': t_str, 'reference_output': r_str}
        return coverage, outcome, info

    return run_func


def make_oracle():
    """Build a simple pass/fail oracle for ddmin."""

    def oracle(inp):
        try:
            t = str(target.execute(inp))
        except Exception as e:
            t = f"ERROR:{type(e).__name__}:{e}"
        try:
            r = str(reference.execute(inp))
        except Exception as e:
            r = f"ERROR:{type(e).__name__}:{e}"
        return 'FAIL' if t != r else 'PASS'

    return oracle


def deduplicate_failures(failures):
    """Keep one representative input per unique (target_output, ref_output) pair."""
    seen = set()
    unique = []
    for f in failures:
        key = (f['info']['target_output'], f['info']['reference_output'])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def main():
    seeds = load_seeds()
    tracker = CoverageTracker()
    localizer = OchiaiLocalizer()
    schedule = AFLFastSchedule(exponent=5.0)
    fuzzer = GreyboxFuzzer(seeds, schedule)

    run_func = make_run_func(tracker, localizer)

    print(f"[pipeline] Fuzzing with {NUM_FUZZ_ITERATIONS} iterations...")
    raw_failures = fuzzer.run(run_func, num_iterations=NUM_FUZZ_ITERATIONS)
    print(f"[pipeline] Raw failures: {len(raw_failures)}")

    unique_failures = deduplicate_failures(raw_failures)
    print(f"[pipeline] Unique failure patterns: {len(unique_failures)}")

    # Ochiai rankings
    print("[pipeline] Computing Ochiai rankings...")
    rankings = localizer.rank()

    # Delta debugging
    print("[pipeline] Minimizing failure-inducing inputs...")
    oracle = make_oracle()
    minimized = []

    for f in unique_failures[:25]:
        original = f['input']
        try:
            if oracle(original) != 'FAIL':
                continue
            reduced = ddmin(oracle, original)
            minimized.append({
                'original': original,
                'minimized': reduced,
                'target_output': f['info']['target_output'],
                'reference_output': f['info']['reference_output'],
            })
        except Exception as e:
            print(f"[pipeline] ddmin skipped: {e}")

    # Write results
    os.makedirs('/app/results', exist_ok=True)

    crashes_out = []
    for f in unique_failures:
        crashes_out.append({
            'input': f['input'],
            'target_output': f['info']['target_output'],
            'reference_output': f['info']['reference_output'],
        })

    with open('/app/results/crashes.json', 'w') as fp:
        json.dump(crashes_out, fp, indent=2)

    rankings_out = []
    for event, score in rankings[:50]:
        fn, lineno = event
        rankings_out.append({
            'location': [fn, lineno],
            'score': round(score, 6),
        })

    with open('/app/results/rankings.json', 'w') as fp:
        json.dump(rankings_out, fp, indent=2)

    with open('/app/results/minimized.json', 'w') as fp:
        json.dump(minimized, fp, indent=2)

    print(f"[pipeline] Results written to /app/results/")
    print(f"  Crashes:   {len(crashes_out)}")
    print(f"  Rankings:  {len(rankings_out)}")
    print(f"  Minimized: {len(minimized)}")


if __name__ == '__main__':
    main()
