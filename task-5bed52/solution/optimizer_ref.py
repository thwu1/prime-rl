#!/usr/bin/env python3
"""
Reference solution: complete dataflow analysis and optimization framework for TAC IR.
"""

import json
import os
import sys
import re
from collections import defaultdict, OrderedDict
from copy import deepcopy

# ============================================================
# TAC Parser
# ============================================================

class Instruction:
    def __init__(self, kind, dst=None, src1=None, op=None, src2=None, label=None, func=None, nargs=None):
        self.kind = kind  # 'assign_const','assign_copy','assign_binop','assign_unop','if','goto','param','call','return','nop','func','endfunc'
        self.dst = dst
        self.src1 = src1
        self.op = op
        self.src2 = src2
        self.label = label  # for jumps
        self.func = func    # for call
        self.nargs = nargs  # for call

    def defs(self):
        if self.dst:
            return {self.dst}
        return set()

    def uses(self):
        u = set()
        if self.kind == 'assign_copy':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
        elif self.kind == 'assign_binop':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
            if self.src2 and not _is_const(self.src2):
                u.add(self.src2)
        elif self.kind == 'assign_unop':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
        elif self.kind == 'if':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
        elif self.kind == 'param':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
        elif self.kind == 'return':
            if self.src1 and not _is_const(self.src1):
                u.add(self.src1)
        elif self.kind == 'call':
            pass  # params handled via PARAM instructions
        return u

    def __repr__(self):
        return f"Instr({self.kind}, dst={self.dst}, src1={self.src1}, op={self.op}, src2={self.src2}, label={self.label})"

    def to_tac(self):
        if self.kind == 'assign_const':
            return f"  {self.dst} = {self.src1}"
        elif self.kind == 'assign_copy':
            return f"  {self.dst} = {self.src1}"
        elif self.kind == 'assign_binop':
            return f"  {self.dst} = {self.src1} {self.op} {self.src2}"
        elif self.kind == 'assign_unop':
            return f"  {self.dst} = {self.op} {self.src1}"
        elif self.kind == 'if':
            return f"  IF {self.src1} GOTO {self.label}"
        elif self.kind == 'goto':
            return f"  GOTO {self.label}"
        elif self.kind == 'param':
            return f"  PARAM {self.src1}"
        elif self.kind == 'call':
            return f"  {self.dst} = CALL {self.func} {self.nargs}"
        elif self.kind == 'return':
            return f"  RETURN {self.src1}"
        elif self.kind == 'nop':
            return f"  NOP"
        return ""


def _is_const(s):
    if s is None:
        return False
    try:
        int(s)
        return True
    except ValueError:
        return False


def _const_val(s):
    return int(s)


BINOPS = {'+', '-', '*', '/', '%', '==', '!=', '<', '>', '<=', '>=', '&&', '||'}
UNOPS = {'-', '!'}


def parse_tac(text):
    """Parse TAC text into list of (func_name, [(block_label, [Instruction])]) tuples."""
    functions = []
    lines = text.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m = re.match(r'^FUNC\s+(\w+)\s*:', line)
        if m:
            fname = m.group(1)
            i += 1
            blocks = []
            current_label = None
            current_instrs = []
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue
                if line == 'ENDFUNC':
                    if current_label is not None:
                        blocks.append((current_label, current_instrs))
                    functions.append((fname, blocks))
                    i += 1
                    break
                # Check if label
                lm = re.match(r'^(\w+)\s*:', line)
                if lm:
                    if current_label is not None:
                        blocks.append((current_label, current_instrs))
                    current_label = lm.group(1)
                    current_instrs = []
                    i += 1
                    continue
                # Parse instruction
                instr = parse_instruction(line)
                if instr:
                    current_instrs.append(instr)
                i += 1
        else:
            i += 1
    return functions


