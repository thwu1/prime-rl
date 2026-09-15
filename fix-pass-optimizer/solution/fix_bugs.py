#!/usr/bin/env python3

"""Fix all five bugs in the LLVM pass sequence optimization framework.

Bug 1 (instrcount.py): count_instructions reads the original input IR file
       instead of the optimized output file when counting instructions.
Bug 2 (synergy_graph.py): build_synergy_graph reverses edge directions,
       adding edges from pass_b to pass_a instead of pass_a to pass_b.
Bug 3 (ga.py): select sorts population by fitness ascending and takes the
       first k, selecting the LEAST fit individuals instead of the fittest.
Bug 4 (ga.py): crossover includes the crossover-point pass in both the
       prefix and suffix, duplicating it in each child sequence.
Bug 5 (optimizer.py): compute_improvement computes (optimized - baseline)
       instead of (baseline - optimized), inverting the sign.
"""

import sys


def apply_fix(filepath, old, new):
    """Replace exactly one occurrence of old with new in filepath."""
    with open(filepath, 'r') as f:
        content = f.read()
    if old not in content:
        print(f"WARNING: pattern not found in {filepath}: {old!r}", file=sys.stderr)
        return False
    if content.count(old) > 1:
        print(f"WARNING: pattern appears {content.count(old)} times in {filepath}, "
              f"replacing first: {old!r}", file=sys.stderr)
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"Fixed: {filepath}")
    return True


# ---- Bug 1: instrcount.py reads input instead of output ----
apply_fix(
    '/app/src/instrcount.py',
    'return parse_instruction_count(ir_file)',
    'return parse_instruction_count(output_file)',
)

# ---- Bug 2: synergy_graph.py reverses edge direction ----
apply_fix(
    '/app/src/synergy_graph.py',
    'graph[pass_b].add(pass_a)',
    'graph[pass_a].add(pass_b)',
)

# ---- Bug 3: ga.py selection picks least-fit ----
apply_fix(
    '/app/src/ga.py',
    'sorted(population, key=lambda ind: ind.fitness)',
    'sorted(population, key=lambda ind: ind.fitness, reverse=True)',
)

# ---- Bug 4: ga.py crossover duplicates crossover point ----
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

# ---- Bug 5: optimizer.py improvement sign is inverted ----
apply_fix(
    '/app/src/optimizer.py',
    'return (optimized_count - baseline_count) / baseline_count',
    'return (baseline_count - optimized_count) / baseline_count',
)

print("\nAll bugs fixed.")
