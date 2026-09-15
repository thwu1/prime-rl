#!/usr/bin/env python3
"""
LLVM Pass Sequence Optimizer using Synergy-Guided Search.

Reads synergy pair data, builds a directed graph of pass relationships,
validates passes against the installed LLVM, generates candidate sequences
from both synergy walks and known-effective patterns, and selects the
best sequence per benchmark by direct evaluation.
"""

import json
import os
import random
import subprocess
import sys
from collections import defaultdict

sys.path.insert(0, '/app')
from instcount import get_instruction_count

BENCHMARKS_DIR = '/app/benchmarks'
SYNERGY_FILE = '/app/synergy_pairs.json'
RESULTS_FILE = '/app/results.json'

random.seed(42)

# Passes known to exist in LLVM 18 new pass manager
CANDIDATE_PASSES = [
    'instcombine', 'simplifycfg', 'gvn', 'sroa', 'mem2reg',
    'dse', 'adce', 'sccp', 'early-cse', 'reassociate',
    'jump-threading', 'memcpyopt', 'aggressive-instcombine',
    'correlated-propagation', 'bdce', 'tailcallelim', 'newgvn',
    'globalopt', 'globaldce', 'deadargelim',
    'licm', 'loop-simplify', 'loop-rotate', 'loop-deletion',
    'indvars', 'inline',
]