def parse_instruction(line):
    line = line.strip()
    if line == 'NOP':
        return Instruction('nop')

    # RETURN x
    m = re.match(r'^RETURN\s+(.+)$', line)
    if m:
        return Instruction('return', src1=m.group(1).strip())

    # PARAM x
    m = re.match(r'^PARAM\s+(.+)$', line)
    if m:
        return Instruction('param', src1=m.group(1).strip())

    # IF x GOTO label
    m = re.match(r'^IF\s+(\S+)\s+GOTO\s+(\w+)$', line)
    if m:
        return Instruction('if', src1=m.group(1), label=m.group(2))

    # GOTO label
    m = re.match(r'^GOTO\s+(\w+)$', line)
    if m:
        return Instruction('goto', label=m.group(1))

    # x = CALL f n
    m = re.match(r'^(\w+)\s*=\s*CALL\s+(\w+)\s+(\d+)$', line)
    if m:
        return Instruction('call', dst=m.group(1), func=m.group(2), nargs=int(m.group(3)))

    # x = unop y  (only prefix - or !)
    m = re.match(r'^(\w+)\s*=\s*([!\-])\s*(\w+)$', line)
    if m:
        # Disambiguate: "x = - y" is unary, but "x = y - z" is binary
        # This pattern only matches unary (no space issues since we stripped)
        # Actually let's be more careful - try binary first
        pass

    # x = y op z (binary)
    # Need to handle multi-char ops like <=, >=, ==, !=, &&, ||
    m = re.match(r'^(\w+)\s*=\s*(\S+)\s+([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s+(\S+)$', line)
    if m:
        return Instruction('assign_binop', dst=m.group(1), src1=m.group(2), op=m.group(3), src2=m.group(4))

    # x = unop y
    m = re.match(r'^(\w+)\s*=\s*([!\-])\s+(\S+)$', line)
    if m:
        return Instruction('assign_unop', dst=m.group(1), op=m.group(2), src1=m.group(3))

    # x = y (copy or const)
    m = re.match(r'^(\w+)\s*=\s*(\S+)$', line)
    if m:
        val = m.group(2)
        if _is_const(val):
            return Instruction('assign_const', dst=m.group(1), src1=val)
        else:
            return Instruction('assign_copy', dst=m.group(1), src1=val)

    return None


# ============================================================
# CFG Construction
# ============================================================

def build_cfg(blocks):
    """Build CFG adjacency from list of (label, instrs).
    Returns dict: label -> [successor labels]
    """
    label_list = [b[0] for b in blocks]
    cfg = OrderedDict()
    for idx, (label, instrs) in enumerate(blocks):
        succs = []
        has_jump = False
        for instr in instrs:
            if instr.kind == 'goto':
                succs.append(instr.label)
                has_jump = True
            elif instr.kind == 'if':
                succs.append(instr.label)
                # fallthrough
                if idx + 1 < len(blocks):
                    ft = label_list[idx + 1]
                    if ft not in succs:
                        succs.append(ft)
                has_jump = True
            elif instr.kind == 'return':
                has_jump = True
        if not has_jump and idx + 1 < len(blocks):
            succs.append(label_list[idx + 1])
        cfg[label] = succs
    return cfg


def build_pred(cfg):
    pred = defaultdict(list)
    for b, succs in cfg.items():
        for s in succs:
            if b not in pred[s]:
                pred[s].append(b)
    # ensure all blocks present
    for b in cfg:
        if b not in pred:
            pred[b] = []
    return pred


# ============================================================
# Dataflow Analyses
# ============================================================

def liveness_analysis(blocks, cfg):
    """Backward dataflow: live variables.
    Returns live_in, live_out dicts: block_label -> set of variable names.
    """
    pred = build_pred(cfg)
    # Compute gen/kill per block
    gen = {}
    kill = {}
    for label, instrs in blocks:
        g = set()
        k = set()
        # Process instructions in reverse for gen/kill
        for instr in reversed(instrs):
            d = instr.defs()
            u = instr.uses()
            g = (g - d) | u
            k = k | d
        gen[label] = g
        kill[label] = k

    live_in = {b: set() for b, _ in blocks}
    live_out = {b: set() for b, _ in blocks}

    changed = True
    while changed:
        changed = False
        for label, _ in reversed(blocks):
            old_in = live_in[label].copy()
            # live_out = union of live_in of successors
            new_out = set()
            for s in cfg.get(label, []):
                new_out |= live_in[s]
            live_out[label] = new_out
            # live_in = gen ∪ (live_out - kill)
            new_in = gen[label] | (live_out[label] - kill[label])
            live_in[label] = new_in
            if new_in != old_in:
                changed = True

    return live_in, live_out


