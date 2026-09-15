"""
Solution: Register allocator using liveness analysis, interference
graph construction, and DSATUR graph coloring with spill support.
"""


import sys
sys.path.insert(0, '/app')

from ir import *

NUM_PHYS_REGS = 6


def allocate_registers(program: Program) -> Program:
    program = program.copy()

    all_vregs = program.all_vregs()
    if not all_vregs:
        return program

    cfg = _build_cfg(program)
    live_after = _liveness_analysis(program, cfg)
    adj, move_pairs = _build_interference(program, live_after, all_vregs)
    reg_map = _color_graph(adj, move_pairs, all_vregs)
    return _rewrite(program, reg_map)


# ------------------------------------------------------------------ #
# 1. Control-flow graph
# ------------------------------------------------------------------ #

def _build_cfg(program):
    cfg = {}
    for label, instrs in program.blocks.items():
        last = instrs[-1] if instrs else None
        cfg[label] = last.successors() if last else []
    return cfg


# ------------------------------------------------------------------ #
# 2. Liveness analysis (backward dataflow, fixpoint for loops)
# ------------------------------------------------------------------ #

def _liveness_analysis(program, cfg):
    preds = {l: [] for l in program.blocks}
    for l, succs in cfg.items():
        for s in succs:
            preds[s].append(l)

    live_in = {l: set() for l in program.blocks}
    live_out = {l: set() for l in program.blocks}

    changed = True
    while changed:
        changed = False
        for label in program.blocks:
            new_out = set()
            for s in cfg[label]:
                new_out |= live_in[s]
            if new_out != live_out[label]:
                live_out[label] = new_out
                changed = True

            live = set(live_out[label])
            for instr in reversed(program.blocks[label]):
                live = (live - instr.defs()) | instr.uses()
            if live != live_in[label]:
                live_in[label] = live
                changed = True

    # Per-instruction live-after map
    la_map = {}
    for label, instrs in program.blocks.items():
        live = set(live_out[label])
        for i in range(len(instrs) - 1, -1, -1):
            la_map[(label, i)] = frozenset(live)
            live = (live - instrs[i].defs()) | instrs[i].uses()
    return la_map


# ------------------------------------------------------------------ #
# 3. Interference graph
# ------------------------------------------------------------------ #

def _build_interference(program, la_map, all_vregs):
    adj = {v: set() for v in all_vregs}
    move_pairs = set()

    def _add_edge(a, b):
        adj[a].add(b)
        adj[b].add(a)

    for label, instrs in program.blocks.items():
        for i, instr in enumerate(instrs):
            la = la_map[(label, i)]
            if instr.is_move() and is_vreg(instr.dst):
                # Move: dst interferes with live-after EXCEPT src
                for v in la:
                    if is_vreg(v) and v != instr.dst and v != instr.src1:
                        _add_edge(instr.dst, v)
                if is_vreg(instr.src1):
                    move_pairs.add(
                        (min(instr.dst, instr.src1),
                         max(instr.dst, instr.src1)))
            else:
                for d in instr.defs():
                    if is_vreg(d):
                        for v in la:
                            if is_vreg(v) and v != d:
                                _add_edge(d, v)
    return adj, move_pairs


# ------------------------------------------------------------------ #
# 4. Graph coloring (DSATUR with move bias and spill)
# ------------------------------------------------------------------ #

def _color_graph(adj, move_pairs, all_vregs):
    vregs = sorted(all_vregs)   # deterministic order
    coloring = {}
    saturation = {v: set() for v in vregs}

    while len(coloring) < len(vregs):
        # Pick uncolored vertex with highest saturation, then degree, then name
        best = None
        best_key = (-1, -1, '')
        for v in vregs:
            if v in coloring:
                continue
            key = (len(saturation[v]), len(adj[v]), v)
            if key > best_key:
                best_key = key
                best = v

        used = saturation[best]

        # Try move-biased color first
        preferred = set()
        for a, b in move_pairs:
            partner = None
            if a == best:
                partner = b
            elif b == best:
                partner = a
            if partner and partner in coloring:
                preferred.add(coloring[partner])

        chosen = None
        for c in sorted(preferred):
            if c < NUM_PHYS_REGS and c not in used:
                chosen = c
                break
        if chosen is None:
            c = 0
            while c in used:
                c += 1
            chosen = c

        coloring[best] = chosen
        for n in adj[best]:
            if n not in coloring:
                saturation[n].add(chosen)

    # Map color → register / stack-slot name
    reg_map = {}
    for v, color in coloring.items():
        reg_map[v] = f'r{color}' if color < NUM_PHYS_REGS else f's{color - NUM_PHYS_REGS}'
    return reg_map


# ------------------------------------------------------------------ #
# 5. Rewrite program
# ------------------------------------------------------------------ #

def _rewrite(program, reg_map):
    new_blocks = {}
    for label, instrs in program.blocks.items():
        new_instrs = []
        for instr in instrs:
            ni = Instr(
                op=instr.op,
                dst=reg_map.get(instr.dst, instr.dst),
                src1=reg_map.get(instr.src1, instr.src1),
                src2=reg_map.get(instr.src2, instr.src2),
                label1=instr.label1,
                label2=instr.label2,
            )
            # Drop trivial moves
            if ni.op == 'MOV' and ni.dst == ni.src1:
                continue
            new_instrs.append(ni)
        new_blocks[label] = new_instrs
    return Program(new_blocks, program.entry)
