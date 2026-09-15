#!/usr/bin/env python3
"""
Linearizability checker for concurrent operation histories on a CAS register.

Reads JSON-converted histories (from babashka EDN->JSON conversion), checks
linearizability via backtracking search, and outputs results keyed by
original .edn filenames.

Based on linearizability theory (Herlihy & Wing, 1990) and inspired by
the Knossos checker from Jepsen.
"""

import json
import os
import sys


def apply_op(reg_value, op):
    """Apply an operation to the register at a candidate linearization point.

    Returns (new_value, valid).
    """
    f = op['f']
    value = op['value']
    is_info = op['type'] == 'info'

    if f == 'read':
        if is_info:
            return reg_value, True
        else:
            return reg_value, (value == reg_value)

    elif f == 'write':
        return value, True

    elif f == 'cas':
        old, new = value[0], value[1]
        if is_info:
            if reg_value == old:
                return new, True
            else:
                return reg_value, True
        else:
            if reg_value == old:
                return new, True
            else:
                return reg_value, False

    return reg_value, False


def parse_history(history):
    """Parse a raw history into paired operations."""
    ops = []
    invocations = {}

    for event in history:
        proc = event['process']
        typ = event['type']

        if typ == 'invoke':
            invocations[proc] = event
        elif typ in ('ok', 'fail', 'info'):
            if proc in invocations:
                inv = invocations.pop(proc)
                ops.append({
                    'process': proc,
                    'f': event['f'],
                    'value': event.get('value'),
                    'type': typ,
                    'invoke_index': inv['index'],
                    'complete_index': event['index'],
                })

    return ops


def check_linearizable(history):
    """Check if a history is linearizable w.r.t. a CAS register."""
    all_ops = parse_history(history)

    ok_ops = [op for op in all_ops if op['type'] == 'ok']
    info_ops = [op for op in all_ops if op['type'] == 'info']

    num_info = len(info_ops)
    for info_mask in range(1 << num_info):
        active_info = [info_ops[i] for i in range(num_info) if info_mask & (1 << i)]
        candidate_ops = ok_ops + active_info

        if _check_ops_linearizable(candidate_ops):
            return True

    return False


def _check_ops_linearizable(ops):
    """Check if a set of operations admits a valid linearization."""
    n = len(ops)
    if n == 0:
        return True

    must_precede = [set() for _ in range(n)]
    for i in range(n):
        if ops[i]['type'] != 'ok':
            continue
        ci = ops[i]['complete_index']
        for j in range(n):
            if i != j and ci < ops[j]['invoke_index']:
                must_precede[j].add(i)

    linearized = [False] * n
    return _backtrack(ops, linearized, None, must_precede, 0, n)


def _backtrack(ops, linearized, reg_value, must_precede, count, n):
    """Recursive backtracking search for a valid linearization order."""
    if count == n:
        return True

    for i in range(n):
        if linearized[i]:
            continue
        if not all(linearized[j] for j in must_precede[i]):
            continue

        new_value, valid = apply_op(reg_value, ops[i])
        if valid:
            linearized[i] = True
            if _backtrack(ops, linearized, new_value, must_precede, count + 1, n):
                return True
            linearized[i] = False

    return False


def check_file(filepath):
    """Check a single JSON history file for linearizability."""
    with open(filepath) as f:
        history = json.load(f)
    return check_linearizable(history)


def main():
    json_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/json_histories'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/results.json'

    results = {}
    for filename in sorted(os.listdir(json_dir)):
        if filename.endswith('.json'):
            filepath = os.path.join(json_dir, filename)
            result = check_file(filepath)
            # Map back to .edn filename for results
            edn_name = filename[:-5] + '.edn'
            results[edn_name] = result

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == '__main__':
    main()