def reaching_definitions(blocks, cfg):
    """Forward dataflow: reaching definitions.
    A definition is (var, block_label, index_in_block).
    Returns reach_in, reach_out: block_label -> set of (var, block_label, index).
    """
    pred = build_pred(cfg)
    # Collect all definitions
    gen = {}
    kill = {}
    all_defs = set()
    # Map var -> set of all defs of that var
    var_defs = defaultdict(set)
    for label, instrs in blocks:
        for idx, instr in enumerate(instrs):
            for v in instr.defs():
                d = (v, label, idx)
                all_defs.add(d)
                var_defs[v].add(d)

    for label, instrs in blocks:
        g = set()
        k = set()
        for idx, instr in enumerate(instrs):
            for v in instr.defs():
                d = (v, label, idx)
                # kill all other defs of v
                k |= (var_defs[v] - {d})
                g = (g - var_defs[v]) | {d}
        gen[label] = g
        kill[label] = k

    reach_in = {b: set() for b, _ in blocks}
    reach_out = {b: set() for b, _ in blocks}

    entry_label = blocks[0][0]

    changed = True
    while changed:
        changed = False
        for label, _ in blocks:
            old_out = reach_out[label].copy()
            # reach_in = union of reach_out of predecessors
            new_in = set()
            for p in pred[label]:
                new_in |= reach_out[p]
            reach_in[label] = new_in
            # reach_out = gen ∪ (reach_in - kill)
            new_out = gen[label] | (reach_in[label] - kill[label])
            reach_out[label] = new_out
            if new_out != old_out:
                changed = True

    return reach_in, reach_out


def available_expressions(blocks, cfg):
    """Forward dataflow: available expressions.
    An expression is (src1, op, src2) from binary ops.
    Returns avail_in, avail_out: block_label -> set of (src1, op, src2).
    """
    pred = build_pred(cfg)
    # Collect all expressions
    all_exprs = set()
    for label, instrs in blocks:
        for instr in instrs:
            if instr.kind == 'assign_binop':
                all_exprs.add((instr.src1, instr.op, instr.src2))

    # Compute e_gen and e_kill per block
    e_gen = {}
    e_kill = {}
    for label, instrs in blocks:
        g = set()
        k = set()
        for instr in instrs:
            if instr.kind == 'assign_binop':
                expr = (instr.src1, instr.op, instr.src2)
                # If dst doesn't appear in the expression, it's generated
                # First kill any expressions containing the defined var
                for v in instr.defs():
                    killed = {e for e in all_exprs if v in (e[0], e[2])}
                    k |= killed
                    g -= killed
                # Then generate this expression (unless it uses dst)
                if instr.dst not in (instr.src1, instr.src2):
                    g.add(expr)
            else:
                for v in instr.defs():
                    killed = {e for e in all_exprs if v in (e[0], e[2])}
                    k |= killed
                    g -= killed
        e_gen[label] = g
        e_kill[label] = k

    entry_label = blocks[0][0]
    avail_in = {}
    avail_out = {}
    for label, _ in blocks:
        if label == entry_label:
            avail_in[label] = set()
            avail_out[label] = e_gen[label]
        else:
            avail_in[label] = set(all_exprs)
            avail_out[label] = set(all_exprs)

    changed = True
    while changed:
        changed = False
        for label, _ in blocks:
            if label == entry_label:
                continue
            old_out = avail_out[label].copy()
            # avail_in = intersection of avail_out of predecessors
            preds = pred[label]
            if preds:
                new_in = set(avail_out[preds[0]])
                for p in preds[1:]:
                    new_in &= avail_out[p]
            else:
                new_in = set()
            avail_in[label] = new_in
            # avail_out = e_gen ∪ (avail_in - e_kill)
            new_out = e_gen[label] | (avail_in[label] - e_kill[label])
            avail_out[label] = new_out
            if new_out != old_out:
                changed = True

    return avail_in, avail_out


# Constant propagation lattice: TOP (undefined), BOT (overdefined), or int constant
TOP = "TOP"
BOT = "BOT"


def _meet_const(a, b):
    if a == TOP:
        return b
    if b == TOP:
        return a
    if a == BOT or b == BOT:
        return BOT
    if a == b:
        return a
    return BOT


