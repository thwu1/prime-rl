"""
test_state.py - Tests for the GVN + load-store forwarding optimizer.

"""
import sys
sys.path.insert(0, "/app")

import pytest
from ir import (
    Function, Block, Instr, Phi, Terminator,
    count_ops, find_instrs, find_phis, interpret,
)
from optimize import compute_rpo, compute_dominators, optimize


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def _diamond():
    """bb0 --(branch)--> bb1, bb2 --(jump)--> bb3"""
    f = Function("diamond", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "const", [1])]
    bb0.term = Terminator("branch", ["a0", "bb1", "bb2"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [Instr("v1", "const", [2])]
    bb1.term = Terminator("jump", ["bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = [Instr("v2", "const", [3])]
    bb2.term = Terminator("jump", ["bb3"])

    bb3 = f.add_block("bb3")
    bb3.phis = [Phi("v3", {"bb1": "v1", "bb2": "v2"})]
    bb3.instrs = []
    bb3.term = Terminator("return", ["v3"])
    return f


def _loop_cfg():
    """
    bb0 -> bb1 (jump)
    bb1 -> bb2, bb3 (branch)
    bb2 -> bb4 (jump)
    bb3 -> bb4 (jump)
    bb4 -> bb5, bb1 (branch — back-edge to bb1)
    bb5 -> return
    """
    f = Function("loop", 1)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "const", [0])]
    bb0.term = Terminator("jump", ["bb1"])

    bb1 = f.add_block("bb1")
    bb1.phis = [Phi("v1", {"bb0": "v0", "bb4": "v5"})]
    bb1.instrs = []
    bb1.term = Terminator("branch", ["a0", "bb2", "bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = [Instr("v2", "const", [1])]
    bb2.term = Terminator("jump", ["bb4"])

    bb3 = f.add_block("bb3")
    bb3.instrs = [Instr("v3", "const", [2])]
    bb3.term = Terminator("jump", ["bb4"])

    bb4 = f.add_block("bb4")
    bb4.phis = [Phi("v4", {"bb2": "v2", "bb3": "v3"})]
    bb4.instrs = [Instr("v5", "add", ["v1", "v4"])]
    bb4.term = Terminator("branch", ["v5", "bb5", "bb1"])

    bb5 = f.add_block("bb5")
    bb5.instrs = []
    bb5.term = Terminator("return", ["v5"])
    return f


# ================================================================== #
#  1.  RPO                                                            #
# ================================================================== #

def test_rpo_diamond():
    f = _diamond()
    rpo = compute_rpo(f)
    assert set(rpo) == {"bb0", "bb1", "bb2", "bb3"}
    pos = {b: i for i, b in enumerate(rpo)}
    # predecessors before successors
    assert pos["bb0"] < pos["bb1"]
    assert pos["bb0"] < pos["bb2"]
    assert pos["bb1"] < pos["bb3"]
    assert pos["bb2"] < pos["bb3"]


def test_rpo_loop():
    f = _loop_cfg()
    rpo = compute_rpo(f)
    assert set(rpo) == {"bb0", "bb1", "bb2", "bb3", "bb4", "bb5"}
    pos = {b: i for i, b in enumerate(rpo)}
    assert pos["bb0"] < pos["bb1"]
    assert pos["bb1"] < pos["bb2"]
    assert pos["bb1"] < pos["bb3"]
    assert pos["bb2"] < pos["bb4"]
    assert pos["bb3"] < pos["bb4"]
    assert pos["bb4"] < pos["bb5"]


# ================================================================== #
#  2.  Dominators                                                     #
# ================================================================== #

def test_dominators_diamond():
    f = _diamond()
    rpo = compute_rpo(f)
    doms = compute_dominators(f, rpo)
    assert doms["bb0"] is None
    assert doms["bb1"] == "bb0"
    assert doms["bb2"] == "bb0"
    assert doms["bb3"] == "bb0"


def test_dominators_loop():
    f = _loop_cfg()
    rpo = compute_rpo(f)
    doms = compute_dominators(f, rpo)
    assert doms["bb0"] is None
    assert doms["bb1"] == "bb0"
    assert doms["bb2"] == "bb1"
    assert doms["bb3"] == "bb1"
    assert doms["bb4"] == "bb1"
    assert doms["bb5"] == "bb4"


# ================================================================== #
#  3.  Local GVN                                                      #
# ================================================================== #

def test_local_gvn():
    """Two identical adds in the same block should be deduplicated."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "add", ["a0", "a1"]),
        Instr("v1", "add", ["a0", "a1"]),
        Instr("v2", "mul", ["v0", "v1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig
    assert count_ops(opt_f, "add") == 1
    mul = find_instrs(opt_f, "mul")[0]
    assert mul.args[0] == mul.args[1]


def test_commutative_gvn():
    """add a0 a1 and add a1 a0 are equivalent."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "add", ["a0", "a1"]),
        Instr("v1", "add", ["a1", "a0"]),
        Instr("v2", "mul", ["v0", "v1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig
    assert count_ops(opt_f, "add") == 1


def test_const_dedup():
    """Two identical const instructions should be deduplicated."""
    f = Function("test", 0)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "const", [42]),
        Instr("v1", "const", [42]),
        Instr("v2", "add", ["v0", "v1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    orig = interpret(f, [])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, []) == orig == 84
    assert count_ops(opt_f, "const") == 1


def test_non_commutative_not_deduped():
    """sub a0 a1 and sub a1 a0 are NOT equivalent."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "sub", ["a0", "a1"]),
        Instr("v1", "sub", ["a1", "a0"]),
        Instr("v2", "add", ["v0", "v1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    opt_f = optimize(f.deep_copy())
    assert count_ops(opt_f, "sub") == 2  # both kept


# ================================================================== #
#  4.  Cross-block GVN                                                #
# ================================================================== #

def test_cross_block_gvn():
    """GVN across a dominator chain (bb0 -> bb1)."""
    f = Function("test", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "add", ["a0", "a1"])]
    bb0.term = Terminator("jump", ["bb1"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [
        Instr("v1", "add", ["a0", "a1"]),
        Instr("v2", "mul", ["v0", "v1"]),
    ]
    bb1.term = Terminator("return", ["v2"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig
    assert count_ops(opt_f, "add") == 1
    mul = find_instrs(opt_f, "mul")[0]
    assert mul.args[0] == mul.args[1]


def test_gvn_dominator_share_diamond():
    """Values from dominator are available in both branches."""
    f = Function("test", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "add", ["a0", "a1"])]
    bb0.term = Terminator("branch", ["a0", "bb1", "bb2"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [Instr("v1", "add", ["a0", "a1"])]
    bb1.term = Terminator("jump", ["bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = [Instr("v2", "add", ["a0", "a1"])]
    bb2.term = Terminator("jump", ["bb3"])

    bb3 = f.add_block("bb3")
    bb3.phis = [Phi("v3", {"bb1": "v1", "bb2": "v2"})]
    bb3.instrs = [Instr("v4", "mul", ["v3", "a0"])]
    bb3.term = Terminator("return", ["v4"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig
    assert count_ops(opt_f, "add") == 1
    # phi becomes trivial (both incoming -> v0)
    assert len(find_phis(opt_f)) == 0


def test_gvn_no_share_siblings():
    """Sibling blocks in a diamond cannot share values."""
    f = Function("test", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "const", [1])]
    bb0.term = Terminator("branch", ["a0", "bb1", "bb2"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [Instr("v1", "mul", ["a0", "a1"])]
    bb1.term = Terminator("jump", ["bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = [Instr("v2", "mul", ["a0", "a1"])]
    bb2.term = Terminator("jump", ["bb3"])

    bb3 = f.add_block("bb3")
    bb3.phis = [Phi("v3", {"bb1": "v1", "bb2": "v2"})]
    bb3.instrs = []
    bb3.term = Terminator("return", ["v3"])

    opt_f = optimize(f.deep_copy())
    # Both muls must remain — neither sibling dominates the other
    assert count_ops(opt_f, "mul") == 2


# ================================================================== #
#  5.  Load-store forwarding                                          #
# ================================================================== #

def test_load_forwarding():
    """Duplicate load should be eliminated."""
    f = Function("test", 1)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "load", ["a0", 0]),
        Instr("v1", "load", ["a0", 0]),
        Instr("v2", "add", ["v0", "v1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    heap = {(100, 0): 42}
    orig = interpret(f, [100], initial_heap=dict(heap))
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [100], initial_heap=dict(heap)) == orig
    assert count_ops(opt_f, "load") == 1
    add_i = find_instrs(opt_f, "add")[0]
    assert add_i.args[0] == add_i.args[1]


def test_store_to_load():
    """Load after store to same (obj, offset) forwards stored value."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "store", ["a0", 0, "a1"]),
        Instr("v1", "load", ["a0", 0]),
        Instr("v2", "add", ["v1", "a1"]),
    ]
    bb.term = Terminator("return", ["v2"])

    orig = interpret(f, [100, 7])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [100, 7]) == orig
    assert count_ops(opt_f, "load") == 0
    add_i = find_instrs(opt_f, "add")[0]
    assert add_i.args[0] == add_i.args[1] == "a1"


def test_alias_invalidation():
    """Store at same offset (different object) must invalidate cache."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "load", ["a0", 0]),
        Instr("v1", "store", ["a1", 0, "v0"]),
        Instr("v2", "load", ["a0", 0]),
        Instr("v3", "add", ["v0", "v2"]),
    ]
    bb.term = Terminator("return", ["v3"])

    opt_f = optimize(f.deep_copy())
    assert count_ops(opt_f, "load") == 2  # second load NOT eliminated


def test_different_offset_no_invalidation():
    """Store at different offset does NOT invalidate cached load."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "load", ["a0", 0]),
        Instr("v1", "store", ["a1", 4, "v0"]),
        Instr("v2", "load", ["a0", 0]),
        Instr("v3", "add", ["v0", "v2"]),
    ]
    bb.term = Terminator("return", ["v3"])

    heap = {(100, 0): 42}
    orig = interpret(f, [100, 200], initial_heap=dict(heap))
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [100, 200], initial_heap=dict(heap)) == orig
    assert count_ops(opt_f, "load") == 1


def test_redundant_store():
    """Store same value already at (obj, offset) should be eliminated."""
    f = Function("test", 1)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "load", ["a0", 0]),
        Instr("v1", "store", ["a0", 0, "v0"]),
    ]
    bb.term = Terminator("return", ["v0"])

    heap = {(100, 0): 42}
    orig = interpret(f, [100], initial_heap=dict(heap))
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [100], initial_heap=dict(heap)) == orig
    assert count_ops(opt_f, "store") == 0


