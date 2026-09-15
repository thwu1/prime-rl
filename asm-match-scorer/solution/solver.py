#!/usr/bin/env python3
"""
MIPS Assembly Matching Scorer

Compares two MIPS assembly functions, finds the optimal register renaming
via minimum-weight bipartite matching (Hungarian algorithm), then scores
the alignment using Needleman-Wunsch global sequence alignment.
"""

import json
import re
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

# All renameable MIPS registers (temporaries and saved)
RENAMEABLE = set()
for _i in range(8):
    RENAMEABLE.add(f"$s{_i}")
for _i in range(10):
    RENAMEABLE.add(f"$t{_i}")
RENAMEABLE_LIST = sorted(RENAMEABLE)

GAP_PENALTY = 10


def parse_assembly(filepath):
    """Parse an assembly file into a list of (mnemonic, [operands])."""
    instructions = []
    with open(filepath) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line or line.endswith(":"):
                continue
            parts = line.split(None, 1)
            mnemonic = parts[0]
            operands = _split_operands(parts[1]) if len(parts) > 1 else []
            instructions.append((mnemonic, operands))
    return instructions


def _split_operands(s):
    """Split operands on commas, respecting parentheses."""
    operands = []
    depth = 0
    current = []
    for ch in s:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            operands.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        operands.append("".join(current).strip())
    return operands


def _extract_registers(op):
    """Extract register names from an operand string."""
    # Memory operand: offset($reg)
    m = re.match(r"^-?\w*\((\$\w+)\)$", op)
    if m:
        return [m.group(1)]
    # Direct register
    if op.startswith("$"):
        return [op]
    return []


def _get_renameable_regs(instructions):
    """Get the sorted list of renameable registers used in instructions."""
    regs = set()
    for _, operands in instructions:
        for op in operands:
            for reg in _extract_registers(op):
                if reg in RENAMEABLE:
                    regs.add(reg)
    return sorted(regs)


def _apply_mapping_to_op(op, mapping):
    """Apply register mapping to a single operand."""
    m = re.match(r"^(-?\w*)\((\$\w+)\)$", op)
    if m:
        offset = m.group(1)
        reg = m.group(2)
        return f"{offset}({mapping.get(reg, reg)})"
    if op.startswith("$"):
        return mapping.get(op, op)
    return op


def _apply_mapping(instructions, mapping):
    """Apply register mapping to all instructions (simultaneous substitution)."""
    result = []
    for mnemonic, operands in instructions:
        new_ops = [_apply_mapping_to_op(op, mapping) for op in operands]
        result.append((mnemonic, new_ops))
    return result


def _instruction_penalty(a, b):
    """Compute the alignment penalty between two instructions."""
    mnem_a, ops_a = a
    mnem_b, ops_b = b
    if mnem_a != mnem_b:
        return 8
    max_ops = max(len(ops_a), len(ops_b))
    diffs = 0
    for i in range(max_ops):
        oa = ops_a[i] if i < len(ops_a) else None
        ob = ops_b[i] if i < len(ops_b) else None
        if oa != ob:
            diffs += 1
    return 2 * diffs


def _build_cost_matrix(target, candidate, cand_regs):
    """Build the cost matrix for the Hungarian algorithm.

    Uses positional alignment to find register co-occurrences between
    target and candidate instructions, then constructs a cost matrix
    where negative entries indicate beneficial mappings.
    """
    n_cand = len(cand_regs)
    n_all = len(RENAMEABLE_LIST)
    cost = np.zeros((n_cand, n_all), dtype=float)

    min_len = min(len(target), len(candidate))
    for pos in range(min_len):
        _, t_ops = target[pos]
        _, c_ops = candidate[pos]
        max_ops = max(len(t_ops), len(c_ops))
        for oi in range(max_ops):
            t_op = t_ops[oi] if oi < len(t_ops) else ""
            c_op = c_ops[oi] if oi < len(c_ops) else ""
            t_regs = _extract_registers(t_op)
            c_regs = _extract_registers(c_op)
            for tr in t_regs:
                if tr not in RENAMEABLE:
                    continue
                ti = RENAMEABLE_LIST.index(tr)
                for cr in c_regs:
                    if cr in RENAMEABLE and cr in cand_regs:
                        ci = cand_regs.index(cr)
                        cost[ci][ti] -= 1
    return cost


def _needleman_wunsch(target, candidate):
    """Global sequence alignment minimizing total penalty.

    Returns (score, alignment) where alignment is a list of
    (target_instr_or_None, candidate_instr_or_None) pairs.
    """
    m, n = len(target), len(candidate)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        dp[i][0] = i * GAP_PENALTY
    for j in range(1, n + 1):
        dp[0][j] = j * GAP_PENALTY

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            match = dp[i - 1][j - 1] + _instruction_penalty(
                target[i - 1], candidate[j - 1]
            )
            delete = dp[i - 1][j] + GAP_PENALTY
            insert = dp[i][j - 1] + GAP_PENALTY
            dp[i][j] = min(match, delete, insert)

    # Traceback
    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and dp[i][j]
            == dp[i - 1][j - 1]
            + _instruction_penalty(target[i - 1], candidate[j - 1])
        ):
            alignment.append((target[i - 1], candidate[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + GAP_PENALTY:
            alignment.append((target[i - 1], None))
            i -= 1
        else:
            alignment.append((None, candidate[j - 1]))
            j -= 1
    alignment.reverse()
    return dp[m][n], alignment


def score_assembly(target_file, candidate_file):
    """Main scoring function."""
    target = parse_assembly(target_file)
    candidate = parse_assembly(candidate_file)

    cand_regs = _get_renameable_regs(candidate)

    mapping = {}
    if cand_regs:
        cost = _build_cost_matrix(target, candidate, cand_regs)
        row_ind, col_ind = linear_sum_assignment(cost)
        for r, c in zip(row_ind, col_ind):
            cr = cand_regs[r]
            tr = RENAMEABLE_LIST[c]
            if cr != tr:
                mapping[cr] = tr

    mapped_candidate = _apply_mapping(candidate, mapping)
    total_score, _ = _needleman_wunsch(target, mapped_candidate)

    return {
        "score": int(total_score),
        "num_target_instructions": len(target),
        "num_candidate_instructions": len(candidate),
        "register_mapping": mapping,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: python3 asm_scorer.py <target.s> <candidate.s>",
            file=sys.stderr,
        )
        sys.exit(1)

    result = score_assembly(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