def _eval_const(op, v1, v2):
    """Evaluate binary op on two known integer constants."""
    ops = {
        '+': lambda a, b: a + b,
        '-': lambda a, b: a - b,
        '*': lambda a, b: a * b,
        '/': lambda a, b: a // b if b != 0 else None,
        '%': lambda a, b: a % b if b != 0 else None,
        '==': lambda a, b: int(a == b),
        '!=': lambda a, b: int(a != b),
        '<': lambda a, b: int(a < b),
        '>': lambda a, b: int(a > b),
        '<=': lambda a, b: int(a <= b),
        '>=': lambda a, b: int(a >= b),
        '&&': lambda a, b: int(bool(a) and bool(b)),
        '||': lambda a, b: int(bool(a) or bool(b)),
    }
    if op in ops:
        r = ops[op](v1, v2)
        return r
    return None


def _eval_unary_const(op, v):
    if op == '-':
        return -v
    if op == '!':
        return int(not bool(v))
    return None


def constant_propagation(blocks, cfg):
    """Forward dataflow: constant propagation using lattice.
    Returns const_in: block_label -> {var: value} where value is TOP, BOT, or int.
    """
    pred = build_pred(cfg)
    # Collect all variables
    all_vars = set()
    for label, instrs in blocks:
        for instr in instrs:
            all_vars |= instr.defs()
            all_vars |= instr.uses()

    entry_label = blocks[0][0]

    # Initialize: all vars TOP at all blocks
    const_in = {b: {v: TOP for v in all_vars} for b, _ in blocks}
    const_out = {b: {v: TOP for v in all_vars} for b, _ in blocks}

    def transfer(label, in_state):
        state = dict(in_state)
        block_instrs = dict(blocks)[label]
        for instr in block_instrs:
            if instr.kind == 'assign_const':
                state[instr.dst] = int(instr.src1)
            elif instr.kind == 'assign_copy':
                if _is_const(instr.src1):
                    state[instr.dst] = int(instr.src1)
                else:
                    state[instr.dst] = state.get(instr.src1, TOP)
            elif instr.kind == 'assign_binop':
                v1 = int(instr.src1) if _is_const(instr.src1) else state.get(instr.src1, TOP)
                v2 = int(instr.src2) if _is_const(instr.src2) else state.get(instr.src2, TOP)
                if v1 == BOT or v2 == BOT:
                    state[instr.dst] = BOT
                elif v1 == TOP or v2 == TOP:
                    state[instr.dst] = TOP
                else:
                    r = _eval_const(instr.op, v1, v2)
                    state[instr.dst] = r if r is not None else BOT
            elif instr.kind == 'assign_unop':
                v = int(instr.src1) if _is_const(instr.src1) else state.get(instr.src1, TOP)
                if v == BOT:
                    state[instr.dst] = BOT
                elif v == TOP:
                    state[instr.dst] = TOP
                else:
                    r = _eval_unary_const(instr.op, v)
                    state[instr.dst] = r if r is not None else BOT
            elif instr.kind == 'call':
                state[instr.dst] = BOT  # conservative
        return state

    changed = True
    while changed:
        changed = False
        for label, _ in blocks:
            old_out = dict(const_out[label])
            # Meet predecessors
            preds = pred[label]
            if not preds:
                new_in = {v: TOP for v in all_vars}
            else:
                new_in = {}
                for v in all_vars:
                    val = TOP
                    for p in preds:
                        val = _meet_const(val, const_out[p].get(v, TOP))
                    new_in[v] = val
            const_in[label] = new_in
            new_out = transfer(label, new_in)
            const_out[label] = new_out
            if new_out != old_out:
                changed = True

    return const_in, const_out


# ============================================================
# Optimizations
# ============================================================

def dead_code_elimination(blocks, cfg):
    """Remove instructions that define variables never live-out of block and not used later in block."""
    live_in, live_out = liveness_analysis(blocks, cfg)
    new_blocks = []
    changed = False
    for label, instrs in blocks:
        new_instrs = []
        # For each instruction, check if its def is used
        # We need to compute liveness within the block
        live_at = set(live_out[label])
        keep = [True] * len(instrs)
        for i in range(len(instrs) - 1, -1, -1):
            instr = instrs[i]
            if instr.kind in ('if', 'goto', 'return', 'param', 'call', 'nop'):
                live_at = (live_at - instr.defs()) | instr.uses()
            else:
                d = instr.defs()
                if d and not (d & live_at):
                    keep[i] = False
                    changed = True
                else:
                    live_at = (live_at - d) | instr.uses()
        for i, instr in enumerate(instrs):
            if keep[i]:
                new_instrs.append(instr)
        new_blocks.append((label, new_instrs))
    return new_blocks, changed


