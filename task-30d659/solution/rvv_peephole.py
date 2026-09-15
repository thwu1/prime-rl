#!/usr/bin/env python3
"""
RISC-V Vector (RVV) Assembly Peephole Optimizer

Implements two optimization passes:
1. Redundant vsetvli elimination within basic blocks
2. Vector-scalar broadcast fusion (vmv.v.x/vfmv.v.f + .vv -> .vx/.vf)
"""

import sys
import re
import json
import argparse

# ---------------------------------------------------------------------------
# Instruction classification tables
# ---------------------------------------------------------------------------

# Float .vv -> .vf fusable pairs
FLOAT_VV_TO_VF = {
    'vfadd.vv': 'vfadd.vf', 'vfsub.vv': 'vfsub.vf',
    'vfmul.vv': 'vfmul.vf',
    'vfmadd.vv': 'vfmadd.vf', 'vfnmadd.vv': 'vfnmadd.vf',
    'vfmsub.vv': 'vfmsub.vf', 'vfnmsub.vv': 'vfnmsub.vf',
    'vfmacc.vv': 'vfmacc.vf', 'vfnmacc.vv': 'vfnmacc.vf',
    'vfmsac.vv': 'vfmsac.vf', 'vfnmsac.vv': 'vfnmsac.vf',
}

# Integer .vv -> .vx fusable pairs
INT_VV_TO_VX = {
    'vadd.vv': 'vadd.vx', 'vsub.vv': 'vsub.vx',
    'vand.vv': 'vand.vx', 'vor.vv': 'vor.vx', 'vxor.vv': 'vxor.vx',
    'vmul.vv': 'vmul.vx',
    'vmadd.vv': 'vmadd.vx', 'vnmsub.vv': 'vnmsub.vx',
    'vmacc.vv': 'vmacc.vx', 'vnmsac.vv': 'vnmsac.vx',
}

# FMA-style ops: layout is "vd, vs1, vs2" (scalar replaces vs1 at operand index 1)
# Non-FMA arithmetic: layout is "vd, vs2, vs1" (scalar replaces vs1 at operand index 2)
FMA_OPS = {
    'vfmadd.vv', 'vfnmadd.vv', 'vfmsub.vv', 'vfnmsub.vv',
    'vfmacc.vv', 'vfnmacc.vv', 'vfmsac.vv', 'vfnmsac.vv',
    'vmadd.vv', 'vnmsub.vv', 'vmacc.vv', 'vnmsac.vv',
}

# Commutative ops: broadcast register can be in either source position
COMMUTATIVE = {
    'vadd.vv', 'vand.vv', 'vor.vv', 'vxor.vv', 'vmul.vv',
    'vfadd.vv', 'vfmul.vv',
}

