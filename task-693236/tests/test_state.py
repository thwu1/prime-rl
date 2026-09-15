
"""Comprehensive tests for the x86-64 register allocator."""

import sys
sys.path.insert(0, '/app')
sys.path.insert(1, '/opt/task_lib')

import pytest
from ir import (
    Var, Reg, Deref, Immediate, Instr, Callq, Jump, JumpIf,
    X86Program, CALLER_SAVED, CALLEE_SAVED, ALLOCATABLE,
    variables_in_program, is_move,
)
from programs import (
    make_program_1, make_program_2, make_program_3,
    make_program_4, make_program_5, make_program_6,
    ALL_PROGRAMS,
)
from emulator import run_program
from allocator import (
    uncover_live, build_interference, build_move_graph,
    color_graph, assign_homes, patch_instructions,
    allocate_registers,
)


# ---------------------------------------------------------------------------
# Liveness analysis tests
# ---------------------------------------------------------------------------

class TestLiveness:
    def test_straight_line_first_instr(self):
        """After 'movq $1, v', only v should be live (needed by later movq v,x)."""
        prog = make_program_1()
        la = uncover_live(prog)['start']
        assert Var('v') in la[0], "v should be live after movq $1, v"
        assert Var('w') not in la[0], "w not yet defined"

    def test_straight_line_second_instr(self):
        """After 'movq $42, w', both v and w should be live."""
        prog = make_program_1()
        la = uncover_live(prog)['start']
        assert Var('v') in la[1]
        assert Var('w') in la[1]

    def test_straight_line_var_dies(self):
        """After 'movq v, x', v is dead (last use) and x is live."""
        prog = make_program_1()
        la = uncover_live(prog)['start']
        assert Var('v') not in la[2], "v should be dead after its last use"
        assert Var('x') in la[2]
        assert Var('w') in la[2]

    def test_diamond_branches_liveness(self):
        """In the diamond CFG, a and b must be live at the end of start block."""
        prog = make_program_2()
        la = uncover_live(prog)
        start_la = la['start']
        # After cmpq instruction (index 2), a and b are both still needed
        # by then_block and else_block
        assert Var('a') in start_la[2]
        assert Var('b') in start_la[2]

    def test_loop_fixedpoint_convergence(self):
        """Loop header must show both sum and i as live (requires fixed-point)."""
        prog = make_program_3()
        la = uncover_live(prog)
        # At the start of loop_header, both sum and i must be live.
        # This is only true if the back-edge from loop_body -> loop_header
        # propagates liveness of sum correctly (sum is used in loop_body
        # but that info must flow back through the back-edge).
        header_la = la['loop_header']
        # After cmpq $0, i: both sum and i should be live
        assert Var('i') in header_la[0], "i must be live in loop_header"
        assert Var('sum') in header_la[0], (
            "sum must be live in loop_header (requires fixed-point iteration)"
        )

    def test_call_liveness(self):
        """Variables live across a call must appear in live-after sets."""
        prog = make_program_5()
        la = uncover_live(prog)['start']
        # After callq (instruction index 3), a and b should be live
        assert Var('a') in la[3], "a must be live after callq"
        assert Var('b') in la[3], "b must be live after callq"


# ---------------------------------------------------------------------------
# Interference graph tests
# ---------------------------------------------------------------------------

