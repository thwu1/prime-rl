#!/usr/bin/env python3
"""TAC IR Optimizer: constant folding, copy/constant propagation,
dead store elimination, and unreachable code elimination."""

import re
import sys
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
from copy import deepcopy

# ---------- 32-bit integer semantics ----------

INT32_MASK = 0xFFFFFFFF
INT32_SIGN = 0x80000000
INT32_MOD = 0x100000000


def to_int32(val: int) -> int:
    val = val & INT32_MASK
    if val >= INT32_SIGN:
        val -= INT32_MOD
    return val


def c_div(a: int, b: int) -> int:
    if b == 0:
        raise RuntimeError("Division by zero")
    q, r = divmod(a, b)
    if r != 0 and (a < 0) != (b < 0):
        q += 1
    return q


def eval_binop(op: str, a: int, b: int) -> int:
    if op == 'add': return to_int32(a + b)
    if op == 'sub': return to_int32(a - b)
    if op == 'mul': return to_int32(a * b)
    if op == 'div': return to_int32(c_div(a, b))
    if op == 'mod':
        if b == 0:
            raise RuntimeError("Division by zero")
        return to_int32(a - c_div(a, b) * b)
    if op == 'eq': return 1 if a == b else 0
    if op == 'ne': return 1 if a != b else 0
    if op == 'lt': return 1 if a < b else 0
    if op == 'le': return 1 if a <= b else 0
    if op == 'gt': return 1 if a > b else 0
    if op == 'ge': return 1 if a >= b else 0
    if op == 'and': return 1 if (a != 0 and b != 0) else 0
    if op == 'or': return 1 if (a != 0 or b != 0) else 0
    if op == 'band': return to_int32(a & b)
    if op == 'bor': return to_int32(a | b)
    if op == 'bxor': return to_int32(a ^ b)
    if op == 'shl': return to_int32(a << (b & 31))
    if op == 'shr': return to_int32(a >> (b & 31))
    raise ValueError(f"Unknown binop: {op}")


def eval_unop(op: str, a: int) -> int:
    if op == 'neg': return to_int32(-a)
    if op == 'not': return 1 if a == 0 else 0
    if op == 'bnot': return to_int32(~a)
    raise ValueError(f"Unknown unop: {op}")


# ---------- IR data structures ----------

class Inst:
    __slots__ = ('kind', 'dest', 'op', 'args', 'label')

    def __init__(self, kind, dest=None, op=None, args=None, label=None):
        self.kind = kind
        self.dest = dest
        self.op = op
        self.args = list(args) if args else []
        self.label = label

    def clone(self):
        return Inst(self.kind, self.dest, self.op, list(self.args), self.label)


class Func:
    def __init__(self, name, params, insts):
        self.name = name
        self.params = list(params)
        self.insts = list(insts)

    def rebuild_label_map(self):
        m = {}
        for i, inst in enumerate(self.insts):
            if inst.label is not None:
                m[inst.label] = i
        return m


def is_const(s: str) -> bool:
    return bool(re.match(r'^-?\d+$', s))


def const_val(s: str) -> int:
    return to_int32(int(s))


# ---------- Parser ----------

def parse_instruction(line: str) -> Optional[Inst]:
    if '#' in line:
        idx = line.index('#')
        depth = 0
        for c in line[:idx]:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
        if depth == 0:
            line = line[:idx].strip()
    if not line:
        return None

    m = re.match(r'return\s+(.+)', line)
    if m:
        return Inst('return', args=[m.group(1).strip()])
    m = re.match(r'jump\s+(\w+)', line)
    if m:
        return Inst('jump', args=[m.group(1)])
    m = re.match(r'jz\s+(\S+)\s+(\w+)', line)
    if m:
        return Inst('jz', args=[m.group(1), m.group(2)])
    m = re.match(r'jnz\s+(\S+)\s+(\w+)', line)
    if m:
        return Inst('jnz', args=[m.group(1), m.group(2)])

    m = re.match(r'(\w+)\s*=\s*(.+)', line)
    if m:
        dest = m.group(1)
        rhs = m.group(2).strip()

        cm = re.match(r'call\s+(\w+)\s*\(([^)]*)\)', rhs)
        if cm:
            func = cm.group(1)
            a_str = cm.group(2).strip()
            args = [a.strip() for a in a_str.split(',') if a.strip()] if a_str else []
            return Inst('call', dest=dest, op=func, args=args)

        bm = re.match(
            r'(add|sub|mul|div|mod|eq|ne|lt|le|gt|ge|band|bor|bxor|shl|shr|and|or)\s+(\S+)\s+(\S+)',
            rhs)
        if bm:
            return Inst('binop', dest=dest, op=bm.group(1), args=[bm.group(2), bm.group(3)])

        um = re.match(r'(neg|not|bnot)\s+(\S+)', rhs)
        if um:
            return Inst('unop', dest=dest, op=um.group(1), args=[um.group(2)])

        cm2 = re.match(r'copy\s+(\S+)', rhs)
        if cm2:
            return Inst('copy', dest=dest, args=[cm2.group(1)])

        if re.match(r'^-?\d+$', rhs):
            return Inst('assign_const', dest=dest, args=[rhs])

        raise ValueError(f"Cannot parse: '{rhs}'")
    raise ValueError(f"Cannot parse line: '{line}'")