def constant_folding_pass(blocks, cfg):
    """Use constant propagation to fold expressions."""
    const_in, const_out = constant_propagation(blocks, cfg)
    new_blocks = []
    changed = False
    for label, instrs in blocks:
        state = dict(const_in[label])
        new_instrs = []
        for instr in instrs:
            new_instr = deepcopy(instr)
            if instr.kind == 'assign_binop':
                v1 = int(instr.src1) if _is_const(instr.src1) else state.get(instr.src1, TOP)
                v2 = int(instr.src2) if _is_const(instr.src2) else state.get(instr.src2, TOP)
                if isinstance(v1, int) and isinstance(v2, int):
                    r = _eval_const(instr.op, v1, v2)
                    if r is not None:
                        new_instr = Instruction('assign_const', dst=instr.dst, src1=str(r))
                        changed = True
                elif isinstance(v1, int) and not _is_const(instr.src1):
                    new_instr.src1 = str(v1)
                    changed = True
                elif isinstance(v2, int) and not _is_const(instr.src2):
                    new_instr.src2 = str(v2)
                    changed = True
            elif instr.kind == 'assign_copy':
                if not _is_const(instr.src1):
                    v = state.get(instr.src1, TOP)
                    if isinstance(v, int):
                        new_instr = Instruction('assign_const', dst=instr.dst, src1=str(v))
                        changed = True
            elif instr.kind == 'assign_unop':
                v = int(instr.src1) if _is_const(instr.src1) else state.get(instr.src1, TOP)
                if isinstance(v, int):
                    r = _eval_unary_const(instr.op, v)
                    if r is not None:
                        new_instr = Instruction('assign_const', dst=instr.dst, src1=str(r))
                        changed = True
            # Update state for next instruction
            if new_instr.kind == 'assign_const':
                state[new_instr.dst] = int(new_instr.src1)
            elif new_instr.kind == 'assign_copy':
                state[new_instr.dst] = state.get(new_instr.src1, TOP) if not _is_const(new_instr.src1) else int(new_instr.src1)
            elif new_instr.kind in ('assign_binop', 'assign_unop', 'call'):
                state[new_instr.dst] = BOT
            new_instrs.append(new_instr)
        new_blocks.append((label, new_instrs))
    return new_blocks, changed


def cse_pass(blocks, cfg):
    """Common subexpression elimination using available expressions."""
    avail_in, avail_out = available_expressions(blocks, cfg)
    # We need to track which temp holds each available expression
    # For each block, track expressions computed so far
    new_blocks = []
    changed = False

    # First pass: find all expression -> first defining temp mappings
    expr_to_temp = {}
    for label, instrs in blocks:
        for instr in instrs:
            if instr.kind == 'assign_binop':
                expr = (instr.src1, instr.op, instr.src2)
                if expr not in expr_to_temp:
                    expr_to_temp[expr] = instr.dst

    # Second pass: replace redundant computations
    for label, instrs in blocks:
        avail = set(avail_in[label])
        computed_in_block = {}  # expr -> temp for this block
        new_instrs = []
        for instr in instrs:
            new_instr = deepcopy(instr)
            if instr.kind == 'assign_binop':
                expr = (instr.src1, instr.op, instr.src2)
                if expr in avail and expr in computed_in_block:
                    temp = computed_in_block[expr]
                    if temp != instr.dst:
                        new_instr = Instruction('assign_copy', dst=instr.dst, src1=temp)
                        changed = True
                elif expr in computed_in_block:
                    temp = computed_in_block[expr]
                    if temp != instr.dst:
                        new_instr = Instruction('assign_copy', dst=instr.dst, src1=temp)
                        changed = True
                else:
                    computed_in_block[expr] = instr.dst

                # Update avail: kill exprs containing dst, add this expr
                for v in instr.defs():
                    avail = {e for e in avail if v not in (e[0], e[2])}
                    computed_in_block = {e: t for e, t in computed_in_block.items() if v not in (e[0], e[2]) or e == expr}
                if instr.dst not in (instr.src1, instr.src2):
                    avail.add(expr)
            else:
                for v in instr.defs():
                    avail = {e for e in avail if v not in (e[0], e[2])}
                    computed_in_block = {e: t for e, t in computed_in_block.items() if v not in (e[0], e[2])}
            new_instrs.append(new_instr)
        new_blocks.append((label, new_instrs))
    return new_blocks, changed


