#!/usr/bin/env python3
"""
Differential flame graph analysis engine.

Reads two folded stack trace profiles, computes per-function exclusive (self)
and inclusive time, normalizes across profiles of different durations, and
produces a structured JSON regression report.
"""

import json
import os
import re
from collections import defaultdict

HEX_RE = re.compile(r'0x[0-9a-fA-F]+')


def parse_folded(path):
    """Parse a folded stack trace file.

    Returns dict mapping stack (str) -> sample count (int).
    Skips comments, empty lines, zero-count entries.
    Replaces hex addresses with [addr].
    """
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            stack_raw, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            if count <= 0:
                continue
            stack = HEX_RE.sub('[addr]', stack_raw)
            stacks[stack] = stacks.get(stack, 0) + count
    return stacks


def compute_function_metrics(stacks, total):
    """Compute per-function exclusive and inclusive sample counts.

    Exclusive: function is the leaf (last frame) of the stack.
    Inclusive: function appears anywhere in the stack (counted once per stack).
    Returns (exclusive_counts, inclusive_counts) as dicts.
    """
    exclusive = defaultdict(int)
    inclusive = defaultdict(int)

    for stack, count in stacks.items():
        frames = stack.split(';')
        leaf = frames[-1]
        exclusive[leaf] += count
        seen = set()
        for frame in frames:
            if frame not in seen:
                inclusive[frame] += count
                seen.add(frame)

    return dict(exclusive), dict(inclusive)


def to_pct(counts, total):
    return {f: c / total * 100 for f, c in counts.items()}


def main():
    before_stacks = parse_folded('/app/traces/before.folded')
    after_stacks = parse_folded('/app/traces/after.folded')

    before_total = sum(before_stacks.values())
    after_total = sum(after_stacks.values())
    norm_factor = after_total / before_total

    before_excl, before_incl = compute_function_metrics(
        before_stacks, before_total)
    after_excl, after_incl = compute_function_metrics(
        after_stacks, after_total)

    before_excl_pct = to_pct(before_excl, before_total)
    before_incl_pct = to_pct(before_incl, before_total)
    after_excl_pct = to_pct(after_excl, after_total)
    after_incl_pct = to_pct(after_incl, after_total)

    all_funcs = (set(before_excl) | set(before_incl)
                 | set(after_excl) | set(after_incl))

    functions = {}
    for func in all_funcs:
        be = before_excl_pct.get(func, 0.0)
        ae = after_excl_pct.get(func, 0.0)
        bi = before_incl_pct.get(func, 0.0)
        ai = after_incl_pct.get(func, 0.0)

        ed = ae - be
        id_ = ai - bi
        score = ed * 0.7 + id_ * 0.3

        in_before = func in before_excl or func in before_incl
        in_after = func in after_excl or func in after_incl

        if in_after and not in_before:
            classification = 'new'
        elif in_before and not in_after:
            classification = 'elided'
        elif score > 0:
            classification = 'worsened'
        else:
            classification = 'improved'

        functions[func] = {
            'before_exclusive_pct': round(be, 4),
            'after_exclusive_pct': round(ae, 4),
            'before_inclusive_pct': round(bi, 4),
            'after_inclusive_pct': round(ai, 4),
            'exclusive_delta_pct': round(ed, 4),
            'inclusive_delta_pct': round(id_, 4),
            'regression_score': round(score, 4),
            'classification': classification,
        }

    before_stack_set = set(before_stacks.keys())
    after_stack_set = set(after_stacks.keys())

    new_stacks = sorted([
        {
            'stack': stack,
            'samples': after_stacks[stack],
            'pct': round(after_stacks[stack] / after_total * 100, 4),
        }
        for stack in after_stack_set - before_stack_set
    ], key=lambda e: e['stack'])

    elided_stacks = sorted([
        {
            'stack': stack,
            'samples': before_stacks[stack],
            'pct': round(before_stacks[stack] / before_total * 100, 4),
        }
        for stack in before_stack_set - after_stack_set
    ], key=lambda e: e['stack'])

    ranked = sorted(
        [
            {
                'function': f,
                'score': d['regression_score'],
                'classification': d['classification'],
            }
            for f, d in functions.items()
        ],
        key=lambda x: x['score'],
        reverse=True,
    )

    report = {
        'summary': {
            'before_total_samples': before_total,
            'after_total_samples': after_total,
            'normalization_factor': round(norm_factor, 4),
        },
        'functions': functions,
        'new_stacks': new_stacks,
        'elided_stacks': elided_stacks,
        'regression_scores_ranked': ranked,
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/regression_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to /app/output/regression_report.json")
    print(f"Before: {before_total} samples, After: {after_total} samples")
    print(f"Normalization factor: {norm_factor:.4f}")
    print(f"Functions analyzed: {len(functions)}")
    print(f"New stacks: {len(new_stacks)}, Elided stacks: {len(elided_stacks)}")


if __name__ == '__main__':
    main()