def parse_file(text: str) -> List[Func]:
    funcs = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1
            continue
        fm = re.match(r'function\s+(\w+)\s*\(([^)]*)\)\s*:', line)
        if fm:
            name = fm.group(1)
            ps = fm.group(2).strip()
            params = [p.strip() for p in ps.split(',') if p.strip()]
            insts = []
            pending_label = None
            i += 1
            while i < len(lines):
                line = lines[i].strip()
                if not line or line.startswith('#'):
                    i += 1
                    continue
                if re.match(r'function\s+\w+\s*\(', line):
                    break
                lm = re.match(r'^(\w+)\s*:\s*$', line)
                if lm:
                    pending_label = lm.group(1)
                    i += 1
                    continue
                inst = parse_instruction(line)
                if inst is not None:
                    inst.label = pending_label
                    pending_label = None
                    insts.append(inst)
                i += 1
            funcs.append(Func(name, params, insts))
        else:
            i += 1
    return funcs


# ---------- Basic Block / CFG ----------

class BB:
    def __init__(self, idx, label, insts):
        self.idx = idx
        self.label = label
        self.insts = insts  # list of Inst
        self.succs: List[int] = []
        self.preds: List[int] = []


def build_cfg(func: Func) -> List[BB]:
    insts = func.insts
    if not insts:
        return []

    # Identify block start indices
    starts = {0}
    for i, inst in enumerate(insts):
        if inst.label is not None:
            starts.add(i)
        if inst.kind in ('jump', 'return'):
            if i + 1 < len(insts):
                starts.add(i + 1)
        elif inst.kind in ('jz', 'jnz'):
            if i + 1 < len(insts):
                starts.add(i + 1)
    starts = sorted(starts)

    # Build blocks
    blocks = []
    for bi, start in enumerate(starts):
        end = starts[bi + 1] if bi + 1 < len(starts) else len(insts)
        block_insts = insts[start:end]
        label = block_insts[0].label if block_insts else None
        blocks.append(BB(bi, label, block_insts))

    # Build label -> block index map
    label_to_block = {}
    for bi, bb in enumerate(blocks):
        if bb.label is not None:
            label_to_block[bb.label] = bi

    # Build edges
    for bi, bb in enumerate(blocks):
        if not bb.insts:
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)
            continue
        last = bb.insts[-1]
        if last.kind == 'jump':
            target_label = last.args[0]
            if target_label in label_to_block:
                bb.succs.append(label_to_block[target_label])
        elif last.kind in ('jz', 'jnz'):
            target_label = last.args[1]
            if target_label in label_to_block:
                bb.succs.append(label_to_block[target_label])
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)
        elif last.kind == 'return':
            pass  # no successors
        else:
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)

    # Build predecessor lists
    for bi, bb in enumerate(blocks):
        for si in bb.succs:
            blocks[si].preds.append(bi)

    return blocks


def flatten_cfg(blocks: List[BB]) -> List[Inst]:
    result = []
    for bb in blocks:
        for inst in bb.insts:
            result.append(inst)
    return result


# ---------- Get uses / defs ----------