def optimize(blocks, cfg):
    """Run optimization passes to fixpoint."""
    changed = True
    while changed:
        changed = False
        blocks, c = constant_folding_pass(blocks, cfg)
        changed |= c
        cfg = build_cfg(blocks)  # rebuild after changes
        blocks, c = cse_pass(blocks, cfg)
        changed |= c
        cfg = build_cfg(blocks)
        blocks, c = dead_code_elimination(blocks, cfg)
        changed |= c
        cfg = build_cfg(blocks)
    return blocks, cfg


# ============================================================
# Output
# ============================================================

def blocks_to_tac(fname, blocks):
    lines = [f"FUNC {fname}:"]
    for label, instrs in blocks:
        lines.append(f"{label}:")
        for instr in instrs:
            lines.append(instr.to_tac())
    lines.append("ENDFUNC")
    return '\n'.join(lines) + '\n'


def write_results(basename, fname, blocks, cfg, results_dir):
    # CFG
    cfg_data = {k: v for k, v in cfg.items()}
    with open(os.path.join(results_dir, f"{basename}.cfg.json"), 'w') as f:
        json.dump(cfg_data, f, indent=2, sort_keys=True)

    # Liveness
    live_in, live_out = liveness_analysis(blocks, cfg)
    live_data = {k: sorted(list(v)) for k, v in live_in.items()}
    with open(os.path.join(results_dir, f"{basename}.live.json"), 'w') as f:
        json.dump(live_data, f, indent=2, sort_keys=True)

    # Reaching definitions
    reach_in, reach_out = reaching_definitions(blocks, cfg)
    reach_data = {}
    for k, v in reach_in.items():
        reach_data[k] = sorted([[d[0], d[1], d[2]] for d in v], key=lambda x: (x[0], x[1], x[2]))
    with open(os.path.join(results_dir, f"{basename}.reaching.json"), 'w') as f:
        json.dump(reach_data, f, indent=2, sort_keys=True)

    # Available expressions
    avail_in, avail_out = available_expressions(blocks, cfg)
    avail_data = {}
    for k, v in avail_in.items():
        avail_data[k] = sorted([list(e) for e in v])
    with open(os.path.join(results_dir, f"{basename}.avail.json"), 'w') as f:
        json.dump(avail_data, f, indent=2, sort_keys=True)

    # Constant propagation
    const_in, const_out = constant_propagation(blocks, cfg)
    const_data = {}
    for k, v in const_in.items():
        const_data[k] = {}
        for var, val in sorted(v.items()):
            if val == TOP:
                const_data[k][var] = "TOP"
            elif val == BOT:
                const_data[k][var] = "BOT"
            else:
                const_data[k][var] = val
    with open(os.path.join(results_dir, f"{basename}.constprop.json"), 'w') as f:
        json.dump(const_data, f, indent=2, sort_keys=True)

    # Optimized TAC
    opt_blocks, opt_cfg = optimize(deepcopy(blocks), build_cfg(blocks))
    opt_tac = blocks_to_tac(fname, opt_blocks)
    with open(os.path.join(results_dir, f"{basename}.opt.tac"), 'w') as f:
        f.write(opt_tac)


def main():
    programs_dir = '/app/programs'
    results_dir = '/app/results'
    os.makedirs(results_dir, exist_ok=True)

    for fname_tac in sorted(os.listdir(programs_dir)):
        if not fname_tac.endswith('.tac'):
            continue
        basename = fname_tac[:-4]
        with open(os.path.join(programs_dir, fname_tac)) as f:
            text = f.read()
        functions = parse_tac(text)
        for func_name, blocks in functions:
            cfg = build_cfg(blocks)
            write_results(basename, func_name, blocks, cfg, results_dir)


if __name__ == '__main__':
    main()