# Pre-crafted sequences covering diverse optimization strategies
SEED_SEQUENCES = [
    # Core CSE + cleanup
    ['sroa', 'early-cse', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # Reassociate variant
    ['mem2reg', 'instcombine', 'reassociate', 'gvn', 'simplifycfg', 'dse', 'adce', 'instcombine'],
    # Extended with memcpyopt
    ['sroa', 'instcombine', 'simplifycfg', 'reassociate', 'gvn', 'memcpyopt', 'dse', 'adce', 'instcombine', 'simplifycfg'],
    # Jump threading focus
    ['sroa', 'early-cse', 'instcombine', 'jump-threading', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine'],
    # SCCP + correlated propagation
    ['mem2reg', 'early-cse', 'instcombine', 'gvn', 'simplifycfg', 'jump-threading', 'dse', 'adce', 'sccp', 'instcombine'],
    # LICM for loops
    ['sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'licm', 'adce', 'instcombine', 'simplifycfg'],
    # BDCE variant
    ['sroa', 'early-cse', 'simplifycfg', 'instcombine', 'reassociate', 'gvn', 'dse', 'bdce', 'adce', 'instcombine'],
    # Correlated propagation
    ['mem2reg', 'instcombine', 'simplifycfg', 'sccp', 'gvn', 'dse', 'adce', 'correlated-propagation', 'instcombine'],
    # Aggressive instcombine
    ['sroa', 'aggressive-instcombine', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine'],
    # NewGVN variant
    ['sroa', 'instcombine', 'newgvn', 'simplifycfg', 'dse', 'adce', 'instcombine', 'simplifycfg'],
    # Tailcallelim
    ['mem2reg', 'sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'tailcallelim', 'instcombine'],
    # Global optimizations
    ['globalopt', 'sroa', 'early-cse', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'globaldce'],
    # Jump threading + correlated
    ['sroa', 'instcombine', 'simplifycfg', 'jump-threading', 'correlated-propagation', 'gvn', 'dse', 'adce', 'instcombine'],
    # Multi-round (mimics -Oz iterative approach)
    ['sroa', 'early-cse', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'],
    # Multi-round variant 2
    ['sroa', 'instcombine', 'simplifycfg', 'reassociate', 'gvn', 'dse', 'adce', 'instcombine', 'gvn', 'simplifycfg', 'dse', 'adce'],
    # Double instcombine-gvn loop
    ['mem2reg', 'instcombine', 'gvn', 'simplifycfg', 'dse', 'instcombine', 'gvn', 'simplifycfg', 'adce'],
    # With inlining (helps mixed_ops.c with static helpers)
    ['inline', 'sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine'],
    # Inline + early-cse
    ['inline', 'sroa', 'early-cse', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine', 'simplifycfg'],
    # Global + inline
    ['globalopt', 'inline', 'sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'instcombine', 'globaldce'],
    # LICM + indvars
    ['sroa', 'instcombine', 'simplifycfg', 'licm', 'indvars', 'gvn', 'dse', 'adce', 'instcombine'],
    # Deep with LICM
    ['sroa', 'early-cse', 'instcombine', 'reassociate', 'gvn', 'simplifycfg', 'dse', 'licm', 'adce', 'instcombine', 'gvn'],
    # Deadargelim + global
    ['deadargelim', 'sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce', 'globaldce', 'instcombine'],
    # Kitchen sink
    ['globalopt', 'sroa', 'early-cse', 'instcombine', 'simplifycfg', 'reassociate', 'gvn', 'memcpyopt', 'dse', 'licm', 'adce', 'instcombine', 'simplifycfg', 'globaldce'],
    # Inline + multi-round
    ['inline', 'sroa', 'instcombine', 'gvn', 'simplifycfg', 'dse', 'adce', 'instcombine', 'gvn', 'simplifycfg', 'adce'],
]


def load_synergy_pairs():
    """Load synergy pair data from JSON."""
    with open(SYNERGY_FILE) as f:
        return json.load(f)


def build_synergy_graph(pairs, valid_passes):
    """Build directed weighted graph from synergy pairs, filtered to valid passes."""
    graph = defaultdict(list)
    for entry in pairs:
        a, b, score = entry['a'], entry['b'], entry['score']
        if a in valid_passes and b in valid_passes:
            graph[a].append((b, score))
    return dict(graph)


def validate_passes(test_ll_file):
    """Validate which passes work in the installed LLVM version."""
    valid = set()
    for p in CANDIDATE_PASSES:
        try:
            result = subprocess.run(
                ['opt', '--passes=' + p, '-S', '-o', '/dev/null', test_ll_file],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                valid.add(p)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return valid


def generate_synergy_sequence(graph, min_len=5, max_len=15):
    """Generate a pass sequence by weighted random walk on synergy graph."""
    nodes = list(graph.keys())
    if not nodes:
        return []

    current = random.choice(nodes)
    sequence = [current]
    target_len = random.randint(min_len, max_len)

    while len(sequence) < target_len:
        neighbors = graph.get(current, [])
        if neighbors and random.random() < 0.8:
            total = sum(s for _, s in neighbors)
            r = random.random() * total
            cumulative = 0
            chosen = neighbors[0][0]
            for node, score in neighbors:
                cumulative += score
                if cumulative >= r:
                    chosen = node
                    break
            current = chosen
        else:
            current = random.choice(nodes)
        sequence.append(current)

    return sequence


def filter_sequence(seq, valid_passes):
    """Filter a sequence to only valid passes."""
    return [p for p in seq if p in valid_passes]


def main():
    print("=== LLVM Pass Sequence Optimizer ===")

    # Load synergy data
    print("Loading synergy pairs...")
    pairs = load_synergy_pairs()
    print(f"  {len(pairs)} synergy pairs loaded")

    # Find benchmark files
    ll_files = sorted([f for f in os.listdir(BENCHMARKS_DIR) if f.endswith('.ll')])
    if not ll_files:
        print("ERROR: No .ll files found")
        sys.exit(1)

    test_file = os.path.join(BENCHMARKS_DIR, ll_files[0])

    # Validate passes against installed LLVM
    print("Validating passes...")
    valid_passes = validate_passes(test_file)
    print(f"  {len(valid_passes)}/{len(CANDIDATE_PASSES)} passes confirmed valid")
    print(f"  Valid: {sorted(valid_passes)}")

    # Build synergy graph filtered to valid passes
    synergy_graph = build_synergy_graph(pairs, valid_passes)
    print(f"  Synergy graph: {len(synergy_graph)} nodes")

    # Build candidate sequences
    candidates = []

    # Add pre-crafted sequences (filtered to valid passes)
    for seq in SEED_SEQUENCES:
        filtered = filter_sequence(seq, valid_passes)
        if len(filtered) >= 3:
            candidates.append(filtered)

    # Add synergy-guided random walk sequences
    for _ in range(20):
        seq = generate_synergy_sequence(synergy_graph)
        if len(seq) >= 3:
            candidates.append(seq)

    # Add greedy synergy paths (follow highest-synergy edges)
    top_starts = sorted(
        synergy_graph.keys(),
        key=lambda k: sum(s for _, s in synergy_graph.get(k, [])),
        reverse=True
    )[:8]
    for start in top_starts:
        seq = [start]
        current = start
        for _ in range(12):
            neighbors = synergy_graph.get(current, [])
            if neighbors:
                best = max(neighbors, key=lambda x: x[1])
                seq.append(best[0])
                current = best[0]
            else:
                break
        if len(seq) >= 3:
            candidates.append(seq)

    print(f"  {len(candidates)} candidate sequences generated")

    # Process each benchmark
    results = {"benchmarks": {}}

    for ll_name in ll_files:
        name = ll_name.replace('.ll', '')
        ll_path = os.path.join(BENCHMARKS_DIR, ll_name)
        print(f"\nOptimizing: {name}")

        # Get baseline counts
        orig_count = get_instruction_count(ll_path)
        oz_count = get_instruction_count(ll_path, '-Oz')
        print(f"  Original: {orig_count}, -Oz: {oz_count}")

        if orig_count is None:
            print(f"  ERROR: Cannot read {name}, using fallback")
            orig_count = 100

        if oz_count is None:
            print(f"  WARNING: -Oz failed for {name}, using original as oz baseline")
            oz_count = orig_count

        # Evaluate all candidate sequences, track the best
        best_count = orig_count
        best_seq = None

        for seq in candidates:
            passes_str = ','.join(seq)
            count = get_instruction_count(ll_path, passes_str)
            if count is not None and count < best_count:
                best_count = count
                best_seq = list(seq)

        # Fallback if nothing worked
        if best_seq is None:
            fallback_passes = [p for p in ['sroa', 'instcombine', 'simplifycfg', 'gvn', 'dse', 'adce'] if p in valid_passes]
            if len(fallback_passes) >= 3:
                passes_str = ','.join(fallback_passes)
                count = get_instruction_count(ll_path, passes_str)
                if count is not None:
                    best_count = count
                    best_seq = fallback_passes

        # Ultimate fallback
        if best_seq is None:
            best_seq = [p for p in ['instcombine', 'simplifycfg', 'gvn'] if p in valid_passes]
            if not best_seq:
                best_seq = list(valid_passes)[:3]
            passes_str = ','.join(best_seq)
            count = get_instruction_count(ll_path, passes_str)
            if count is not None:
                best_count = count

        passes_str = ','.join(best_seq)
        print(f"  Best: {best_count} ({len(best_seq)} passes)")
        if oz_count > 0:
            pct = (best_count - oz_count) / oz_count * 100
            print(f"  vs -Oz: {pct:+.1f}%")

        results['benchmarks'][name] = {
            'original_count': int(orig_count),
            'oz_count': int(oz_count),
            'optimized_count': int(best_count),
            'pass_sequence': passes_str
        }

    # Write results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {RESULTS_FILE}")

    # Summary
    print("\n=== Summary ===")
    for name, data in results['benchmarks'].items():
        oz = data['oz_count']
        opt = data['optimized_count']
        orig = data['original_count']
        status = 'BEATS -Oz' if opt < oz else f'within {round((opt-oz)/oz*100,1)}% of -Oz' if oz > 0 else 'N/A'
        print(f"  {name}: orig={orig} oz={oz} opt={opt} ({status})")


if __name__ == '__main__':
    main()