def get_uses(inst: Inst) -> List[str]:
    """Return variable names used by this instruction."""
    uses = []
    if inst.kind == 'assign_const':
        pass
    elif inst.kind == 'copy':
        if not is_const(inst.args[0]):
            uses.append(inst.args[0])
    elif inst.kind == 'binop':
        for a in inst.args:
            if not is_const(a):
                uses.append(a)
    elif inst.kind == 'unop':
        if not is_const(inst.args[0]):
            uses.append(inst.args[0])
    elif inst.kind == 'call':
        for a in inst.args:
            if not is_const(a):
                uses.append(a)
    elif inst.kind == 'return':
        if not is_const(inst.args[0]):
            uses.append(inst.args[0])
    elif inst.kind in ('jz', 'jnz'):
        if not is_const(inst.args[0]):
            uses.append(inst.args[0])
    return uses


def get_def(inst: Inst) -> Optional[str]:
    """Return variable defined by this instruction, if any."""
    if inst.kind in ('assign_const', 'copy', 'binop', 'unop', 'call'):
        return inst.dest
    return None


# ---------- Pass 1: Combined constant folding + copy propagation ----------

def propagate_and_fold_block(insts: List[Inst], initial_env: Dict[str, str]) -> bool:
    """Forward pass: propagate constants/copies and fold constant expressions.
    Returns True if any changes were made.
    env maps variable -> known value (as a string, could be a constant literal or variable).
    """
    changed = False
    env = dict(initial_env)

    for inst in insts:
        # Substitute known values in operands
        if inst.kind in ('copy', 'binop', 'unop', 'call', 'return', 'jz', 'jnz'):
            new_args = []
            for a in inst.args:
                if not is_const(a) and a in env:
                    new_args.append(env[a])
                    if env[a] != a:
                        changed = True
                else:
                    new_args.append(a)
            # For jz/jnz, only substitute the first arg (second is label)
            if inst.kind in ('jz', 'jnz'):
                old_cond = inst.args[0]
                new_cond = new_args[0]
                if new_cond != old_cond:
                    changed = True
                inst.args[0] = new_cond
            else:
                if inst.args != new_args:
                    changed = True
                inst.args = new_args

        # Constant folding
        if inst.kind == 'binop' and is_const(inst.args[0]) and is_const(inst.args[1]):
            a_val = const_val(inst.args[0])
            b_val = const_val(inst.args[1])
            try:
                result = eval_binop(inst.op, a_val, b_val)
                inst.kind = 'assign_const'
                inst.args = [str(result)]
                inst.op = None
                changed = True
            except RuntimeError:
                pass  # division by zero - don't fold

        elif inst.kind == 'unop' and is_const(inst.args[0]):
            a_val = const_val(inst.args[0])
            result = eval_unop(inst.op, a_val)
            inst.kind = 'assign_const'
            inst.args = [str(result)]
            inst.op = None
            changed = True

        elif inst.kind == 'copy' and is_const(inst.args[0]):
            inst.kind = 'assign_const'
            changed = True

        # Update environment
        if inst.kind == 'assign_const':
            env[inst.dest] = inst.args[0]
        elif inst.kind == 'copy':
            src = inst.args[0]
            # Transitively resolve
            if src in env:
                env[inst.dest] = env[src]
            else:
                env[inst.dest] = src
        elif inst.dest is not None:
            # Non-copy/const assignment: invalidate
            if inst.dest in env:
                del env[inst.dest]

    return changed


def propagate_and_fold(blocks: List[BB]) -> bool:
    """Run combined constant/copy propagation + constant folding on all blocks."""
    changed = False
    for bb in blocks:
        if not bb.insts:
            continue
        # Conservative: start with empty env at each block
        # (cross-block propagation handled by iteration + single-predecessor optimization)
        initial_env: Dict[str, str] = {}

        # Single-predecessor optimization: if this block has exactly one predecessor
        # and that predecessor ends with a jump (not conditional), we can inherit its env
        # Actually, this is complex to get right across iterations, so keep it conservative.

        if propagate_and_fold_block(bb.insts, initial_env):
            changed = True
    return changed


# ---------- Pass 2: Resolve constant conditional branches ----------

def resolve_branches(blocks: List[BB]) -> bool:
    """Convert jz/jnz with constant conditions to jump or remove."""
    changed = False
    for bb in blocks:
        if not bb.insts:
            continue
        last = bb.insts[-1]
        if last.kind == 'jz' and is_const(last.args[0]):
            val = const_val(last.args[0])
            if val == 0:
                # Always jump
                last.kind = 'jump'
                last.args = [last.args[1]]
                changed = True
            else:
                # Never jump - remove the jz (fall through)
                bb.insts.remove(last)
                changed = True
        elif last.kind == 'jnz' and is_const(last.args[0]):
            val = const_val(last.args[0])
            if val != 0:
                # Always jump
                last.kind = 'jump'
                last.args = [last.args[1]]
                changed = True
            else:
                # Never jump - remove the jnz
                bb.insts.remove(last)
                changed = True
    return changed


