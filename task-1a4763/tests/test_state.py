
"""Tests for the register allocator.

Each test loads an IR program, runs the allocator, and independently verifies
the allocation using a reference liveness analysis and interference graph.
"""

import sys
import os
import pytest
from collections import defaultdict

sys.path.insert(0, "/app")
import ir


# ---------------------------------------------------------------------------
# Reference liveness analysis (independent of the allocator)
# ---------------------------------------------------------------------------

def _ref_liveness(func):
    """Iterative backward dataflow liveness analysis.

    Returns a dict mapping (block_label, instr_index) to (live_in, live_out)
    where each is a frozenset of vreg names.
    """
    block_live_in = {label: set() for label in func.block_order}
    block_live_out = {label: set() for label in func.block_order}

    changed = True
    while changed:
        changed = False
        for label in reversed(func.block_order):
            block = func.blocks[label]

            new_out = set()
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

    result = {}
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


def _ref_interference(func, liveness):
    """Build interference edges from reference liveness.

    Returns a set of frozenset({a, b}) pairs representing interference edges.
    """
    edges = set()

    for label in func.block_order:
        block = func.blocks[label]
        for i, instr in enumerate(block.instructions):
            _, lo = liveness[(label, i)]
            for d in instr.defs():
                for v in lo:
                    if v == d:
                        continue
                    # Copy exception: src and dst of a copy don't interfere
                    if instr.op == "copy" and v == instr.src1:
                        continue
                    edges.add(frozenset({d, v}))

    return edges


def _count_remaining_moves(func, allocation):
    """Count copy instructions where src and dst are allocated differently."""
    count = 0
    for label in func.block_order:
        block = func.blocks[label]
        for instr in block.instructions:
            if instr.op == "copy" and instr.src1 in allocation and instr.dst in allocation:
                if allocation[instr.src1] != allocation[instr.dst]:
                    count += 1
    return count


# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------

def _verify(func, alloc, max_spills=None, max_moves=None):
    """Verify that an allocation is valid and meets quality bounds."""
    # (1) All vregs allocated
    for vreg in func.vreg_classes:
        assert vreg in alloc, f"Virtual register '{vreg}' is missing from the allocation"

    # (2) Class constraints
    for vreg, phys in alloc.items():
        if phys.startswith("stack"):
            continue
        reg_class = func.vreg_classes.get(vreg)
        if reg_class is None:
            continue
        valid_regs = ir.regs_for_class(reg_class)
        assert phys in valid_regs, (
            f"Virtual register '{vreg}' (class={reg_class}) was allocated to "
            f"'{phys}' which is not in the valid set {valid_regs}"
        )

    # (3) Interference check
    liveness = _ref_liveness(func)
    edges = _ref_interference(func, liveness)
    for edge in edges:
        v1, v2 = tuple(edge)
        r1 = alloc.get(v1)
        r2 = alloc.get(v2)
        if r1 is None or r2 is None:
            continue
        if r1.startswith("stack") or r2.startswith("stack"):
            continue
        assert r1 != r2, (
            f"Interfering virtual registers '{v1}' and '{v2}' are both "
            f"allocated to physical register '{r1}'"
        )

    # (4) Spill bound
    spill_count = sum(1 for r in alloc.values() if r.startswith("stack"))
    if max_spills is not None:
        assert spill_count <= max_spills, (
            f"Too many spills: {spill_count} > allowed {max_spills}"
        )

    # (5) Move bound
    if max_moves is not None:
        moves = _count_remaining_moves(func, alloc)
        assert moves <= max_moves, (
            f"Too many remaining moves: {moves} > allowed {max_moves}"
        )


def _load_and_allocate(program_name):
    """Load a program and allocate registers for its 'target' function."""
    import allocator

    prog = ir.load_program(f"/app/programs/{program_name}.json")
    func = prog.functions["target"]
    alloc = allocator.allocate(func)
    return func, alloc


# ---------------------------------------------------------------------------
# Test cases — pre-built programs
# ---------------------------------------------------------------------------

class TestTrivial:
    """Trivial program: 3 GP registers, easily colorable."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("trivial")
        _verify(func, alloc, max_spills=0)


class TestTwelveClique:
    """12 GP registers forming a tight clique.  Must be colorable without spills."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("twelve_clique")
        _verify(func, alloc, max_spills=0)


class TestForceSpill:
    """13 GP registers all simultaneously live.  Exactly one must be spilled."""

    def test_spill_bound(self):
        func, alloc = _load_and_allocate("force_spill")
        _verify(func, alloc, max_spills=1)

    def test_at_least_one_spill(self):
        func, alloc = _load_and_allocate("force_spill")
        spill_count = sum(1 for r in alloc.values() if r.startswith("stack"))
        assert spill_count >= 1, (
            "13 simultaneously-live GP vregs with k=12 requires at least 1 spill"
        )


