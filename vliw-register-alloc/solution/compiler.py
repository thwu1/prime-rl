"""
VLIW Backend Compiler — reference solution.


Implements register allocation (linear-scan with spilling) and
VLIW list scheduling.
"""

from vliw import (
    Program, CompiledProgram, PhysInst, VLIWBundle,
    Inst, LATENCY, MEM_SIZE, MASK32, slot_kind,
)
from collections import defaultdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_use_map(instructions):
    """Return {vreg: last_instruction_index_that_reads_vreg}."""
    lu = {}
    for i, inst in enumerate(instructions):
        for s in inst.srcs:
            lu[s] = i
    return lu


def _max_simultaneous_live(instructions, last_use):
    """Estimate max simultaneously live virtual registers."""
    live = set()
    max_live = 0
    for i, inst in enumerate(instructions):
        if inst.dst >= 0:
            live.add(inst.dst)
        dead = {v for v in live if last_use.get(v, -1) <= i}
        live -= dead
        if len(live) > max_live:
            max_live = len(live)
    return max_live


# ---------------------------------------------------------------------------
# Phase 1: Register allocation with spilling
# ---------------------------------------------------------------------------

def _find_victim(p2v, last_use, cur_pos):
    """Pick the allocated physical register whose vreg has the furthest next use."""
    best_preg = None
    best_dist = -1
    for preg, vreg in p2v.items():
        d = last_use.get(vreg, cur_pos) - cur_pos
        if d > best_dist:
            best_dist = d
            best_preg = preg
    return best_preg


def _register_allocate(instructions, max_regs, data_size):
    """Allocate physical registers; insert spill/reload code as needed.

    Returns a list of PhysInst in execution order.
    """
    last_use = _last_use_map(instructions)
    max_live = _max_simultaneous_live(instructions, last_use)

    # Decide whether we need a dedicated spill-base register.
    # r0 = hardwired zero.  r1 = spill base (if spilling needed).
    need_spill = max_live >= max_regs
    first_usable = 2 if need_spill else 1
    spill_base_reg = 1 if need_spill else -1
    spill_mem_base = data_size

    free = list(range(max_regs - 1, first_usable - 1, -1))
    v2p = {}        # vreg -> preg
    p2v = {}        # preg -> vreg
    spill_slot = {} # vreg -> memory offset from spill_mem_base
    next_slot = [0] # mutable counter

    result = []

    # Optimisation: map any `li 0` vreg straight to r0 (hardwired zero).
    li_zero_vregs = set()
    for inst in instructions:
        if inst.op == "li" and inst.imm == 0 and inst.dst >= 0:
            li_zero_vregs.add(inst.dst)
            v2p[inst.dst] = 0   # r0

    if need_spill:
        result.append(PhysInst("li", spill_base_reg, [], spill_mem_base))

    def _ensure_free():
        """Make room for one more register by spilling if needed."""
        if free:
            return
        victim = _find_victim(p2v, last_use, cur_pos)
        vv = p2v[victim]
        if vv not in spill_slot:
            spill_slot[vv] = next_slot[0]
            next_slot[0] += 1
        result.append(PhysInst("sw", -1, [spill_base_reg, victim], spill_slot[vv]))
        del v2p[vv]
        del p2v[victim]
        free.append(victim)

    for cur_pos, inst in enumerate(instructions):
        # Skip li-zero instructions (already mapped to r0).
        if inst.dst in li_zero_vregs and inst.op == "li" and inst.imm == 0:
            continue

        # --- reload any spilled sources ---
        for s in inst.srcs:
            if s in v2p:
                continue
            if s in spill_slot:
                _ensure_free()
                preg = free.pop()
                result.append(PhysInst("lw", preg, [spill_base_reg], spill_slot[s]))
                v2p[s] = preg
                p2v[preg] = s

        # --- translate sources ---
        phys_srcs = [v2p.get(s, 0) for s in inst.srcs]

        # --- free dead sources (before allocating dst) ---
        freed_this = set()
        for s in inst.srcs:
            if s in v2p and s not in freed_this and last_use.get(s, -1) <= cur_pos:
                if inst.dst < 0 or s != inst.dst:
                    preg = v2p.pop(s)
                    if preg == 0:
                        # r0 is hardwired; never goes to free / p2v
                        freed_this.add(s)
                        continue
                    del p2v[preg]
                    free.append(preg)
                    freed_this.add(s)

        if inst.dst >= 0:
            # --- allocate for destination ---
            _ensure_free()
            preg = free.pop()
            # Evict previous occupant (WAW on physical register).
            if preg in p2v:
                old = p2v[preg]
                if old in v2p and v2p[old] == preg:
                    del v2p[old]
                del p2v[preg]
            v2p[inst.dst] = preg
            p2v[preg] = inst.dst
            result.append(PhysInst(inst.op, preg, phys_srcs, inst.imm))
        else:
            result.append(PhysInst(inst.op, -1, phys_srcs, inst.imm))

    return result