# ---------- Pass 3: Unreachable code elimination ----------

def eliminate_unreachable(blocks: List[BB]) -> bool:
    """Remove blocks not reachable from entry (block 0). Rebuild edges."""
    if not blocks:
        return False

    # Rebuild edges first (they may be stale after branch resolution)
    label_to_block = {}
    for bi, bb in enumerate(blocks):
        if bb.label is not None:
            label_to_block[bb.label] = bi

    for bb in blocks:
        bb.succs = []
        bb.preds = []

    for bi, bb in enumerate(blocks):
        if not bb.insts:
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)
            continue
        last = bb.insts[-1]
        if last.kind == 'jump':
            tgt = last.args[0]
            if tgt in label_to_block:
                bb.succs.append(label_to_block[tgt])
        elif last.kind in ('jz', 'jnz'):
            tgt = last.args[1]
            if tgt in label_to_block:
                bb.succs.append(label_to_block[tgt])
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)
        elif last.kind == 'return':
            pass
        else:
            if bi + 1 < len(blocks):
                bb.succs.append(bi + 1)

    for bi, bb in enumerate(blocks):
        for si in bb.succs:
            if si < len(blocks):
                blocks[si].preds.append(bi)

    # BFS from entry
    reachable = set()
    queue = [0]
    while queue:
        bi = queue.pop()
        if bi in reachable:
            continue
        reachable.add(bi)
        for si in blocks[bi].succs:
            if si not in reachable:
                queue.append(si)

    if len(reachable) == len(blocks):
        return False

    # Remove unreachable blocks
    new_blocks = [blocks[i] for i in sorted(reachable)]
    blocks.clear()
    blocks.extend(new_blocks)
    # Re-index
    for bi, bb in enumerate(blocks):
        bb.idx = bi
    return True


# ---------- Pass 4: Dead store elimination ----------

def compute_liveness(blocks: List[BB]) -> List[Tuple[Set[str], Set[str]]]:
    """Iterative backward liveness analysis.
    Returns (live_in, live_out) for each block.
    """
    n = len(blocks)

    # Rebuild successors
    label_to_block = {}
    for bi, bb in enumerate(blocks):
        if bb.label is not None:
            label_to_block[bb.label] = bi

    for bb in blocks:
        bb.succs = []
        bb.preds = []

    for bi, bb in enumerate(blocks):
        if not bb.insts:
            if bi + 1 < n:
                bb.succs.append(bi + 1)
            continue
        last = bb.insts[-1]
        if last.kind == 'jump':
            tgt = last.args[0]
            if tgt in label_to_block:
                bb.succs.append(label_to_block[tgt])
        elif last.kind in ('jz', 'jnz'):
            tgt = last.args[1]
            if tgt in label_to_block:
                bb.succs.append(label_to_block[tgt])
            if bi + 1 < n:
                bb.succs.append(bi + 1)
        elif last.kind == 'return':
            pass
        else:
            if bi + 1 < n:
                bb.succs.append(bi + 1)

    for bi, bb in enumerate(blocks):
        for si in bb.succs:
            blocks[si].preds.append(bi)

    # Compute gen/kill for each block
    gen_sets: List[Set[str]] = []
    kill_sets: List[Set[str]] = []
    for bb in blocks:
        gen = set()
        kill = set()
        # Process instructions in reverse order
        for inst in reversed(bb.insts):
            d = get_def(inst)
            if d is not None:
                gen.discard(d)
                kill.add(d)
            for u in get_uses(inst):
                gen.add(u)
        gen_sets.append(gen)
        kill_sets.append(kill)

    # Iterative fixed point
    live_in: List[Set[str]] = [set() for _ in range(n)]
    live_out: List[Set[str]] = [set() for _ in range(n)]

    changed = True
    while changed:
        changed = False
        for bi in reversed(range(n)):
            # live_out = union of live_in of successors
            new_out: Set[str] = set()
            for si in blocks[bi].succs:
                new_out |= live_in[si]
            if new_out != live_out[bi]:
                live_out[bi] = new_out
                changed = True
            # live_in = gen ∪ (live_out - kill)
            new_in = gen_sets[bi] | (live_out[bi] - kill_sets[bi])
            if new_in != live_in[bi]:
                live_in[bi] = new_in
                changed = True

    return list(zip(live_in, live_out))


