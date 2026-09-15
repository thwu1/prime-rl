#!/usr/bin/env python3
"""LLVM pass phase-ordering optimizer.


Finds per-benchmark and universal pass sequences that minimize
IR instruction count beyond -Oz, subject to a 25-pass budget
and a no-regression constraint on the universal sequence.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/app')
from count_ir import count_instructions

MAX_PASSES = 25

# Curated list of LLVM 18 new-PM pass names
PASSES = [
    'inline', 'sroa', 'mem2reg', 'instcombine', 'aggressive-instcombine',
    'simplifycfg', 'early-cse', 'gvn', 'dse', 'adce', 'bdce', 'dce',
    'reassociate', 'sccp', 'jump-threading', 'correlated-propagation',
    'memcpyopt', 'tailcallelim', 'licm', 'loop-rotate', 'loop-unroll',
    'loop-deletion', 'loop-simplifycfg', 'indvars',
    'globalopt', 'globaldce', 'deadargelim', 'ipsccp',
]

# Template sequences — each exploits a different optimization strategy.
TEMPLATES = [
    # T1: Aggressive inline + cleanup
    ['inline', 'sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # T2: Inline + loop opts + cleanup
    ['inline', 'sroa', 'instcombine', 'simplifycfg', 'loop-rotate', 'licm',
     'loop-unroll', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # T3: Multiple cleanup rounds
    ['inline', 'sroa', 'early-cse', 'instcombine', 'simplifycfg', 'reassociate',
     'gvn', 'dse', 'memcpyopt', 'adce', 'instcombine', 'simplifycfg', 'dce'],
    # T4: Full pipeline with module passes
    ['inline', 'ipsccp', 'globalopt', 'sroa', 'early-cse', 'instcombine',
     'simplifycfg', 'reassociate', 'loop-rotate', 'licm', 'loop-unroll',
     'gvn', 'memcpyopt', 'dse', 'instcombine', 'jump-threading',
     'simplifycfg', 'adce', 'globaldce'],
    # T5: GVN-heavy
    ['inline', 'sroa', 'early-cse', 'gvn', 'instcombine', 'simplifycfg',
     'early-cse', 'gvn', 'dse', 'adce', 'instcombine', 'dce'],
    # T6: Loop-focused
    ['inline', 'sroa', 'instcombine', 'simplifycfg', 'loop-rotate', 'indvars',
     'licm', 'loop-unroll', 'loop-deletion', 'loop-simplifycfg',
     'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # T7: Memory optimization
    ['inline', 'sroa', 'mem2reg', 'instcombine', 'simplifycfg', 'gvn',
     'memcpyopt', 'dse', 'instcombine', 'simplifycfg', 'adce'],
    # T8: Kitchen sink (trimmed to 25)
    ['inline', 'deadargelim', 'ipsccp', 'globalopt', 'sroa',
     'aggressive-instcombine', 'instcombine', 'simplifycfg', 'reassociate',
     'early-cse', 'gvn', 'loop-rotate', 'licm', 'loop-unroll', 'instcombine',
     'memcpyopt', 'dse', 'jump-threading', 'correlated-propagation',
     'simplifycfg', 'adce', 'globaldce', 'dce'],
    # T9: Minimal inline + cleanup
    ['inline', 'instcombine', 'simplifycfg', 'sroa', 'dce'],
    # T10: Double inline
    ['inline', 'instcombine', 'simplifycfg', 'inline', 'instcombine',
     'simplifycfg', 'sroa', 'gvn', 'dse', 'adce'],
    # T11: No inline — loop + cleanup
    ['sroa', 'instcombine', 'simplifycfg', 'loop-rotate', 'loop-unroll',
     'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # T12: No inline — multi-round cleanup
    ['sroa', 'early-cse', 'instcombine', 'simplifycfg', 'reassociate', 'gvn',
     'dse', 'adce', 'instcombine', 'simplifycfg', 'dce'],
]


def evaluate(input_ll, passes):
    """Run opt with the given passes and count instructions. Returns count or None."""
    if not passes:
        return None
    passes_str = ','.join(passes)
    with tempfile.NamedTemporaryFile(suffix='.ll', delete=False, dir='/tmp') as f:
        output = f.name
    try:
        ret = subprocess.run(
            ['opt', f'-passes={passes_str}', input_ll, '-S', '-o', output],
            capture_output=True, text=True, timeout=30
        )
        if ret.returncode != 0:
            return None
        return count_instructions(output)
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.unlink(output)
        except OSError:
            pass


def get_oz_count(input_ll):
    """Measure the -Oz baseline instruction count."""
    with tempfile.NamedTemporaryFile(suffix='.ll', delete=False, dir='/tmp') as f:
        output = f.name
    try:
        ret = subprocess.run(
            ['opt', '-Oz', input_ll, '-S', '-o', output],
            capture_output=True, text=True, timeout=30
        )
        if ret.returncode != 0:
            return None
        return count_instructions(output)
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.unlink(output)
        except OSError:
            pass


def refine(input_ll, seq, count):
    """Greedy refinement: remove unnecessary passes, then try appending/prepending."""
    # Phase 1: Iteratively remove passes that don't help
    changed = True
    while changed:
        changed = False
        for i in range(len(seq)):
            candidate = seq[:i] + seq[i+1:]
            if not candidate:
                continue
            c = evaluate(input_ll, candidate)
            if c is not None and c <= count:
                seq = candidate
                count = c
                changed = True
                break

    # Phase 2: Try appending each pass (respect budget)
    for p in PASSES:
        if len(seq) >= MAX_PASSES:
            break
        c = evaluate(input_ll, seq + [p])
        if c is not None and c < count:
            seq = seq + [p]
            count = c

    # Phase 3: Try prepending module-level passes
    for p in ['inline', 'ipsccp', 'globalopt', 'deadargelim']:
        if len(seq) >= MAX_PASSES:
            break
        if seq and p == seq[0]:
            continue
        c = evaluate(input_ll, [p] + seq)
        if c is not None and c < count:
            seq = [p] + seq
            count = c

    # Phase 4: Second removal pass after additions
    changed = True
    while changed:
        changed = False
        for i in range(len(seq)):
            candidate = seq[:i] + seq[i+1:]
            if not candidate:
                continue
            c = evaluate(input_ll, candidate)
            if c is not None and c <= count:
                seq = candidate
                count = c
                changed = True
                break

    return seq, count


def optimize_benchmark(input_ll, name):
    """Find an optimal pass sequence for a single benchmark."""
    oz_count = get_oz_count(input_ll)
    if oz_count is None:
        print(f"  ERROR: could not measure -Oz baseline for {name}")
        return [], 0, 0, 0.0

    best_seq = None
    best_count = oz_count

    # Evaluate all templates (within budget)
    for template in TEMPLATES:
        if len(template) > MAX_PASSES:
            continue
        c = evaluate(input_ll, template)
        if c is not None and c < best_count:
            best_count = c
            best_seq = template[:]

    # Refine the best template
    if best_seq is not None:
        best_seq, best_count = refine(input_ll, best_seq, best_count)
    else:
        # Fallback: pick the best template overall and refine
        fallback_best = None
        fallback_count = float('inf')
        for template in TEMPLATES:
            if len(template) > MAX_PASSES:
                continue
            c = evaluate(input_ll, template)
            if c is not None and c < fallback_count:
                fallback_count = c
                fallback_best = template[:]
        if fallback_best is not None:
            best_seq, best_count = refine(input_ll, fallback_best, fallback_count)
        else:
            best_seq = ['instcombine', 'simplifycfg', 'sroa']
            best_count = evaluate(input_ll, best_seq) or oz_count

    improvement = (oz_count - best_count) / oz_count * 100 if oz_count > 0 else 0.0
    return best_seq, best_count, oz_count, improvement


def eval_universal_full(seq, benchmark_files, oz_counts):
    """Evaluate a sequence on all benchmarks.

    Always returns results — never returns None.
    Returns (avg_improvement, per_results, n_regressions, worst_regression).
    If opt fails on any benchmark, returns sentinel values indicating failure.
    """
    per_results = {}
    improvements = []
    n_regressions = 0
    worst_regression = 0.0
    for name, input_ll in benchmark_files.items():
        c = evaluate(input_ll, seq)
        if c is None:
            # opt failed — return failure sentinel
            return -999.0, {}, len(benchmark_files), -999.0
        oz = oz_counts[name]
        imp = (oz - c) / oz * 100 if oz > 0 else 0.0
        if imp < -0.01:
            n_regressions += 1
            if imp < worst_regression:
                worst_regression = imp
        per_results[name] = {
            'optimized_count': c,
            'oz_count': oz,
            'improvement_pct': round(imp, 4)
        }
        improvements.append(imp)
    avg = sum(improvements) / len(improvements) if improvements else 0.0
    return avg, per_results, n_regressions, worst_regression


def optimize_universal(benchmark_files, oz_counts):
    """Find a universal sequence that improves all benchmarks without regression.

    Uses a multi-phase strategy:
    1. Evaluate all templates, preferring non-regressing ones with best average.
    2. If no non-regressing template found, take the one with fewest regressions
       and try to eliminate regressions via pass removal.
    3. Greedy refinement: remove unhelpful passes, add helpful ones.
    """
    best_seq = None
    best_avg = -999.0
    best_results = None
    best_regressions = len(benchmark_files)

    # Also track the overall best regardless of regression for fallback
    fallback_seq = None
    fallback_avg = -999.0
    fallback_results = None
    fallback_regressions = len(benchmark_files)

    # Phase 1: Evaluate all templates
    for template in TEMPLATES:
        if len(template) > MAX_PASSES:
            continue
        avg, per_results, n_reg, worst = eval_universal_full(
            template, benchmark_files, oz_counts)

        # Track best non-regressing
        if n_reg == 0 and avg > best_avg:
            best_avg = avg
            best_seq = template[:]
            best_results = per_results
            best_regressions = 0

        # Track overall best (fewest regressions, then best average)
        if (n_reg < fallback_regressions) or \
           (n_reg == fallback_regressions and avg > fallback_avg):
            fallback_avg = avg
            fallback_seq = template[:]
            fallback_results = per_results
            fallback_regressions = n_reg

    # If no non-regressing template, try to fix the best fallback
    if best_seq is None and fallback_seq is not None:
        print(f"  No non-regressing template found (best has {fallback_regressions} regressions). Trying repair...")
        best_seq = fallback_seq[:]
        best_avg = fallback_avg
        best_results = fallback_results
        best_regressions = fallback_regressions

        # Try removing passes one at a time to eliminate regressions
        changed = True
        while changed and best_regressions > 0:
            changed = False
            for i in range(len(best_seq)):
                candidate = best_seq[:i] + best_seq[i+1:]
                if not candidate:
                    continue
                avg, per_results, n_reg, worst = eval_universal_full(
                    candidate, benchmark_files, oz_counts)
                # Accept if it reduces regressions, or same regressions but better avg
                if n_reg < best_regressions or \
                   (n_reg == best_regressions and avg > best_avg):
                    best_seq = candidate
                    best_avg = avg
                    best_results = per_results
                    best_regressions = n_reg
                    changed = True
                    break

    # If still no sequence, use a very safe minimal sequence
    if best_seq is None:
        safe_seqs = [
            ['inline', 'sroa', 'instcombine', 'simplifycfg', 'adce'],
            ['instcombine', 'simplifycfg', 'adce'],
            ['instcombine', 'simplifycfg'],
            ['instcombine'],
            ['dce'],
        ]
        for safe in safe_seqs:
            avg, per_results, n_reg, worst = eval_universal_full(
                safe, benchmark_files, oz_counts)
            if avg > -999.0:
                best_seq = safe
                best_avg = avg
                best_results = per_results
                best_regressions = n_reg
                if n_reg == 0:
                    break

    # Phase 2: Greedy removal — remove passes that don't help universally
    if best_seq is not None:
        changed = True
        while changed:
            changed = False
            for i in range(len(best_seq)):
                candidate = best_seq[:i] + best_seq[i+1:]
                if not candidate:
                    continue
                avg, per_results, n_reg, worst = eval_universal_full(
                    candidate, benchmark_files, oz_counts)
                # Keep removal if: fewer regressions, or same regressions and >= avg
                if n_reg < best_regressions or \
                   (n_reg <= best_regressions and avg >= best_avg):
                    best_seq = candidate
                    best_avg = avg
                    best_results = per_results
                    best_regressions = n_reg
                    changed = True
                    break

    # Phase 3: Greedy addition — try appending passes that help universally
    if best_seq is not None:
        for p in PASSES:
            if len(best_seq) >= MAX_PASSES:
                break
            avg, per_results, n_reg, worst = eval_universal_full(
                best_seq + [p], benchmark_files, oz_counts)
            # Accept if it reduces regressions or improves avg without new regressions
            if (n_reg < best_regressions) or \
               (n_reg <= best_regressions and avg > best_avg):
                best_seq = best_seq + [p]
                best_avg = avg
                best_results = per_results
                best_regressions = n_reg

    # Phase 4: Final removal pass
    if best_seq is not None:
        changed = True
        while changed:
            changed = False
            for i in range(len(best_seq)):
                candidate = best_seq[:i] + best_seq[i+1:]
                if not candidate:
                    continue
                avg, per_results, n_reg, worst = eval_universal_full(
                    candidate, benchmark_files, oz_counts)
                if n_reg < best_regressions or \
                   (n_reg <= best_regressions and avg >= best_avg):
                    best_seq = candidate
                    best_avg = avg
                    best_results = per_results
                    best_regressions = n_reg
                    changed = True
                    break

    # Phase 5: If still regressing, try sub-sequences of the per-benchmark best
    # sequences that might work universally
    if best_regressions > 0 and best_seq is not None:
        print(f"  Still {best_regressions} regressions after refinement. Trying pass intersection...")
        # Try progressively smaller subsets by removing each pass
        for _ in range(len(best_seq)):
            if best_regressions == 0:
                break
            improved = False
            for i in range(len(best_seq)):
                candidate = best_seq[:i] + best_seq[i+1:]
                if not candidate:
                    continue
                avg, per_results, n_reg, worst = eval_universal_full(
                    candidate, benchmark_files, oz_counts)
                if n_reg < best_regressions:
                    best_seq = candidate
                    best_avg = avg
                    best_results = per_results
                    best_regressions = n_reg
                    improved = True
                    break
            if not improved:
                break

    return best_seq, best_avg, best_results, best_regressions


def main():
    benchmarks_dir = '/app/benchmarks/'

    # Collect benchmark files and measure Oz baselines
    benchmark_files = {}
    oz_counts = {}
    for ll_file in sorted(os.listdir(benchmarks_dir)):
        if not ll_file.endswith('.ll'):
            continue
        name = ll_file[:-3]
        path = os.path.join(benchmarks_dir, ll_file)
        benchmark_files[name] = path
        oz = get_oz_count(path)
        if oz is not None:
            oz_counts[name] = oz
        print(f"Baseline {name}: -Oz = {oz}")

    # --- Per-benchmark optimization ---
    bench_results = {}
    for name, input_path in sorted(benchmark_files.items()):
        print(f"\nOptimizing {name}...")
        best_seq, best_count, oz_count, improvement = optimize_benchmark(input_path, name)
        print(f"  -Oz: {oz_count}  Best: {best_count}  Improvement: {improvement:.2f}%  Passes: {len(best_seq)}")
        bench_results[name] = {
            'pass_sequence': best_seq,
            'optimized_count': best_count,
            'oz_count': oz_count,
            'improvement_pct': round(improvement, 4)
        }

    bench_avg = sum(r['improvement_pct'] for r in bench_results.values()) / len(bench_results)
    print(f"\nPer-benchmark average improvement: {bench_avg:.2f}%")

    # --- Universal sequence optimization ---
    print("\nOptimizing universal sequence...")
    uni_seq, uni_avg, uni_results, uni_regressions = optimize_universal(benchmark_files, oz_counts)

    if uni_seq is None or uni_results is None:
        # Ultimate fallback: use the simplest possible sequence
        print("  WARNING: Could not find any working universal sequence, using minimal fallback")
        uni_seq = ['instcombine']
        uni_avg, uni_results, _, _ = eval_universal_full(uni_seq, benchmark_files, oz_counts)

    print(f"Universal sequence ({len(uni_seq)} passes): avg improvement = {uni_avg:.2f}%  regressions = {uni_regressions}")
    for name, r in sorted(uni_results.items()):
        print(f"  {name}: {r['improvement_pct']:.2f}%")

    # --- Write output ---
    output = {
        'benchmarks': bench_results,
        'universal': {
            'pass_sequence': uni_seq,
            'results': uni_results,
        }
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to /app/results.json")
    if bench_avg >= 2.0:
        print("PASS: per-benchmark meets 2% threshold")
    else:
        print("WARN: per-benchmark below 2% threshold")
    if uni_avg >= 0.5:
        print("PASS: universal meets 0.5% threshold")
    else:
        print("WARN: universal below 0.5% threshold")
    if uni_regressions == 0:
        print("PASS: universal has no regressions")
    else:
        print(f"WARN: universal has {uni_regressions} regressions")


if __name__ == '__main__':
    main()