class TestInterference:
    def _get_interference(self, make_prog):
        prog = make_prog()
        la = uncover_live(prog)
        return build_interference(prog, la)

    def test_straight_line_edges(self):
        """Verify expected interference edges from the running example."""
        g = self._get_interference(make_program_1)
        # Expected edges (from lecture analysis):
        assert g.has_edge(Var('w'), Var('v')), "w-v should interfere"
        assert g.has_edge(Var('x'), Var('w')), "x-w should interfere"
        assert g.has_edge(Var('y'), Var('w')), "y-w should interfere"
        assert g.has_edge(Var('z'), Var('w')), "z-w should interfere"
        assert g.has_edge(Var('z'), Var('y')), "z-y should interfere"
        assert g.has_edge(Var('t'), Var('z')), "t-z should interfere"

    def test_move_no_interference(self):
        """movq x, y: x and y should NOT interfere (move rule)."""
        g = self._get_interference(make_program_1)
        assert not g.has_edge(Var('y'), Var('x')), (
            "y-x must not interfere (move rule: skip src-dst edge)"
        )

    def test_call_clobbers_caller_saved(self):
        """Variables live across callq must interfere with caller-saved regs."""
        g = self._get_interference(make_program_5)
        for r in CALLER_SAVED:
            assert g.has_edge(Var('b'), Reg(r)), (
                f"b must interfere with caller-saved {r}"
            )

    def test_no_self_edges(self):
        """No vertex should have an edge to itself."""
        for name, make_prog, _ in ALL_PROGRAMS:
            g = self._get_interference(make_prog)
            for e in g.edges():
                assert e.source != e.target, (
                    f"Self-edge found: {e.source} in {name}"
                )


# ---------------------------------------------------------------------------
# Graph coloring tests
# ---------------------------------------------------------------------------

class TestColoring:
    def _get_coloring(self, make_prog):
        prog = make_prog()
        la = uncover_live(prog)
        interference = build_interference(prog, la)
        move_g = build_move_graph(prog)
        variables = variables_in_program(prog)
        coloring = color_graph(interference, move_g, variables)
        return prog, interference, coloring, variables

    def test_valid_coloring_all(self):
        """No two adjacent vertices in the interference graph share a color."""
        for name, make_prog, _ in ALL_PROGRAMS:
            _, interference, coloring, _ = self._get_coloring(make_prog)
            for e in interference.edges():
                u, v = e.source, e.target
                if u in coloring and v in coloring:
                    assert coloring[u] != coloring[v], (
                        f"[{name}] {u} and {v} both have color {coloring[u]}"
                    )

    def test_all_variables_colored(self):
        """Every variable in the program must receive a color."""
        for name, make_prog, _ in ALL_PROGRAMS:
            _, _, coloring, variables = self._get_coloring(make_prog)
            for v in variables:
                assert v in coloring, f"[{name}] Variable {v} not colored"

    def test_no_spill_simple(self):
        """Programs with few live variables need no stack spills."""
        num_regs = len(ALLOCATABLE)
        for make_prog in [make_program_1, make_program_2, make_program_3]:
            _, _, coloring, variables = self._get_coloring(make_prog)
            for v in variables:
                assert coloring[v] < num_regs, (
                    f"Variable {v} spilled (color {coloring[v]}) but "
                    f"program has few variables—no spill should be needed"
                )

    def test_spill_required(self):
        """High-pressure program (13 simultaneously live vars, 12 regs) must spill."""
        _, _, coloring, variables = self._get_coloring(make_program_4)
        max_color = max(coloring[v] for v in variables)
        assert max_color >= len(ALLOCATABLE), (
            f"Expected at least one spill (color >= {len(ALLOCATABLE)}), "
            f"but max color is {max_color}"
        )

    def test_registers_pre_colored(self):
        """Physical registers in ALLOCATABLE must have their canonical colors."""
        _, _, coloring, _ = self._get_coloring(make_program_1)
        for i, r in enumerate(ALLOCATABLE):
            reg = Reg(r)
            if reg in coloring:
                assert coloring[reg] == i, (
                    f"Reg({r}) should have color {i}, got {coloring[reg]}"
                )


# ---------------------------------------------------------------------------
# Move biasing tests
# ---------------------------------------------------------------------------

