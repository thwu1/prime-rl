#!/usr/bin/env python3

"""
Assembly function match scorer.
Compares two x86-64 ELF relocatable object files by disassembling them,
finding the optimal register renaming, and computing an alignment score.
"""

import subprocess
import sys
import json
import re
from itertools import permutations

# ---------------------------------------------------------------------------
# x86-64 register families
# ---------------------------------------------------------------------------

REGISTER_FAMILIES = {
    'rax': ['rax', 'eax', 'ax', 'al', 'ah'],
    'rbx': ['rbx', 'ebx', 'bx', 'bl', 'bh'],
    'rcx': ['rcx', 'ecx', 'cx', 'cl', 'ch'],
    'rdx': ['rdx', 'edx', 'dx', 'dl', 'dh'],
    'rsi': ['rsi', 'esi', 'si', 'sil'],
    'rdi': ['rdi', 'edi', 'di', 'dil'],
    'rbp': ['rbp', 'ebp', 'bp', 'bpl'],
    'rsp': ['rsp', 'esp', 'sp', 'spl'],
    'r8':  ['r8',  'r8d',  'r8w',  'r8b'],
    'r9':  ['r9',  'r9d',  'r9w',  'r9b'],
    'r10': ['r10', 'r10d', 'r10w', 'r10b'],
    'r11': ['r11', 'r11d', 'r11w', 'r11b'],
    'r12': ['r12', 'r12d', 'r12w', 'r12b'],
    'r13': ['r13', 'r13d', 'r13w', 'r13b'],
    'r14': ['r14', 'r14d', 'r14w', 'r14b'],
    'r15': ['r15', 'r15d', 'r15w', 'r15b'],
}

REG_TO_FAMILY = {}
for _fam_key, _members in REGISTER_FAMILIES.items():
    for _m in _members:
        REG_TO_FAMILY[_m] = _fam_key

# Instruction mnemonic aliases (same opcode, different name)
MNEMONIC_ALIASES = {
    'jz': 'je', 'jnz': 'jne',
    'jc': 'jb', 'jnc': 'jnb', 'jnae': 'jb', 'jae': 'jnb',
    'jna': 'jbe', 'ja': 'jnbe',
    'jpe': 'jp', 'jpo': 'jnp',
    'jnge': 'jl', 'jge': 'jnl',
    'jng': 'jle', 'jg': 'jnle',
    'setz': 'sete', 'setnz': 'setne',
    'setc': 'setb', 'setnc': 'setnb',
    'cmovz': 'cmove', 'cmovnz': 'cmovne',
    'retq': 'ret', 'pushq': 'push', 'popq': 'pop',
    'movabs': 'movabs',
}

# Scoring constants
GAP_PENALTY = 10
MNEMONIC_MISMATCH_PENALTY = 8
OPERAND_DIFF_PENALTY = 2


def normalize_mnemonic(mnemonic):
    """Normalize instruction mnemonic via alias table."""
    return MNEMONIC_ALIASES.get(mnemonic, mnemonic)