# ---------------------------------------------------------------------------
# Phase 2: VLIW list scheduling
# ---------------------------------------------------------------------------

def _build_deps(phys_insts):
    """Build dependency sets for each instruction index.

    Tracks RAW, WAW, and WAR hazards on physical registers,
    plus conservative memory ordering.
    """
    n = len(phys_insts)
    writer = {}                     # preg -> most recent writer index
    readers = defaultdict(set)      # preg -> set of reader indices since last write
    deps = [set() for _ in range(n)]

    last_mem = -1
    for i, inst in enumerate(phys_insts):
        # RAW: inst reads r, depends on whoever last wrote r
        for s in inst.srcs:
            if s > 0 and s in writer:
                deps[i].add(writer[s])

        # WAW: inst writes r, depends on whoever last wrote r
        if inst.dst > 0 and inst.dst in writer:
            deps[i].add(writer[inst.dst])

        # WAR: inst writes r, depends on everyone who read r since its last write
        if inst.dst > 0 and inst.dst in readers:
            for j in readers[inst.dst]:
                if j != i:
                    deps[i].add(j)

        # Memory ordering (conservative: all mem ops serialised)
        if inst.op in ("lw", "sw"):
            if last_mem >= 0:
                deps[i].add(last_mem)
            last_mem = i

        # Bookkeeping: record readers
        for s in inst.srcs:
            if s > 0:
                readers[s].add(i)

        # Bookkeeping: record writer (clears readers for that reg)
        if inst.dst > 0:
            writer[inst.dst] = i
            readers[inst.dst] = set()

    return deps


def _list_schedule(phys_insts, deps):
    """Schedule PhysInst list into VLIW bundles using list scheduling."""
    n = len(phys_insts)

    # Reverse deps
    rdeps = [set() for _ in range(n)]
    for i in range(n):
        for j in deps[i]:
            rdeps[j].add(i)

    # Critical-path priority (larger = schedule sooner)
    crit = [0] * n
    for i in range(n - 1, -1, -1):
        lat = LATENCY[phys_insts[i].op]
        max_succ = max((crit[j] for j in rdeps[i]), default=0)
        crit[i] = lat + max_succ

    scheduled = [False] * n
    ready_at = {}            # preg -> cycle when value becomes available
    cycle = 0
    bundles = []
    remaining = n

    while remaining > 0:
        # Gather ready instructions (all preds scheduled, operands available)
        ready = []
        for i in range(n):
            if scheduled[i]:
                continue
            if not all(scheduled[j] for j in deps[i]):
                continue
            ok = True
            for s in phys_insts[i].srcs:
                if s > 0 and s in ready_at and ready_at[s] > cycle:
                    ok = False
                    break
            if ok:
                ready.append(i)

        if not ready:
            cycle += 1
            if cycle > 50000:
                raise RuntimeError("Scheduling stuck")
            continue

        # Sort by critical path (longest first)
        ready.sort(key=lambda i: -crit[i])

        bundle = VLIWBundle()
        packed = set()

        for i in ready:
            # Must not depend on anything packed in *this* bundle
            if any(j in packed for j in deps[i]):
                continue

            inst = phys_insts[i]
            kind = slot_kind(inst.op)

            # WAW check within bundle
            if inst.dst > 0:
                conflict = False
                for other in bundle.all_insts():
                    if other.dst == inst.dst:
                        conflict = True
                        break
                if conflict:
                    continue

            placed = False
            if kind == "alu":
                if bundle.alu0 is None:
                    bundle.alu0 = inst; placed = True
                elif bundle.alu1 is None:
                    bundle.alu1 = inst; placed = True
            elif kind == "mul":
                if bundle.mul is None:
                    bundle.mul = inst; placed = True
            elif kind == "mem":
                if bundle.mem is None:
                    bundle.mem = inst; placed = True

            if placed:
                packed.add(i)
                scheduled[i] = True
                remaining -= 1
                if inst.dst > 0:
                    ready_at[inst.dst] = cycle + LATENCY[inst.op]

        if bundle.all_insts():
            bundles.append(bundle)
        cycle += 1

    return bundles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile(program: Program, max_regs: int) -> CompiledProgram:
    """Compile *program* to VLIW bundles using at most *max_regs* registers."""
    phys_insts = _register_allocate(
        program.instructions, max_regs, program.data_size
    )
    deps = _build_deps(phys_insts)
    bundles = _list_schedule(phys_insts, deps)
    return CompiledProgram(bundles, max_regs)