class TestMoveBiasing:
    def test_chain_same_color(self):
        """In program 6, v->w->x are move-related and don't interfere.
        Move biasing should assign them the same color."""
        prog = make_program_6()
        la = uncover_live(prog)
        interference = build_interference(prog, la)
        move_g = build_move_graph(prog)
        variables = variables_in_program(prog)
        coloring = color_graph(interference, move_g, variables)
        assert coloring[Var('v')] == coloring[Var('w')], (
            "v and w are move-related, don't interfere—should share color"
        )
        assert coloring[Var('w')] == coloring[Var('x')], (
            "w and x are move-related, don't interfere—should share color"
        )

    def test_biasing_reduces_moves_program1(self):
        """Program 1 has 4 move-related non-interfering pairs (v-x, x-y, y-t).
        With move biasing, v, x, y, t should share a color -> 3 trivial moves
        removed by patching, leaving at most 9 instructions."""
        prog = make_program_1()
        allocated = allocate_registers(prog)
        total_instrs = sum(len(instrs) for instrs in allocated.blocks.values())
        assert total_instrs <= 9, (
            f"Expected <= 9 instructions after move biasing + patching, "
            f"got {total_instrs}"
        )


# ---------------------------------------------------------------------------
# End-to-end execution tests
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_pre_allocation_execution(self):
        """Sanity: original programs produce correct results in the emulator."""
        for name, make_prog, expected in ALL_PROGRAMS:
            prog = make_prog()
            result = run_program(prog)
            assert result == expected, (
                f"[{name}] Pre-alloc: expected {expected}, got {result}"
            )

    def test_post_allocation_execution(self):
        """Allocated programs must produce the same results as originals."""
        for name, make_prog, expected in ALL_PROGRAMS:
            prog = make_prog()
            allocated = allocate_registers(prog)
            result = run_program(allocated)
            assert result == expected, (
                f"[{name}] Post-alloc: expected {expected}, got {result}"
            )

    def test_no_remaining_vars(self):
        """After allocation, no Var operands should remain in the program."""
        for name, make_prog, _ in ALL_PROGRAMS:
            prog = make_prog()
            allocated = allocate_registers(prog)
            for label, instrs in allocated.blocks.items():
                for instr in instrs:
                    if isinstance(instr, Instr):
                        for arg in instr.args:
                            assert not isinstance(arg, Var), (
                                f"[{name}] Var({arg.name}) still present "
                                f"after allocation in block {label}"
                            )

    def test_no_trivial_moves(self):
        """After patching, no movq X, X instructions should remain."""
        for name, make_prog, _ in ALL_PROGRAMS:
            prog = make_prog()
            allocated = allocate_registers(prog)
            for label, instrs in allocated.blocks.items():
                for instr in instrs:
                    if isinstance(instr, Instr) and instr.name == 'movq':
                        src, dst = instr.args
                        assert src != dst, (
                            f"[{name}] Trivial move {src} -> {dst} in {label}"
                        )

    def test_no_two_memory_operands(self):
        """No binary instruction should have two Deref operands."""
        for name, make_prog, _ in ALL_PROGRAMS:
            prog = make_prog()
            allocated = allocate_registers(prog)
            for label, instrs in allocated.blocks.items():
                for instr in instrs:
                    if isinstance(instr, Instr) and len(instr.args) == 2:
                        src, dst = instr.args
                        assert not (isinstance(src, Deref) and isinstance(dst, Deref)), (
                            f"[{name}] Two memory operands in {instr} "
                            f"in block {label}"
                        )

    def test_stack_space_aligned(self):
        """Stack space for spills must be a multiple of 16."""
        for name, make_prog, _ in ALL_PROGRAMS:
            prog = make_prog()
            allocated = allocate_registers(prog)
            assert allocated.stack_space % 16 == 0, (
                f"[{name}] stack_space={allocated.stack_space} not 16-aligned"
            )

    def test_call_live_vars_callee_saved(self):
        """In program 5, a and b survive the call -> must be in callee-saved
        regs or stack. Verify by running the allocated program."""
        prog = make_program_5()
        allocated = allocate_registers(prog)
        result = run_program(allocated)
        assert result == 300, (
            f"Program 5 post-alloc: expected 300, got {result}. "
            f"Variables live across call likely in caller-saved registers."
        )