def disassemble(obj_path):
    """Disassemble an ELF object file and return a list of (mnemonic, operands)."""
    result = subprocess.run(
        ['objdump', '-d', '--no-show-raw-insn', obj_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"objdump failed on {obj_path}: {result.stderr}")

    instructions = []
    func_label_pat = re.compile(r'^[0-9a-f]+ <(.+)>:\s*$')
    in_function = False

    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue

        if func_label_pat.match(line):
            in_function = True
            continue

        if not in_function:
            continue

        # Instruction line: "   addr:   mnemonic  operands"
        m = re.match(r'\s+[0-9a-f]+:\s+(.*)', line)
        if not m:
            continue

        insn_text = m.group(1).strip()
        if not insn_text:
            continue

        parts = insn_text.split(None, 1)
        mnemonic = normalize_mnemonic(parts[0])
        operands = ''
        if len(parts) > 1:
            operands = parts[1].strip()
            # Remove trailing comments like "# 0x1234 <func>"
            operands = re.sub(r'\s*#.*$', '', operands).strip()

        instructions.append((mnemonic, operands))

    return instructions


def extract_families(instructions):
    """Extract all register family keys used across all instruction operands."""
    families = set()
    for _, operands in instructions:
        for m in re.finditer(r'%(\w+)', operands):
            reg = m.group(1)
            if reg in REG_TO_FAMILY:
                families.add(REG_TO_FAMILY[reg])
    return families


def apply_mapping(instructions, mapping):
    """Apply a register family mapping to all instructions.

    Uses re.sub with a callback for simultaneous substitution,
    which correctly handles cyclic mappings (e.g., ebx->ecx->edx->ebx).
    """
    result = []
    for mnemonic, operands in instructions:
        def replace_reg(match, _mapping=mapping):
            reg = match.group(1)
            if reg not in REG_TO_FAMILY:
                return match.group(0)
            src_fam = REG_TO_FAMILY[reg]
            dst_fam = _mapping.get(src_fam, src_fam)
            if src_fam == dst_fam:
                return match.group(0)
            src_members = REGISTER_FAMILIES[src_fam]
            dst_members = REGISTER_FAMILIES[dst_fam]
            try:
                idx = src_members.index(reg)
            except ValueError:
                return match.group(0)
            if idx < len(dst_members):
                return '%' + dst_members[idx]
            return match.group(0)

        new_operands = re.sub(r'%(\w+)', replace_reg, operands)
        result.append((mnemonic, new_operands))
    return result


def instruction_cost(a, b):
    """Compute the mismatch cost between two instructions."""
    cost = 0
    if a[0] != b[0]:
        cost += MNEMONIC_MISMATCH_PENALTY

    ops_a = [x.strip() for x in a[1].split(',') if x.strip()] if a[1] else []
    ops_b = [x.strip() for x in b[1].split(',') if x.strip()] if b[1] else []
    n = max(len(ops_a), len(ops_b))
    for i in range(n):
        oa = ops_a[i] if i < len(ops_a) else ''
        ob = ops_b[i] if i < len(ops_b) else ''
        if oa != ob:
            cost += OPERAND_DIFF_PENALTY
    return cost


def needleman_wunsch(seq_a, seq_b):
    """Needleman-Wunsch global sequence alignment. Returns alignment cost."""
    n = len(seq_a)
    m = len(seq_b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = i * GAP_PENALTY
    for j in range(1, m + 1):
        dp[0][j] = j * GAP_PENALTY

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match_cost = dp[i - 1][j - 1] + instruction_cost(seq_a[i - 1], seq_b[j - 1])
            delete_cost = dp[i - 1][j] + GAP_PENALTY
            insert_cost = dp[i][j - 1] + GAP_PENALTY
            dp[i][j] = min(match_cost, delete_cost, insert_cost)

    return dp[n][m]


def find_optimal_mapping(target_insns, candidate_insns):
    """Find the register mapping that minimizes the alignment score.

    Uses brute-force permutation search over the union of register families
    used in both sequences. Caps at 8 families (8! = 40320 permutations).
    """
    target_fams = extract_families(target_insns)
    candidate_fams = extract_families(candidate_insns)
    all_fams = sorted(target_fams | candidate_fams)

    if len(all_fams) == 0:
        return needleman_wunsch(target_insns, candidate_insns), {}

    if len(all_fams) > 8:
        # Too many families for brute force; use identity mapping
        score = needleman_wunsch(target_insns, candidate_insns)
        return score, {f: f for f in all_fams}

    best_score = float('inf')
    best_mapping = {}

    for perm in permutations(all_fams):
        mapping = dict(zip(all_fams, perm))
        mapped = apply_mapping(candidate_insns, mapping)
        score = needleman_wunsch(target_insns, mapped)
        if score < best_score:
            best_score = score
            best_mapping = mapping

    return best_score, best_mapping


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <target.o> <candidate.o>", file=sys.stderr)
        sys.exit(1)

    target_path = sys.argv[1]
    candidate_path = sys.argv[2]

    target_insns = disassemble(target_path)
    candidate_insns = disassemble(candidate_path)

    score, mapping = find_optimal_mapping(target_insns, candidate_insns)

    reg_mapping = {}
    for src, dst in sorted(mapping.items()):
        if src != dst:
            reg_mapping[f'%{src}'] = f'%{dst}'

    output = {
        'score': score,
        'num_target': len(target_insns),
        'num_candidate': len(candidate_insns),
        'register_mapping': reg_mapping,
    }

    json.dump(output, sys.stdout)
    print()


if __name__ == '__main__':
    main()