# ================================================================== #
#  6.  Phi elimination                                                #
# ================================================================== #

def test_trivial_phi():
    """Phi where all incoming values are identical is eliminated."""
    f = Function("test", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "add", ["a0", "a1"])]
    bb0.term = Terminator("branch", ["a0", "bb1", "bb2"])

    bb1 = f.add_block("bb1")
    bb1.instrs = []
    bb1.term = Terminator("jump", ["bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = []
    bb2.term = Terminator("jump", ["bb3"])

    bb3 = f.add_block("bb3")
    bb3.phis = [Phi("v1", {"bb1": "v0", "bb2": "v0"})]
    bb3.instrs = [Instr("v2", "mul", ["v1", "a0"])]
    bb3.term = Terminator("return", ["v2"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig
    assert len(find_phis(opt_f)) == 0
    # v1 was forwarded to v0 => mul should reference v0
    mul = find_instrs(opt_f, "mul")[0]
    assert mul.args[0] == "v0"


# ================================================================== #
#  7.  Cross-block heap forwarding                                    #
# ================================================================== #

def test_cross_block_load_forwarding():
    """Load in dominated block uses store from dominator's heap cache."""
    f = Function("test", 2)
    bb0 = f.add_block("bb0")
    bb0.instrs = [Instr("v0", "store", ["a0", 0, "a1"])]
    bb0.term = Terminator("jump", ["bb1"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [
        Instr("v1", "load", ["a0", 0]),
        Instr("v2", "add", ["v1", "a1"]),
    ]
    bb1.term = Terminator("return", ["v2"])

    orig = interpret(f, [100, 7])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [100, 7]) == orig
    assert count_ops(opt_f, "load") == 0


# ================================================================== #
#  8.  Side-effect clears cache                                       #
# ================================================================== #

def test_call_clears_heap():
    """A call instruction must clear the heap cache."""
    f = Function("test", 1)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "load", ["a0", 0]),
        Instr("v1", "call", ["some_func", "v0"]),
        Instr("v2", "load", ["a0", 0]),
        Instr("v3", "add", ["v0", "v2"]),
    ]
    bb.term = Terminator("return", ["v3"])

    opt_f = optimize(f.deep_copy())
    assert count_ops(opt_f, "load") == 2  # second load NOT eliminated


# ================================================================== #
#  9.  Terminator resolution                                          #
# ================================================================== #

def test_terminator_resolution():
    """Terminator operands must be resolved through canonical mapping."""
    f = Function("test", 2)
    bb = f.add_block("bb0")
    bb.instrs = [
        Instr("v0", "add", ["a0", "a1"]),
        Instr("v1", "add", ["a0", "a1"]),
    ]
    bb.term = Terminator("return", ["v1"])

    opt_f = optimize(f.deep_copy())
    assert opt_f.blocks["bb0"].term.args[0] == "v0"


# ================================================================== #
#  10. Combined complex test                                          #
# ================================================================== #

def test_combined():
    """Large test exercising GVN, load-store forwarding, and phi elim."""
    f = Function("test", 2)

    bb0 = f.add_block("bb0")
    bb0.instrs = [
        Instr("v0", "add", ["a0", "a1"]),
        Instr("v1", "const", [1]),
        Instr("v2", "store", ["a0", 0, "v1"]),
    ]
    bb0.term = Terminator("branch", ["a0", "bb1", "bb2"])

    bb1 = f.add_block("bb1")
    bb1.instrs = [
        Instr("v3", "add", ["a0", "a1"]),   # GVN  -> v0
        Instr("v4", "load", ["a0", 0]),      # LSF  -> v1
    ]
    bb1.term = Terminator("jump", ["bb3"])

    bb2 = f.add_block("bb2")
    bb2.instrs = [
        Instr("v5", "add", ["a0", "a1"]),   # GVN  -> v0
        Instr("v6", "load", ["a0", 0]),      # LSF  -> v1
    ]
    bb2.term = Terminator("jump", ["bb3"])

    bb3 = f.add_block("bb3")
    # v3->v0, v5->v0  =>  phi trivial  =>  v7->v0
    bb3.phis = [Phi("v7", {"bb1": "v3", "bb2": "v5"})]
    bb3.instrs = [
        Instr("v8", "add", ["a0", "a1"]),   # GVN  -> v0
        Instr("v9", "mul", ["v7", "v8"]),    # after resolution: mul v0 v0
    ]
    bb3.term = Terminator("return", ["v9"])

    orig = interpret(f, [3, 5])
    opt_f = optimize(f.deep_copy())
    assert interpret(opt_f, [3, 5]) == orig

    assert count_ops(opt_f, "add") == 1
    assert count_ops(opt_f, "load") == 0
    assert len(find_phis(opt_f)) == 0

    mul = find_instrs(opt_f, "mul")[0]
    assert mul.args[0] == mul.args[1]  # both v0
