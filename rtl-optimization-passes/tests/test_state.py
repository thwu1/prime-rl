"""
Tests for RTL optimization passes.

Verifies structural properties (specific transformations applied)
and semantic preservation (interpreter produces identical results).

"""

import sys
sys.path.insert(0, '/app')

import pytest
from rtl import (
    Function, Inop, Iop, Icond, Ireturn,
    load_function, interpret, deep_copy_function,
)
from passes import constant_propagation, dead_code_elimination, branch_tunneling
from pipeline import run_pipeline


def load_prog(name):
    return load_function(f'/app/programs/{name}.json')


# ============================================================
# Constant propagation tests
# ============================================================

class TestConstantPropagation:

    def test_basic_constprop(self):
        """r1=5, r2=3, r3=add(r1,r2) => r3 should fold to const 8."""
        func = load_prog('basic_constprop')
        result = constant_propagation(func)
        assert interpret(result, []) == 8
        instr = result.code[3]
        assert isinstance(instr, Iop), f"Expected Iop, got {type(instr).__name__}"
        assert instr.op == "const", f"Expected const, got {instr.op}"
        assert instr.imm == 8, f"Expected imm=8, got {instr.imm}"

    def test_chain_constprop(self):
        """Chained computations should all fold: 2*3=6, 6+4=10, 10*10=100."""
        func = load_prog('chain_constprop')
        result = constant_propagation(func)
        assert interpret(result, []) == 100
        assert result.code[3].op == "const" and result.code[3].imm == 6
        assert result.code[5].op == "const" and result.code[5].imm == 10
        assert result.code[6].op == "const" and result.code[6].imm == 100

    def test_cond_constprop(self):
        """Branch cond lt(3,5) is always true => Icond becomes Inop(4)."""
        func = load_prog('cond_constprop')
        result = constant_propagation(func)
        assert interpret(result, []) == 1
        instr = result.code[3]
        assert isinstance(instr, Inop), (
            f"Expected Inop (resolved branch), got {type(instr).__name__}"
        )
        assert instr.succ == 4, f"Expected succ=4 (true branch), got {instr.succ}"

    def test_diamond_constprop(self):
        """Both branches assign r2=10, so at the merge r3=add(r2,r2)=20."""
        func = load_prog('diamond_constprop')
        result = constant_propagation(func)
        for x in [-5, 0, 5, 100]:
            assert interpret(result, [x]) == 20, (
                f"Failed semantic preservation for input {x}"
            )
        instr = result.code[5]
        assert isinstance(instr, Iop)
        assert instr.op == "const" and instr.imm == 20, (
            f"Expected const 20, got {instr.op} imm={instr.imm}"
        )


# ============================================================
# Dead code elimination tests
# ============================================================

class TestDeadCodeElimination:

    def test_dead_code_basic(self):
        """r2 and r4 are never used => their definitions become Inop."""
        func = load_prog('dead_code')
        result = dead_code_elimination(func)
        assert interpret(result, [5]) == 100
        assert interpret(result, [0]) == 0
        assert isinstance(result.code[2], Inop), (
            f"Node 2 should be Inop (dead r2), got {type(result.code[2]).__name__}"
        )
        assert isinstance(result.code[4], Inop), (
            f"Node 4 should be Inop (dead r4), got {type(result.code[4]).__name__}"
        )

    def test_multi_dead_cascade(self):
        """r5 is dead => r3,r4 become dead cascading. Pipeline handles this."""
        func = load_prog('multi_dead')
        result = run_pipeline(func)
        assert interpret(result, [3]) == 8
        assert interpret(result, [0]) == 5
        for n in [3, 4, 5]:
            if n in result.code:
                assert isinstance(result.code[n], Inop), (
                    f"Node {n} should be dead (Inop or removed)"
                )


# ============================================================
# Branch tunneling tests
# ============================================================