class TestFourteenXmm:
    """14 XMM registers forming a tight clique.  Must be colorable without spills."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("fourteen_xmm")
        _verify(func, alloc, max_spills=0)


class TestLoopLiveness:
    """Loop requiring iterative liveness analysis.  Variables live across the
    back-edge must not share a register with variables inside the loop body."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("loop_liveness")
        _verify(func, alloc, max_spills=0)

    def test_back_edge_liveness(self):
        func, alloc = _load_and_allocate("loop_liveness")
        liveness = _ref_liveness(func)
        edges = _ref_interference(func, liveness)
        for edge in edges:
            v1, v2 = tuple(edge)
            r1, r2 = alloc.get(v1), alloc.get(v2)
            if r1 and r2 and not r1.startswith("stack") and not r2.startswith("stack"):
                assert r1 != r2, (
                    f"Loop liveness violation: '{v1}' and '{v2}' interfere but "
                    f"share register '{r1}'"
                )


class TestBriggsCoalesce:
    """Program with copy instructions that should be coalesced.
    After coalescing, zero register-to-register moves should remain."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("briggs_coalesce")
        _verify(func, alloc, max_spills=0)

    def test_coalescing(self):
        func, alloc = _load_and_allocate("briggs_coalesce")
        _verify(func, alloc, max_moves=0)


class TestDiamondCfg:
    """Diamond-shaped control flow (if/else) with variables live across
    merge point."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("diamond_cfg")
        _verify(func, alloc, max_spills=0)


class TestMixedTypes:
    """Both GP and XMM register pressure simultaneously.  Each class is
    within its k limit so no spills should be needed."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("mixed_types")
        _verify(func, alloc, max_spills=0)

    def test_class_separation(self):
        func, alloc = _load_and_allocate("mixed_types")
        for vreg, phys in alloc.items():
            if phys.startswith("stack"):
                continue
            cls = func.vreg_classes[vreg]
            if cls == "gp":
                assert phys.startswith("r"), (
                    f"GP vreg '{vreg}' allocated to non-GP register '{phys}'"
                )
            elif cls == "xmm":
                assert phys.startswith("xmm"), (
                    f"XMM vreg '{vreg}' allocated to non-XMM register '{phys}'"
                )


# ---------------------------------------------------------------------------
# Test cases — generated stress-test programs
# ---------------------------------------------------------------------------

class TestSpillCascade:
    """16 GP + 16 XMM vregs all simultaneously live.
    GP k=12 requires exactly 4 spills; XMM k=14 requires exactly 2."""

    def test_validity(self):
        func, alloc = _load_and_allocate("spill_cascade")
        _verify(func, alloc)

    def test_gp_spill_upper_bound(self):
        func, alloc = _load_and_allocate("spill_cascade")
        gp_spills = sum(1 for v, r in alloc.items()
                        if r.startswith("stack") and func.vreg_classes.get(v) == "gp")
        assert gp_spills <= 4, f"Too many GP spills: {gp_spills} > 4"

    def test_gp_spill_lower_bound(self):
        func, alloc = _load_and_allocate("spill_cascade")
        gp_spills = sum(1 for v, r in alloc.items()
                        if r.startswith("stack") and func.vreg_classes.get(v) == "gp")
        assert gp_spills >= 4, (
            f"16 simultaneously-live GP vregs with k=12 needs >= 4 spills, got {gp_spills}"
        )

    def test_xmm_spill_upper_bound(self):
        func, alloc = _load_and_allocate("spill_cascade")
        xmm_spills = sum(1 for v, r in alloc.items()
                         if r.startswith("stack") and func.vreg_classes.get(v) == "xmm")
        assert xmm_spills <= 2, f"Too many XMM spills: {xmm_spills} > 2"

    def test_xmm_spill_lower_bound(self):
        func, alloc = _load_and_allocate("spill_cascade")
        xmm_spills = sum(1 for v, r in alloc.items()
                         if r.startswith("stack") and func.vreg_classes.get(v) == "xmm")
        assert xmm_spills >= 2, (
            f"16 simultaneously-live XMM vregs with k=14 needs >= 2 spills, got {xmm_spills}"
        )


class TestNestedLoopPressure:
    """Nested loops requiring iterative liveness analysis with copy chains."""

    def test_no_spills(self):
        func, alloc = _load_and_allocate("nested_loop_pressure")
        _verify(func, alloc, max_spills=0)

    def test_nested_back_edge_liveness(self):
        """Variables live across nested back-edges must not share registers
        with variables live inside loop bodies."""
        func, alloc = _load_and_allocate("nested_loop_pressure")
        liveness = _ref_liveness(func)
        edges = _ref_interference(func, liveness)
        for edge in edges:
            v1, v2 = tuple(edge)
            r1, r2 = alloc.get(v1), alloc.get(v2)
            if r1 and r2 and not r1.startswith("stack") and not r2.startswith("stack"):
                assert r1 != r2, (
                    f"Nested loop liveness violation: '{v1}' and '{v2}' interfere "
                    f"but share register '{r1}'"
                )
