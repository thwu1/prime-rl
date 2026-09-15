
"""Graph-coloring register allocator: Chaitin-Briggs with optimistic coloring
and Briggs conservative coalescing.

Algorithm outline:
  1.  Compute iterative backward liveness across the CFG.
  2.  Build interference graph (with copy-exception rule) and collect moves.
  3.  For each register class independently:
      a.  Pre-pass Briggs coalescing of copy-related, non-interfering pairs.
      b.  Simplify / potential-spill loop (push nodes onto a stack).
      c.  Select phase: pop nodes and assign colours (optimistic colouring).
"""

import sys
from collections import defaultdict
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

sys.path.insert(0, "/app")
import ir


# ---------------------------------------------------------------------------
# 1. Iterative backward liveness analysis
# ---------------------------------------------------------------------------

def _compute_liveness(func: ir.Function):
    """Return per-instruction liveness as dict[(label, idx)] -> (live_in, live_out)."""
    block_live_in: Dict[str, Set[str]] = {l: set() for l in func.block_order}
    block_live_out: Dict[str, Set[str]] = {l: set() for l in func.block_order}

    changed = True
    while changed:
        changed = False
        for label in reversed(func.block_order):
            block = func.blocks[label]

            new_out: Set[str] = set()
            for s in block.successors:
                new_out |= block_live_in[s]

            live = set(new_out)
            for instr in reversed(block.instructions):
                live = instr.uses() | (live - instr.defs())
            new_in = live

            if new_out != block_live_out[label] or new_in != block_live_in[label]:
                changed = True
                block_live_out[label] = new_out
                block_live_in[label] = new_in

    result: Dict[Tuple[str, int], Tuple[FrozenSet[str], FrozenSet[str]]] = {}
    for label in func.block_order:
        block = func.blocks[label]
        live = set(block_live_out[label])
        for i in range(len(block.instructions) - 1, -1, -1):
            instr = block.instructions[i]
            lo = frozenset(live)
            live = instr.uses() | (live - instr.defs())
            li = frozenset(live)
            result[(label, i)] = (li, lo)
    return result


# ---------------------------------------------------------------------------
# 2. Interference graph + move list
# ---------------------------------------------------------------------------

def _build_graph(func, liveness):
    """Return (adj, moves) where adj maps vreg -> set of interfering vregs,
    and moves is a list of (src, dst) copy pairs."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    moves: List[Tuple[str, str]] = []
    all_vregs = set(func.vreg_classes.keys())

    for label in func.block_order:
        block = func.blocks[label]
        for i, instr in enumerate(block.instructions):
            _, lo = liveness[(label, i)]
            for d in instr.defs():
                for v in lo:
                    if v == d:
                        continue
                    if instr.op == "copy" and v == instr.src1:
                        continue
                    adj[d].add(v)
                    adj[v].add(d)
            if instr.op == "copy" and instr.src1 in all_vregs and instr.dst in all_vregs:
                moves.append((instr.src1, instr.dst))

    # Ensure every vreg is present
    for v in all_vregs:
        _ = adj[v]

    return adj, moves


# ---------------------------------------------------------------------------
# 3. Per-class allocation: coalesce, simplify, select
# ---------------------------------------------------------------------------

def _allocate_class(
    class_vregs: Set[str],
    adj: Dict[str, Set[str]],
    moves: List[Tuple[str, str]],
    func: ir.Function,
    liveness,
    k: int,
    phys_regs: List[str],
) -> Dict[str, str]:
    """Allocate registers for one register class."""

    if not class_vregs:
        return {}

    # --- Class-local adjacency ---
    cadj: Dict[str, Set[str]] = {v: adj[v] & class_vregs for v in class_vregs}

    # --- Union-Find for coalescing ---
    parent: Dict[str, str] = {v: v for v in class_vregs}

    def find(x: str) -> str:
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    # Representative adjacency (mutable during coalescing)
    rep_adj: Dict[str, Set[str]] = {v: set(cadj[v]) for v in class_vregs}

    # --- Briggs coalescing pass ---
    for src, dst in moves:
        if src not in class_vregs or dst not in class_vregs:
            continue
        rs, rd = find(src), find(dst)
        if rs == rd:
            continue
        if rd in rep_adj.get(rs, set()):
            continue  # they interfere

        merged_neighbors = (rep_adj.get(rs, set()) | rep_adj.get(rd, set())) - {rs, rd}
        significant = sum(1 for n in merged_neighbors if len(rep_adj.get(n, set())) >= k)
        if significant >= k:
            continue  # Briggs test fails

        # Merge rd into rs
        parent[rd] = rs
        new_n = (rep_adj.get(rs, set()) | rep_adj.get(rd, set())) - {rs, rd}
        rep_adj[rs] = new_n
        for n in rep_adj.get(rd, set()):
            if n != rs and n in rep_adj:
                rep_adj[n].discard(rd)
                rep_adj[n].add(rs)
        rep_adj.pop(rd, None)

    # --- Active representatives ---
    active_reps = set(rep_adj.keys())

    # Clean up: make sure rep_adj only references active reps
    for v in list(active_reps):
        rep_adj[v] = rep_adj[v] & active_reps

    # --- Use counts for spill cost ---
    use_count: Dict[str, int] = defaultdict(int)
    for label in func.block_order:
        block = func.blocks[label]
        for instr in block.instructions:
            for v in instr.uses() | instr.defs():
                if v in class_vregs:
                    use_count[find(v)] += 1

    # --- Simplify / potential-spill ---
    stack: List[Tuple[str, bool]] = []  # (node, is_potential_spill)
    remaining = set(active_reps)

    while remaining:
        # Try to find a simplifiable node (degree < k)
        found = None
        for v in remaining:
            deg = len(rep_adj.get(v, set()) & remaining)
            if deg < k:
                found = v
                break

        if found is not None:
            stack.append((found, False))
            remaining.remove(found)
        else:
            # Potential spill: pick node with lowest cost = uses / degree
            def spill_cost(v):
                deg = len(rep_adj.get(v, set()) & remaining)
                return use_count.get(v, 0) / max(deg, 1)

            candidate = min(remaining, key=spill_cost)
            stack.append((candidate, True))
            remaining.remove(candidate)

    # --- Select: assign colours ---
    color: Dict[str, str] = {}
    spill_idx = 0

    while stack:
        v, _ = stack.pop()
        used_colors = set()
        for n in rep_adj.get(v, set()):
            c = color.get(n)
            if c is not None and not c.startswith("stack"):
                used_colors.add(c)

        available = [r for r in phys_regs if r not in used_colors]
        if available:
            color[v] = available[0]
        else:
            color[v] = f"stack_{spill_idx}"
            spill_idx += 1

    # --- Map original vregs to colours ---
    result: Dict[str, str] = {}
    for v in class_vregs:
        result[v] = color[find(v)]
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def allocate(func: ir.Function) -> Dict[str, str]:
    """Allocate physical registers (or stack slots) for every virtual register.

    Returns a dict mapping vreg name -> physical register name (e.g. "r3",
    "xmm5") or stack slot name (e.g. "stack_0").
    """
    liveness = _compute_liveness(func)
    adj, moves = _build_graph(func, liveness)

    allocation: Dict[str, str] = {}

    for reg_class in ("gp", "xmm"):
        class_vregs = {v for v in func.vreg_classes if func.vreg_classes[v] == reg_class}
        if not class_vregs:
            continue
        k = ir.k_for_class(reg_class)
        phys = ir.regs_for_class(reg_class)
        result = _allocate_class(class_vregs, adj, moves, func, liveness, k, phys)
        allocation.update(result)

    return allocation