class TestBranchTunneling:

    def test_branch_tunnel_chain(self):
        """Nop chain 2->3->4->5 should be tunneled: node 1 jumps to 6."""
        func = load_prog('branch_tunnel')
        result = branch_tunneling(func)
        assert interpret(result, []) == 42
        instr = result.code[1]
        assert isinstance(instr, Iop)
        assert instr.succ == 6, (
            f"Expected node 1 to tunnel to 6, got {instr.succ}"
        )

    def test_tunnel_preserves_non_nop(self):
        """Tunneling should not skip non-Inop instructions."""
        func = load_prog('basic_constprop')
        result = branch_tunneling(func)
        assert interpret(result, []) == 8
        assert result.code[1].succ == 2


# ============================================================
# Combined pipeline tests
# ============================================================

class TestPipeline:

    def test_combined_simple(self):
        """All passes interact: constprop folds values and resolves branch,
        DCE removes dead code, tunneling collapses nop chains."""
        func = load_prog('combined_simple')
        result = run_pipeline(func)
        assert interpret(result, []) == 24
        instr = result.code[7]
        assert isinstance(instr, Iop)
        assert instr.op == "const" and instr.imm == 24, (
            f"Expected node 7 to be const 24, got {instr.op} imm={instr.imm}"
        )
        reachable = result.reachable_nodes()
        assert len(reachable) < 12, (
            f"Expected fewer than 12 reachable nodes after optimization, got {len(reachable)}"
        )

    def test_loop_program(self):
        """Loop program should preserve semantics and eliminate dead r5."""
        func = load_prog('loop_program')
        result = run_pipeline(func)
        assert interpret(result, []) == 5
        if 9 in result.code:
            assert isinstance(result.code[9], Inop), (
                "Node 9 (dead r5) should be Inop after DCE"
            )

    def test_pipeline_idempotent(self):
        """Running the pipeline twice should produce the same result."""
        for name in ['basic_constprop', 'combined_simple', 'loop_program']:
            func = load_prog(name)
            once = run_pipeline(func)
            twice = run_pipeline(once)
            assert once.to_json() == twice.to_json(), (
                f"Pipeline not idempotent on {name}"
            )


# ============================================================
# Comprehensive semantic preservation
# ============================================================

class TestSemanticPreservation:

    @pytest.mark.parametrize("name,args,expected", [
        ("basic_constprop", [], 8),
        ("chain_constprop", [], 100),
        ("cond_constprop", [], 1),
        ("dead_code", [5], 100),
        ("dead_code", [0], 0),
        ("dead_code", [-3], 36),
        ("multi_dead", [3], 8),
        ("multi_dead", [0], 5),
        ("multi_dead", [-10], -5),
        ("branch_tunnel", [], 42),
        ("diamond_constprop", [10], 20),
        ("diamond_constprop", [-3], 20),
        ("diamond_constprop", [0], 20),
        ("combined_simple", [], 24),
        ("loop_program", [], 5),
    ])
    def test_semantic_preservation(self, name, args, expected):
        """Optimized program must produce same result as original."""
        func = load_prog(name)
        orig_result = interpret(func, args)
        assert orig_result == expected, (
            f"{name}({args}): original expected {expected}, got {orig_result}"
        )
        optimized = run_pipeline(func)
        opt_result = interpret(optimized, args)
        assert opt_result == expected, (
            f"{name}({args}): optimized expected {expected}, got {opt_result}"
        )

    def test_individual_pass_preservation(self):
        """Each individual pass must preserve semantics independently."""
        test_cases = [
            ("basic_constprop", [], 8),
            ("dead_code", [5], 100),
            ("branch_tunnel", [], 42),
            ("diamond_constprop", [7], 20),
            ("loop_program", [], 5),
        ]
        for name, args, expected in test_cases:
            func = load_prog(name)
            cp = constant_propagation(deep_copy_function(func))
            assert interpret(cp, args) == expected, (
                f"constprop broke semantics on {name}"
            )
            dce = dead_code_elimination(deep_copy_function(func))
            assert interpret(dce, args) == expected, (
                f"DCE broke semantics on {name}"
            )
            bt = branch_tunneling(deep_copy_function(func))
            assert interpret(bt, args) == expected, (
                f"tunneling broke semantics on {name}"
            )