BRANCHES = {
    'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu',
    'beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz',
    'j', 'jal', 'jalr', 'jr', 'call', 'tail', 'ret',
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VREG_RE = re.compile(r'^v\d+$')


def is_vreg(s):
    return bool(_VREG_RE.match(s))


def is_vec_store(insn):
    """Detect vector store mnemonics (vse, vsse, vsoxei, vsuxei)."""
    if not insn:
        return False
    return bool(re.match(r'v(se|sse|soxei|suxei)\d+\.v', insn))


def scalar_pos(insn):
    """Operand index where the scalar register goes in the .vf/.vx form."""
    return 1 if insn in FMA_OPS else 2


def vec_reads(insn, ops):
    """Return the set of vector registers read by this instruction."""
    if not insn:
        return set()
    vops = [op for op in ops if is_vreg(op)]
    if is_vec_store(insn):
        return set(vops)
    if insn in FMA_OPS:
        return set(vops)            # vd is both read and written in FMA
    if insn in ('vmv.v.x', 'vfmv.v.f'):
        return set()                # reads scalar, not vector
    if insn == 'vmv.v.v':
        return set(vops[1:])
    # Default: first vector operand is destination, rest are sources
    return set(vops[1:]) if len(vops) > 1 else set()


def vec_dest(insn, ops):
    """Return the destination vector register, or None."""
    if not insn or is_vec_store(insn):
        return None
    vops = [op for op in ops if is_vreg(op)]
    return vops[0] if vops else None

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(text):
    """Parse assembly text into a list of structured line records."""
    lines = []
    for raw in text.split('\n'):
        line = raw
        comment = None
        ci = line.find('#')
        if ci >= 0:
            comment = line[ci:]
            line = line[:ci]
        sline = line.strip()

        label = None
        m = re.match(r'^(\.?\w+)\s*:\s*(.*)', sline)
        if m:
            label = m.group(1)
            sline = m.group(2).strip()

        insn = None
        ops = []
        is_dir = False

        if sline:
            if sline.startswith('.'):
                is_dir = True
                insn = sline
            else:
                parts = sline.split(None, 1)
                insn = parts[0]
                if len(parts) > 1:
                    ops = [o.strip() for o in parts[1].split(',')]

        indent = raw[:len(raw) - len(raw.lstrip())]
        lines.append({
            'raw': raw,
            'label': label,
            'insn': insn,
            'ops': ops,
            'comment': comment,
            'is_dir': is_dir,
            'indent': indent,
        })
    return lines

# ---------------------------------------------------------------------------
# Line reconstruction
# ---------------------------------------------------------------------------

def rebuild(ln, new_insn, new_ops):
    """Rebuild a line with new instruction/operands, preserving indentation."""
    s = ln['indent']
    if ln['label']:
        s = ln['label'] + ': '
    s += new_insn
    if new_ops:
        s += ' ' + ', '.join(new_ops)
    if ln['comment']:
        s += '    ' + ln['comment']
    return s

# ---------------------------------------------------------------------------
# Optimization engine
# ---------------------------------------------------------------------------

def optimize(text):
    lines = parse(text)
    stats = {
        'redundant_vsetvli_removed': 0,
        'fusions_applied': 0,
        'broadcast_instructions_removed': 0,
    }
    remove = set()
    modify = {}   # line_index -> (new_insn, new_ops)

    all_fusable = {**FLOAT_VV_TO_VF, **INT_VV_TO_VX}

    # ---- Pass 1: redundant vsetvli elimination ----
    cur_cfg = None
    for i, ln in enumerate(lines):
        if ln['label']:
            cur_cfg = None
        insn = ln['insn']
        if insn == 'vsetvli':
            cfg = tuple(ln['ops'])
            if cur_cfg == cfg:
                remove.add(i)
                stats['redundant_vsetvli_removed'] += 1
            else:
                cur_cfg = cfg
        elif insn in BRANCHES:
            cur_cfg = None

    # ---- Pass 2: vector-scalar broadcast fusion ----
    for i, ln in enumerate(lines):
        if i in remove:
            continue
        insn = ln['insn']
        if insn not in ('vmv.v.x', 'vfmv.v.f'):
            continue

        is_float = (insn == 'vfmv.v.f')
        vdst = ln['ops'][0]          # broadcast destination vector register
        sreg = ln['ops'][1]          # original scalar register
        fmap = FLOAT_VV_TO_VF if is_float else INT_VV_TO_VX

        # Scan forward to find all uses of vdst
        uses = []       # list of (line_idx, new_insn, new_ops)
        can_rm = False

        for j in range(i + 1, len(lines)):
            if j in remove:
                continue
            jl = lines[j]

            # Labels are basic-block boundaries (potential branch targets)
            if jl['label']:
                can_rm = False
                break

            jinsn = jl['insn']
            if not jinsn or jl['is_dir']:
                continue

            # Branches / calls end the basic block
            if jinsn in BRANCHES:
                can_rm = (jinsn == 'ret')   # at ret, all vector regs are dead
                break

            reads = vec_reads(jinsn, jl['ops'])

            if vdst in reads:
                # Check whether this use is fusable
                if jinsn in fmap:
                    sp = scalar_pos(jinsn)
                    if jl['ops'][sp] == vdst:
                        # Direct match: broadcast reg in the canonical scalar position
                        new_ops = list(jl['ops'])
                        new_ops[sp] = sreg
                        uses.append((j, fmap[jinsn], new_ops))
                    elif jinsn in COMMUTATIVE:
                        # For commutative ops, the broadcast may be in the other source
                        oth = 1 if sp == 2 else 2
                        if len(jl['ops']) > oth and jl['ops'][oth] == vdst:
                            new_ops = list(jl['ops'])
                            new_ops[oth], new_ops[sp] = new_ops[sp], new_ops[oth]
                            new_ops[sp] = sreg
                            uses.append((j, fmap[jinsn], new_ops))
                        else:
                            can_rm = False
                            uses = []
                            break
                    else:
                        # Non-fusable use (e.g. wrong position in non-commutative op)
                        can_rm = False
                        uses = []
                        break
                else:
                    # Used in a non-fusable instruction (store, etc.)
                    can_rm = False
                    uses = []
                    break

            # Check whether vdst is overwritten (killed) without being read
            d = vec_dest(jinsn, jl['ops'])
            if d == vdst and vdst not in reads:
                can_rm = True
                break
        else:
            # Reached end of lines without hitting a branch or label
            can_rm = bool(uses)

        if can_rm and uses:
            for j, ni, no in uses:
                modify[j] = (ni, no)
                stats['fusions_applied'] += 1
            remove.add(i)
            stats['broadcast_instructions_removed'] += 1

    # ---- Emit output ----
    out = []
    for i, ln in enumerate(lines):
        if i in remove:
            continue
        if i in modify:
            ni, no = modify[i]
            out.append(rebuild(ln, ni, no))
        else:
            out.append(ln['raw'])
    return '\n'.join(out), stats

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='RVV Assembly Peephole Optimizer')
    ap.add_argument('input', help='Input assembly file')
    ap.add_argument('--stats', action='store_true',
                    help='Output JSON statistics instead of optimized assembly')
    args = ap.parse_args()

    with open(args.input) as f:
        text = f.read()

    output, stats = optimize(text)

    if args.stats:
        print(json.dumps(stats, indent=2))
    else:
        print(output)


if __name__ == '__main__':
    main()