def eliminate_dead_stores(blocks: List[BB]) -> bool:
    """Remove assignments to variables that are not live after the assignment.
    Never remove function calls (potential side effects).
    """
    liveness = compute_liveness(blocks)
    changed = False

    for bi, bb in enumerate(blocks):
        _, lo = liveness[bi]
        # Walk backward through block, tracking live set
        live = set(lo)
        new_insts = []
        pending_label = None  # label from a removed instruction to preserve
        for inst in reversed(bb.insts):
            d = get_def(inst)
            if d is not None and d not in live and inst.kind != 'call':
                # Dead store - remove, but preserve its label
                if inst.label is not None:
                    pending_label = inst.label
                changed = True
                continue
            # Transfer any preserved label from a removed instruction
            if pending_label is not None:
                if inst.label is None:
                    inst.label = pending_label
                pending_label = None
            new_insts.append(inst)
            # Update live set
            if d is not None:
                live.discard(d)
            for u in get_uses(inst):
                live.add(u)
        bb.insts = list(reversed(new_insts))
        # If a label was on the first instruction and all instructions were removed,
        # update the block's label
        if pending_label is not None and bb.insts:
            bb.insts[0].label = pending_label
            bb.label = pending_label

    return changed


# ---------- Pass 5: Remove redundant jumps ----------

def simplify_jumps(blocks: List[BB]) -> bool:
    """Remove jump instructions that target the immediately following block."""
    changed = False
    for bi, bb in enumerate(blocks):
        if not bb.insts:
            continue
        last = bb.insts[-1]
        if last.kind == 'jump' and bi + 1 < len(blocks):
            next_bb = blocks[bi + 1]
            if next_bb.label == last.args[0]:
                bb.insts.pop()
                changed = True
    return changed


# ---------- Main optimization loop ----------

def optimize_func(func: Func) -> Func:
    func = Func(func.name, func.params, [inst.clone() for inst in func.insts])
    max_iters = 100
    for _ in range(max_iters):
        blocks = build_cfg(func)
        if not blocks:
            break
        c1 = propagate_and_fold(blocks)
        c2 = resolve_branches(blocks)
        c3 = eliminate_unreachable(blocks)
        c4 = eliminate_dead_stores(blocks)
        c5 = simplify_jumps(blocks)
        func.insts = flatten_cfg(blocks)
        if not (c1 or c2 or c3 or c4 or c5):
            break
    return func


# ---------- Serializer ----------

def serialize_inst(inst: Inst) -> str:
    if inst.kind == 'assign_const':
        return f"    {inst.dest} = {inst.args[0]}"
    elif inst.kind == 'copy':
        return f"    {inst.dest} = copy {inst.args[0]}"
    elif inst.kind == 'binop':
        return f"    {inst.dest} = {inst.op} {inst.args[0]} {inst.args[1]}"
    elif inst.kind == 'unop':
        return f"    {inst.dest} = {inst.op} {inst.args[0]}"
    elif inst.kind == 'call':
        args_str = ", ".join(inst.args)
        return f"    {inst.dest} = call {inst.op}({args_str})"
    elif inst.kind == 'return':
        return f"    return {inst.args[0]}"
    elif inst.kind == 'jump':
        return f"    jump {inst.args[0]}"
    elif inst.kind == 'jz':
        return f"    jz {inst.args[0]} {inst.args[1]}"
    elif inst.kind == 'jnz':
        return f"    jnz {inst.args[0]} {inst.args[1]}"
    else:
        raise ValueError(f"Unknown kind: {inst.kind}")


def serialize(funcs: List[Func]) -> str:
    lines = []
    for fi, func in enumerate(funcs):
        params_str = ", ".join(func.params)
        lines.append(f"function {func.name}({params_str}):")
        for inst in func.insts:
            if inst.label is not None:
                lines.append(f"  {inst.label}:")
            lines.append(serialize_inst(inst))
        if fi < len(funcs) - 1:
            lines.append("")
    return "\n".join(lines) + "\n"


# ---------- Entry point ----------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 optimizer.py <file.tac>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        text = f.read()

    funcs = parse_file(text)
    optimized = [optimize_func(f) for f in funcs]
    print(serialize(optimized), end='')


if __name__ == '__main__':
    main()
