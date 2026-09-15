"""
Verification tests for the Proof Decomposition Engine.


These tests verify the correctness of the engine implementation
by checking outputs against known-good results.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, "/app")

import pytest
from proof_engine.engine import (
    build_proof_tree,
    validate_decomposition,
    compute_schedule,
    get_proof_report,
    generate_obligations,
    compute_cone_of_influence,
    check_compositional_soundness,
)
from proof_engine.models import (
    ValidationError,
    CyclicDependencyError,
    Strategy,
    ProofTree,
    ProofReport,
    Obligation,
    ConeInfo,
    SoundnessReport,
    SoundnessIssue,
)


# ============================================================
# Spec builders
# ============================================================

def make_ag_acyclic():
    return {
        "properties": {
            "top": {
                "expression": "G(req -> F ack)",
                "signals": ["req", "ack", "clk"],
                "temporal_depth": 10,
            }
        },
        "signal_dependencies": {
            "req": [],
            "ack": ["req", "clk"],
            "clk": [],
        },
        "decompositions": [
            {
                "strategy": "assume_guarantee",
                "target": "top",
                "params": {
                    "sub_properties": {
                        "sp_a": {
                            "expression": "G(req -> X pending)",
                            "assumes": ["sp_c"],
                        },
                        "sp_b": {
                            "expression": "G(pending -> F ack)",
                            "assumes": ["sp_a"],
                        },
                        "sp_c": {
                            "expression": "G(clk -> X clk)",
                            "assumes": [],
                        },
                    }
                },
            }
        ],
    }


def make_ag_cyclic():
    return {
        "properties": {
            "prop": {
                "expression": "G(a -> F b)",
                "signals": ["a", "b"],
                "temporal_depth": 5,
            }
        },
        "signal_dependencies": {"a": [], "b": ["a"]},
        "decompositions": [
            {
                "strategy": "assume_guarantee",
                "target": "prop",
                "params": {
                    "sub_properties": {
                        "x": {"expression": "G(a)", "assumes": ["y"]},
                        "y": {"expression": "G(b)", "assumes": ["z"]},
                        "z": {"expression": "G(a&b)", "assumes": ["x"]},
                    }
                },
            }
        ],
    }


def make_ag_linear_chain():
    """Linear chain: d->c->b->a (no cycles, long chain)."""
    return {
        "properties": {
            "chain": {
                "expression": "G(s)",
                "signals": ["s"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {"s": []},
        "decompositions": [
            {
                "strategy": "assume_guarantee",
                "target": "chain",
                "params": {
                    "sub_properties": {
                        "a": {"expression": "G(s1)", "assumes": []},
                        "b": {"expression": "G(s2)", "assumes": ["a"]},
                        "c": {"expression": "G(s3)", "assumes": ["b"]},
                        "d": {"expression": "G(s4)", "assumes": ["c"]},
                    }
                },
            }
        ],
    }


def make_case_split_valid_3vars():
    """3-variable case split that is exhaustive and exclusive."""
    return {
        "properties": {
            "p": {
                "expression": "G(x)",
                "signals": ["a", "b", "c"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {"a": [], "b": [], "c": []},
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "p",
                "params": {
                    "cases": [
                        {"name": "c1", "predicate": "a & b & c"},
                        {"name": "c2", "predicate": "a & b & ~c"},
                        {"name": "c3", "predicate": "a & ~b & c"},
                        {"name": "c4", "predicate": "a & ~b & ~c"},
                        {"name": "c5", "predicate": "~a & b & c"},
                        {"name": "c6", "predicate": "~a & b & ~c"},
                        {"name": "c7", "predicate": "~a & ~b & c"},
                        {"name": "c8", "predicate": "~a & ~b & ~c"},
                    ]
                },
            }
        ],
    }


def make_case_split_not_exhaustive():
    return {
        "properties": {
            "p": {
                "expression": "G(x)",
                "signals": ["a", "b"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {"a": [], "b": []},
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "p",
                "params": {
                    "cases": [
                        {"name": "c1", "predicate": "a & b"},
                        {"name": "c2", "predicate": "a & ~b"},
                        {"name": "c3", "predicate": "~a & b"},
                        # Missing: ~a & ~b
                    ]
                },
            }
        ],
    }


def make_case_split_not_exclusive():
    return {
        "properties": {
            "p": {
                "expression": "G(x)",
                "signals": ["a", "b"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {"a": [], "b": []},
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "p",
                "params": {
                    "cases": [
                        {"name": "c1", "predicate": "a"},
                        {"name": "c2", "predicate": "b"},
                        {"name": "c3", "predicate": "~a & ~b"},
                    ]
                },
            }
        ],
    }


def make_case_split_single_var():
    return {
        "properties": {
            "p": {
                "expression": "G(x)",
                "signals": ["v"],
                "temporal_depth": 2,
            }
        },
        "signal_dependencies": {"v": []},
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "p",
                "params": {
                    "cases": [
                        {"name": "pos", "predicate": "v"},
                        {"name": "neg", "predicate": "~v"},
                    ]
                },
            }
        ],
    }


def make_partition_valid():
    return {
        "properties": {
            "bus": {
                "expression": "G(valid -> ok)",
                "signals": ["valid", "ok", "addr", "ctrl", "clk",
                            "a_in", "b_in", "c_in", "d_in"],
                "temporal_depth": 6,
            }
        },
        "signal_dependencies": {
            "valid": ["addr", "ctrl"],
            "ok": ["d_in"],
            "addr": ["a_in", "clk"],
            "ctrl": ["c_in", "clk"],
            "clk": [],
            "a_in": [],
            "b_in": [],
            "c_in": [],
            "d_in": ["b_in"],
        },
        "decompositions": [
            {
                "strategy": "partition",
                "target": "bus",
                "params": {
                    "cut_signals": ["clk"],
                    "partitions": [
                        {"name": "addr_p", "root_signals": ["addr"]},
                        {"name": "data_p", "root_signals": ["ok"]},
                    ],
                },
            }
        ],
    }


def make_partition_overlap():
    return {
        "properties": {
            "p": {
                "expression": "G(a -> b)",
                "signals": ["a", "b", "shared", "x", "y"],
                "temporal_depth": 3,
            }
        },
        "signal_dependencies": {
            "a": ["shared", "x"],
            "b": ["shared", "y"],
            "shared": [],
            "x": [],
            "y": [],
        },
        "decompositions": [
            {
                "strategy": "partition",
                "target": "p",
                "params": {
                    "cut_signals": [],
                    "partitions": [
                        {"name": "pa", "root_signals": ["a"]},
                        {"name": "pb", "root_signals": ["b"]},
                    ],
                },
            }
        ],
    }


def make_stopat_valid():
    return {
        "properties": {
            "deep": {
                "expression": "G[0:20](req -> F[0:20] ack)",
                "signals": ["req", "ack"],
                "temporal_depth": 20,
            }
        },
        "signal_dependencies": {
            "req": [],
            "ack": ["m1"],
            "m1": ["m2"],
            "m2": ["m3"],
            "m3": ["src"],
            "src": [],
        },
        "decompositions": [
            {
                "strategy": "stopat",
                "target": "deep",
                "params": {
                    "depth_limit": 2,
                    "free_variable_prefix": "fv_",
                },
            }
        ],
    }


def make_helper_valid():
    return {
        "properties": {
            "main": {
                "expression": "G(req -> F ack)",
                "signals": ["req", "ack"],
                "temporal_depth": 10,
            },
            "h1": {
                "expression": "G(ack -> X idle)",
                "signals": ["ack", "idle"],
                "temporal_depth": 5,
            },
            "h2": {
                "expression": "G(idle -> ready)",
                "signals": ["idle", "ready"],
                "temporal_depth": 3,
            },
        },
        "signal_dependencies": {
            "req": [],
            "ack": ["req"],
            "idle": ["ack"],
            "ready": ["idle"],
        },
        "decompositions": [
            {
                "strategy": "helper_invariant",
                "target": "main",
                "params": {
                    "helpers": ["h1", "h2"],
                    "target": "main",
                },
            }
        ],
    }


def make_helper_circular():
    return {
        "properties": {
            "pa": {
                "expression": "G(a)",
                "signals": ["a"],
                "temporal_depth": 5,
            },
            "pb": {
                "expression": "G(b)",
                "signals": ["b"],
                "temporal_depth": 5,
            },
        },
        "signal_dependencies": {"a": [], "b": []},
        "decompositions": [
            {
                "strategy": "helper_invariant",
                "target": "pa",
                "params": {"helpers": ["pb"], "target": "pa"},
            },
            {
                "strategy": "helper_invariant",
                "target": "pb",
                "params": {"helpers": ["pa"], "target": "pb"},
            },
        ],
    }


def make_stopat_depth_inconsistent():
    """Stopat with depth_limit exceeding cone sequential depth."""
    return {
        "properties": {
            "short": {
                "expression": "G[0:10](a -> F[0:10] b)",
                "signals": ["a", "b"],
                "temporal_depth": 10,
            }
        },
        "signal_dependencies": {
            "a": [],
            "b": ["mid"],
            "mid": ["a"],
        },
        "decompositions": [
            {
                "strategy": "stopat",
                "target": "short",
                "params": {
                    "depth_limit": 5,
                    "free_variable_prefix": "fv_",
                },
            }
        ],
    }


def make_case_split_non_primary():
    """Case split using non-primary (derived) signal as split variable."""
    return {
        "properties": {
            "p": {
                "expression": "G(x)",
                "signals": ["a", "out"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {
            "a": [],
            "out": ["a"],
        },
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "p",
                "params": {
                    "cases": [
                        {"name": "c1", "predicate": "out"},
                        {"name": "c2", "predicate": "~out"},
                    ]
                },
            }
        ],
    }


# ============================================================
# build_proof_tree tests
# ============================================================

class TestBuildTree:
    def test_builds_valid_ag(self):
        tree = build_proof_tree(make_ag_acyclic())
        assert isinstance(tree, ProofTree)
        assert "top" in tree.properties
        assert tree.decompositions[0].strategy == Strategy.ASSUME_GUARANTEE

    def test_builds_valid_case_split(self):
        tree = build_proof_tree(make_case_split_valid_3vars())
        assert tree.decompositions[0].strategy == Strategy.CASE_SPLIT

    def test_builds_valid_partition(self):
        tree = build_proof_tree(make_partition_valid())
        assert tree.decompositions[0].strategy == Strategy.PARTITION

    def test_builds_valid_stopat(self):
        tree = build_proof_tree(make_stopat_valid())
        assert tree.decompositions[0].strategy == Strategy.STOPAT

    def test_builds_valid_helper(self):
        tree = build_proof_tree(make_helper_valid())
        assert tree.decompositions[0].strategy == Strategy.HELPER_INVARIANT

    def test_rejects_missing_properties(self):
        with pytest.raises(ValidationError):
            build_proof_tree({"signal_dependencies": {}, "decompositions": []})

    def test_rejects_missing_decompositions(self):
        with pytest.raises(ValidationError):
            build_proof_tree({"properties": {}, "signal_dependencies": {}})

    def test_rejects_bad_strategy(self):
        spec = make_ag_acyclic()
        spec["decompositions"][0]["strategy"] = "bogus"
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_rejects_bad_target(self):
        spec = make_ag_acyclic()
        spec["decompositions"][0]["target"] = "no_such_prop"
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_rejects_missing_expression(self):
        spec = make_ag_acyclic()
        del spec["properties"]["top"]["expression"]
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_rejects_missing_signals(self):
        spec = make_ag_acyclic()
        del spec["properties"]["top"]["signals"]
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_rejects_missing_temporal_depth(self):
        spec = make_ag_acyclic()
        del spec["properties"]["top"]["temporal_depth"]
        with pytest.raises(ValidationError):
            build_proof_tree(spec)


# ============================================================
# Assume-Guarantee validation tests
# ============================================================

class TestAGValidation:
    def test_acyclic_is_valid(self):
        tree = build_proof_tree(make_ag_acyclic())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True

    def test_acyclic_order(self):
        tree = build_proof_tree(make_ag_acyclic())
        r = validate_decomposition(tree, 0)
        order = r.details["verification_order"]
        assert order.index("sp_c") < order.index("sp_a")
        assert order.index("sp_a") < order.index("sp_b")

    def test_cyclic_is_invalid(self):
        tree = build_proof_tree(make_ag_cyclic())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False
        assert any("cycl" in e.lower() for e in r.errors)

    def test_linear_chain_order(self):
        tree = build_proof_tree(make_ag_linear_chain())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        order = r.details["verification_order"]
        assert order == ["a", "b", "c", "d"]


# ============================================================
# Case Split validation tests
# ============================================================

class TestCaseSplitValidation:
    def test_valid_3vars(self):
        tree = build_proof_tree(make_case_split_valid_3vars())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        assert set(r.details["variables"]) == {"a", "b", "c"}
        assert r.details["num_cases"] == 8

    def test_valid_single_var(self):
        tree = build_proof_tree(make_case_split_single_var())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        assert r.details["num_cases"] == 2

    def test_not_exhaustive(self):
        tree = build_proof_tree(make_case_split_not_exhaustive())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False
        assert any("exhaustive" in e.lower() for e in r.errors)

    def test_not_exclusive(self):
        tree = build_proof_tree(make_case_split_not_exclusive())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False
        assert any("exclusive" in e.lower() or "overlap" in e.lower()
                    for e in r.errors)


# ============================================================
# Partition validation tests
# ============================================================

class TestPartitionValidation:
    def test_valid_disjoint(self):
        tree = build_proof_tree(make_partition_valid())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        cones = r.details["fanin_cones"]
        assert set(cones["addr_p"]) & set(cones["data_p"]) == set()
        # addr -> a_in (after cutting clk)
        assert "a_in" in cones["addr_p"]
        # ok -> d_in -> b_in
        assert "d_in" in cones["data_p"]
        assert "b_in" in cones["data_p"]

    def test_overlap_detected(self):
        tree = build_proof_tree(make_partition_overlap())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False
        assert any("overlap" in e.lower() or "disjoint" in e.lower()
                    for e in r.errors)


# ============================================================
# Stopat validation tests
# ============================================================

class TestStopatValidation:
    def test_valid(self):
        tree = build_proof_tree(make_stopat_valid())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        assert r.details["original_depth"] == 20
        assert r.details["rewritten_depth"] == 2
        fvs = r.details["free_variables"]
        assert len(fvs) > 0
        assert all(fv.startswith("fv_") for fv in fvs)

    def test_depth_too_large(self):
        spec = make_stopat_valid()
        spec["decompositions"][0]["params"]["depth_limit"] = 25
        tree = build_proof_tree(spec)
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False

    def test_depth_zero(self):
        spec = make_stopat_valid()
        spec["decompositions"][0]["params"]["depth_limit"] = 0
        tree = build_proof_tree(spec)
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False

    def test_depth_equal_to_temporal(self):
        spec = make_stopat_valid()
        spec["decompositions"][0]["params"]["depth_limit"] = 20
        tree = build_proof_tree(spec)
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False


# ============================================================
# Helper Invariant validation tests
# ============================================================

class TestHelperValidation:
    def test_valid(self):
        tree = build_proof_tree(make_helper_valid())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is True
        order = r.details["dependency_order"]
        assert order.index("h1") < order.index("main")
        assert order.index("h2") < order.index("main")

    def test_circular(self):
        tree = build_proof_tree(make_helper_circular())
        r = validate_decomposition(tree, 0)
        assert r.is_valid is False
        assert any("cycl" in e.lower() or "circular" in e.lower()
                    for e in r.errors)


# ============================================================
# Global scheduling tests
# ============================================================

class TestGlobalSchedule:
    def test_ag_schedule(self):
        tree = build_proof_tree(make_ag_acyclic())
        sched = compute_schedule(tree)
        assert isinstance(sched, list)
        # sp_c before sp_a before sp_b
        if "sp_c" in sched and "sp_a" in sched and "sp_b" in sched:
            assert sched.index("sp_c") < sched.index("sp_a")
            assert sched.index("sp_a") < sched.index("sp_b")

    def test_cyclic_raises(self):
        tree = build_proof_tree(make_ag_cyclic())
        with pytest.raises(CyclicDependencyError):
            compute_schedule(tree)

    def test_helper_schedule(self):
        tree = build_proof_tree(make_helper_valid())
        sched = compute_schedule(tree)
        # helpers must precede main
        for h in ["h1", "h2"]:
            if h in sched:
                assert sched.index(h) < sched.index("main")

    def test_mixed_strategies(self):
        """Combine helper + AG on helper."""
        spec = make_helper_valid()
        spec["decompositions"].append({
            "strategy": "assume_guarantee",
            "target": "h1",
            "params": {
                "sub_properties": {
                    "h1a": {"expression": "G(a)", "assumes": []},
                    "h1b": {"expression": "G(b)", "assumes": ["h1a"]},
                }
            },
        })
        tree = build_proof_tree(spec)
        sched = compute_schedule(tree)
        assert sched.index("h1a") < sched.index("h1b")


# ============================================================
# Proof report tests
# ============================================================

class TestReport:
    def test_valid_report(self):
        tree = build_proof_tree(make_ag_acyclic())
        report = get_proof_report(tree)
        assert isinstance(report, ProofReport)
        assert report.has_errors is False
        assert len(report.global_schedule) > 0

    def test_errored_report(self):
        tree = build_proof_tree(make_ag_cyclic())
        report = get_proof_report(tree)
        assert report.has_errors is True

    def test_report_entries(self):
        tree = build_proof_tree(make_case_split_valid_3vars())
        report = get_proof_report(tree)
        decomposed = [e for e in report.entries if e.strategy is not None]
        assert len(decomposed) > 0
        assert decomposed[0].strategy == "case_split"

    def test_report_schedule_order(self):
        tree = build_proof_tree(make_helper_valid())
        report = get_proof_report(tree)
        # Entries should have schedule_order assigned
        ordered = [e for e in report.entries if e.schedule_order is not None]
        assert len(ordered) > 0


# ============================================================
# Obligation generation tests
# ============================================================

class TestObligationGeneration:
    def test_ag_obligations_count(self):
        tree = build_proof_tree(make_ag_acyclic())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 3

    def test_ag_obligations_order(self):
        """AG obligations must be in verification order."""
        tree = build_proof_tree(make_ag_acyclic())
        obls = generate_obligations(tree, 0)
        names = [o.name for o in obls]
        assert names.index("sp_c") < names.index("sp_a")
        assert names.index("sp_a") < names.index("sp_b")

    def test_ag_obligations_assumptions(self):
        """AG obligations carry assumed sub-property expressions."""
        tree = build_proof_tree(make_ag_acyclic())
        obls = generate_obligations(tree, 0)
        obl_map = {o.name: o for o in obls}
        # sp_c has no assumptions
        assert obl_map["sp_c"].assumptions == []
        # sp_a assumes sp_c -> carries sp_c's expression
        assert len(obl_map["sp_a"].assumptions) == 1
        assert obl_map["sp_a"].assumptions[0] == "G(clk -> X clk)"
        # sp_b assumes sp_a -> carries sp_a's expression
        assert len(obl_map["sp_b"].assumptions) == 1
        assert obl_map["sp_b"].assumptions[0] == "G(req -> X pending)"

    def test_ag_obligations_type(self):
        tree = build_proof_tree(make_ag_acyclic())
        obls = generate_obligations(tree, 0)
        for o in obls:
            assert isinstance(o, Obligation)
            assert o.source_strategy == "assume_guarantee"

    def test_ag_linear_chain_obligations(self):
        """Linear chain AG should produce 4 obligations in order a,b,c,d."""
        tree = build_proof_tree(make_ag_linear_chain())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 4
        names = [o.name for o in obls]
        assert names == ["a", "b", "c", "d"]
        # a has no assumptions
        assert obls[0].assumptions == []
        # b assumes a's expression
        assert obls[1].assumptions == ["G(s1)"]
        # c assumes b's expression
        assert obls[2].assumptions == ["G(s2)"]
        # d assumes c's expression
        assert obls[3].assumptions == ["G(s3)"]

    def test_case_split_obligations_count(self):
        tree = build_proof_tree(make_case_split_valid_3vars())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 8

    def test_case_split_obligations_guard(self):
        """Case split obligations have predicate-guarded expressions."""
        tree = build_proof_tree(make_case_split_single_var())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 2
        for o in obls:
            assert "->" in o.expression
            assert "G(x)" in o.expression
            assert o.source_strategy == "case_split"

    def test_case_split_obligations_env(self):
        """Case split obligations include predicate variables in environment."""
        tree = build_proof_tree(make_case_split_valid_3vars())
        obls = generate_obligations(tree, 0)
        for o in obls:
            assert "a" in o.environment
            assert "b" in o.environment
            assert "c" in o.environment

    def test_partition_obligations_count(self):
        tree = build_proof_tree(make_partition_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 2

    def test_partition_obligations_env_disjoint(self):
        """Partition obligations have disjoint environments (after cut)."""
        tree = build_proof_tree(make_partition_valid())
        obls = generate_obligations(tree, 0)
        env0 = set(obls[0].environment)
        env1 = set(obls[1].environment)
        assert env0 & env1 == set()

    def test_partition_obligations_strategy(self):
        tree = build_proof_tree(make_partition_valid())
        obls = generate_obligations(tree, 0)
        for o in obls:
            assert o.source_strategy == "partition"
            assert o.assumptions == []

    def test_stopat_obligations_rewrite(self):
        """Stopat obligation rewrites bounded temporal operators."""
        tree = build_proof_tree(make_stopat_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 1
        obl = obls[0]
        assert "G[0:2]" in obl.expression
        assert "F[0:2]" in obl.expression
        assert "G[0:20]" not in obl.expression

    def test_stopat_obligations_name(self):
        tree = build_proof_tree(make_stopat_valid())
        obls = generate_obligations(tree, 0)
        assert obls[0].name == "deep_bounded"
        assert obls[0].source_strategy == "stopat"

    def test_helper_obligations_count(self):
        tree = build_proof_tree(make_helper_valid())
        obls = generate_obligations(tree, 0)
        # 2 helpers + 1 target = 3
        assert len(obls) == 3

    def test_helper_obligations_target_assumes(self):
        """Target obligation assumes all helper expressions."""
        tree = build_proof_tree(make_helper_valid())
        obls = generate_obligations(tree, 0)
        target_obl = [o for o in obls if o.name == "main"][0]
        assert len(target_obl.assumptions) == 2
        assert "G(ack -> X idle)" in target_obl.assumptions
        assert "G(idle -> ready)" in target_obl.assumptions

    def test_helper_obligations_helpers_no_assumptions(self):
        """Helper obligations have no assumptions."""
        tree = build_proof_tree(make_helper_valid())
        obls = generate_obligations(tree, 0)
        helper_obls = [o for o in obls if o.name != "main"]
        assert len(helper_obls) == 2
        for o in helper_obls:
            assert o.assumptions == []
            assert o.source_strategy == "helper_invariant"


# ============================================================
# Cone of Influence tests
# ============================================================

class TestConeOfInfluence:
    def test_simple_cone(self):
        """AG property with all signals declared - cone equals signals."""
        tree = build_proof_tree(make_ag_acyclic())
        cone = compute_cone_of_influence(tree, "top")
        assert isinstance(cone, ConeInfo)
        assert set(cone.structural_cone) == {"req", "ack", "clk"}
        assert cone.sequential_depth == 0
        assert set(cone.boundary_signals) == {"req", "clk"}

    def test_helper_cone_main(self):
        """Main property cone is just its own signals."""
        tree = build_proof_tree(make_helper_valid())
        cone = compute_cone_of_influence(tree, "main")
        assert set(cone.structural_cone) == {"req", "ack"}
        assert cone.sequential_depth == 0
        assert cone.boundary_signals == ["req"]

    def test_helper_cone_h1(self):
        """h1 cone extends to req (one hop beyond ack)."""
        tree = build_proof_tree(make_helper_valid())
        cone = compute_cone_of_influence(tree, "h1")
        assert set(cone.structural_cone) == {"ack", "idle", "req"}
        assert cone.sequential_depth == 1
        assert cone.boundary_signals == ["req"]

    def test_helper_cone_h2(self):
        """h2 cone extends deeply through dependency chain."""
        tree = build_proof_tree(make_helper_valid())
        cone = compute_cone_of_influence(tree, "h2")
        assert set(cone.structural_cone) == {"ack", "idle", "ready", "req"}
        assert cone.sequential_depth == 2
        assert cone.boundary_signals == ["req"]

    def test_partition_cone_all_signals(self):
        """Property declaring all signals has seq_depth 0."""
        tree = build_proof_tree(make_partition_valid())
        cone = compute_cone_of_influence(tree, "bus")
        assert len(cone.structural_cone) == 9
        assert cone.sequential_depth == 0
        assert set(cone.boundary_signals) == {"a_in", "b_in", "c_in", "clk"}

    def test_stopat_cone_deep(self):
        """Stopat property cone extends far through dependency chain."""
        tree = build_proof_tree(make_stopat_valid())
        cone = compute_cone_of_influence(tree, "deep")
        assert "req" in cone.structural_cone
        assert "ack" in cone.structural_cone
        assert "m1" in cone.structural_cone
        assert "m2" in cone.structural_cone
        assert "m3" in cone.structural_cone
        assert "src" in cone.structural_cone
        assert cone.sequential_depth == 4
        assert set(cone.boundary_signals) == {"req", "src"}

    def test_cone_property_name(self):
        tree = build_proof_tree(make_ag_acyclic())
        cone = compute_cone_of_influence(tree, "top")
        assert cone.property_name == "top"


# ============================================================
# Compositional Soundness tests
# ============================================================

class TestCompositionalSoundness:
    def test_ag_acyclic_is_sound(self):
        tree = build_proof_tree(make_ag_acyclic())
        report = check_compositional_soundness(tree)
        assert isinstance(report, SoundnessReport)
        assert report.is_sound is True
        assert len(report.issues) == 0

    def test_ag_cyclic_is_unsound(self):
        tree = build_proof_tree(make_ag_cyclic())
        report = check_compositional_soundness(tree)
        assert report.is_sound is False
        assert any(i.severity == "error" for i in report.issues)
        assert any("cycl" in i.description.lower() or "circular" in i.description.lower()
                    for i in report.issues)

    def test_helper_circular_is_unsound(self):
        tree = build_proof_tree(make_helper_circular())
        report = check_compositional_soundness(tree)
        assert report.is_sound is False
        assert any(i.severity == "error" for i in report.issues)

    def test_stopat_depth_inconsistency_warning(self):
        """Stopat depth_limit > cone sequential_depth triggers warning."""
        tree = build_proof_tree(make_stopat_depth_inconsistent())
        report = check_compositional_soundness(tree)
        warnings = [i for i in report.issues if i.severity == "warning"]
        assert len(warnings) > 0
        assert any("depth" in w.description.lower() for w in warnings)
        # Warnings don't make the composition unsound
        assert report.is_sound is True

    def test_case_split_non_primary_warning(self):
        """Case split using derived signal triggers warning."""
        tree = build_proof_tree(make_case_split_non_primary())
        report = check_compositional_soundness(tree)
        warnings = [i for i in report.issues if i.severity == "warning"]
        assert len(warnings) > 0
        assert any("primary" in w.description.lower() or "non-primary" in w.description.lower()
                    for w in warnings)

    def test_case_split_primary_no_warning(self):
        """Case split with primary signals produces no case-related warnings."""
        tree = build_proof_tree(make_case_split_valid_3vars())
        report = check_compositional_soundness(tree)
        cs_warnings = [i for i in report.issues
                       if "case" in i.description.lower() or "primary" in i.description.lower()]
        assert len(cs_warnings) == 0

    def test_helper_valid_is_sound(self):
        tree = build_proof_tree(make_helper_valid())
        report = check_compositional_soundness(tree)
        assert report.is_sound is True

    def test_soundness_issue_fields(self):
        """Soundness issues have required fields."""
        tree = build_proof_tree(make_ag_cyclic())
        report = check_compositional_soundness(tree)
        for issue in report.issues:
            assert isinstance(issue, SoundnessIssue)
            assert issue.severity in ("error", "warning")
            assert isinstance(issue.description, str)
            assert isinstance(issue.affected_properties, list)


# ============================================================
# CLI Validator tests
# ============================================================

class TestCLIValidator:
    """Tests for the validate_proof.py CLI tool."""

    def _run_cli(self, proof_file, fmt="json"):
        """Run the CLI validator on a proof file and return output."""
        cmd = ["python3", "/app/validate_proof.py"]
        if fmt != "json":
            cmd.extend(["--format", fmt])
        cmd.append(proof_file)
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd="/app",
            timeout=30,
        )
        assert result.returncode == 0, (
            f"CLI exited {result.returncode} on {proof_file}:\n{result.stderr}"
        )
        if fmt == "json":
            return json.loads(result.stdout)
        return result.stdout

    def test_ag_valid(self):
        report = self._run_cli("/app/proofs/ag_arbiter.json")
        assert report["valid"] is True
        assert len(report["decompositions"]) == 1
        d = report["decompositions"][0]
        assert d["strategy"] == "assume_guarantee"
        assert d["valid"] is True
        assert isinstance(report["schedule"], list)
        assert len(report["schedule"]) > 0

    def test_ag_cyclic(self):
        report = self._run_cli("/app/proofs/ag_cyclic.json")
        assert report["valid"] is False
        d = report["decompositions"][0]
        has_decomp_error = d["valid"] is False
        has_schedule_error = (
            report.get("schedule") is None
            or report.get("schedule_error") is not None
        )
        assert has_decomp_error or has_schedule_error

    def test_casesplit(self):
        report = self._run_cli("/app/proofs/casesplit_modes.json")
        assert report["valid"] is True
        d = report["decompositions"][0]
        assert d["strategy"] == "case_split"
        assert d["valid"] is True

    def test_partition(self):
        report = self._run_cli("/app/proofs/partition_bus.json")
        assert report["valid"] is True
        d = report["decompositions"][0]
        assert d["strategy"] == "partition"
        assert d["valid"] is True

    def test_stopat(self):
        report = self._run_cli("/app/proofs/stopat_depth.json")
        assert report["valid"] is True
        d = report["decompositions"][0]
        assert d["strategy"] == "stopat"
        assert d["valid"] is True

    def test_helper(self):
        report = self._run_cli("/app/proofs/helper_fsm.json")
        assert report["valid"] is True
        d = report["decompositions"][0]
        assert d["strategy"] == "helper_invariant"
        assert d["valid"] is True

    def test_multi_arbiter(self):
        report = self._run_cli("/app/proofs/multi_arbiter.json")
        assert report["valid"] is True
        assert len(report["decompositions"]) == 2
        assert report["decompositions"][0]["strategy"] == "case_split"
        assert report["decompositions"][0]["valid"] is True
        assert report["decompositions"][1]["strategy"] == "helper_invariant"
        assert report["decompositions"][1]["valid"] is True

    def test_report_schema(self):
        """Validate that the CLI output follows the expected JSON schema."""
        report = self._run_cli("/app/proofs/ag_arbiter.json")
        assert "file" in report
        assert "valid" in report
        assert "decompositions" in report
        assert "schedule" in report
        for d in report["decompositions"]:
            assert "index" in d
            assert "target" in d
            assert "strategy" in d
            assert "valid" in d
            assert "errors" in d

    def test_make_validate(self):
        """Verify that 'make validate' succeeds."""
        result = subprocess.run(
            ["make", "validate"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make validate failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ============================================================
# DOT output tests
# ============================================================

class TestDotOutput:
    """Tests for the --format dot CLI flag producing Graphviz DOT output."""

    def test_dot_ag_proof(self):
        """AG proof DOT output has digraph, property name, assumes edges."""
        output = TestCLIValidator()._run_cli(
            "/app/proofs/ag_arbiter.json", fmt="dot"
        )
        assert "digraph" in output
        assert "fairness" in output
        assert "assumes" in output
        assert output.strip().endswith("}")

    def test_dot_helper_proof(self):
        """Helper proof DOT output has depends edges."""
        output = TestCLIValidator()._run_cli(
            "/app/proofs/helper_fsm.json", fmt="dot"
        )
        assert "digraph" in output
        assert "main_liveness" in output
        assert "depends" in output
        assert output.strip().endswith("}")

    def test_dot_casesplit_proof(self):
        """Case split proof DOT output is valid DOT."""
        output = TestCLIValidator()._run_cli(
            "/app/proofs/casesplit_modes.json", fmt="dot"
        )
        assert "digraph" in output
        assert "pipe_correct" in output
        assert output.strip().endswith("}")

    def test_dot_cyclic_proof(self):
        """Cyclic proof still produces valid DOT output."""
        output = TestCLIValidator()._run_cli(
            "/app/proofs/ag_cyclic.json", fmt="dot"
        )
        assert "digraph" in output
        assert output.strip().endswith("}")

    def test_dot_multi_arbiter(self):
        """Multi-strategy proof DOT output is valid."""
        output = TestCLIValidator()._run_cli(
            "/app/proofs/multi_arbiter.json", fmt="dot"
        )
        assert "digraph" in output
        assert "arb_fair" in output
        assert output.strip().endswith("}")


# ============================================================
# CLI Obligations output tests
# ============================================================

class TestCLIObligations:
    """Tests for the --format obligations CLI flag."""

    def _run_obligations(self, proof_file):
        cmd = ["python3", "/app/validate_proof.py", "--format", "obligations", proof_file]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="/app", timeout=30)
        assert result.returncode == 0, (
            f"CLI obligations exited {result.returncode}:\n{result.stderr}"
        )
        return json.loads(result.stdout)

    def test_ag_obligations_schema(self):
        report = self._run_obligations("/app/proofs/ag_arbiter.json")
        assert "decompositions" in report
        assert "cone_of_influence" in report
        assert "soundness" in report
        assert len(report["decompositions"]) == 1
        d = report["decompositions"][0]
        assert d["strategy"] == "assume_guarantee"
        assert len(d["obligations"]) == 3

    def test_ag_obligations_soundness(self):
        report = self._run_obligations("/app/proofs/ag_arbiter.json")
        assert report["soundness"]["is_sound"] is True

    def test_cyclic_obligations_soundness(self):
        report = self._run_obligations("/app/proofs/ag_cyclic.json")
        assert report["soundness"]["is_sound"] is False
        assert len(report["soundness"]["issues"]) > 0

    def test_multi_arbiter_obligations(self):
        report = self._run_obligations("/app/proofs/multi_arbiter.json")
        assert len(report["decompositions"]) == 2
        cs = report["decompositions"][0]
        assert cs["strategy"] == "case_split"
        assert len(cs["obligations"]) == 2
        hi = report["decompositions"][1]
        assert hi["strategy"] == "helper_invariant"
        assert len(hi["obligations"]) == 2

    def test_cone_of_influence_output(self):
        report = self._run_obligations("/app/proofs/ag_arbiter.json")
        coi = report["cone_of_influence"]
        assert "fairness" in coi
        cone = coi["fairness"]
        assert "structural_cone" in cone
        assert "sequential_depth" in cone
        assert "boundary_signals" in cone
        assert isinstance(cone["structural_cone"], list)
        assert isinstance(cone["sequential_depth"], int)

    def test_stopat_obligations_rewrite(self):
        report = self._run_obligations("/app/proofs/stopat_depth.json")
        d = report["decompositions"][0]
        assert d["strategy"] == "stopat"
        assert len(d["obligations"]) == 1
        obl = d["obligations"][0]
        assert "G[0:3]" in obl["expression"]
        assert "F[0:3]" in obl["expression"]

    def test_obligation_fields(self):
        """Each obligation has required fields."""
        report = self._run_obligations("/app/proofs/helper_fsm.json")
        for d in report["decompositions"]:
            for obl in d["obligations"]:
                assert "name" in obl
                assert "expression" in obl
                assert "environment" in obl
                assert "assumptions" in obl
                assert "source_strategy" in obl


# ============================================================
# jq report aggregation tests
# ============================================================

class TestMakeReport:
    """Tests for the jq-based report aggregation pipeline."""

    def test_make_report_succeeds(self):
        """Verify that 'make report' succeeds."""
        result = subprocess.run(
            ["make", "report"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make report failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_report_json_schema(self):
        """Report summary.json has correct schema and counts."""
        subprocess.run(
            ["make", "report"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        report_path = "/app/reports/summary.json"
        assert os.path.exists(report_path), "reports/summary.json not found"
        with open(report_path) as f:
            report = json.load(f)
        assert report["total_files"] == 7
        assert report["valid_count"] == 6
        assert report["invalid_count"] == 1
        assert isinstance(report["files"], list)
        assert len(report["files"]) == 7
        for entry in report["files"]:
            assert "file" in entry
            assert "valid" in entry


# ============================================================
# Graphviz SVG generation tests
# ============================================================

class TestMakeGraph:
    """Tests for graphviz DOT-to-SVG rendering via make graph."""

    def test_make_graph_succeeds(self):
        """Verify that 'make graph' succeeds."""
        result = subprocess.run(
            ["make", "graph"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make graph failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_svg_files_generated(self):
        """All proof files produce corresponding SVG graphs."""
        subprocess.run(
            ["make", "graph"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        for name in ["ag_arbiter", "ag_cyclic", "casesplit_modes",
                      "partition_bus", "stopat_depth", "helper_fsm",
                      "multi_arbiter"]:
            svg_path = f"/app/graphs/{name}.svg"
            assert os.path.exists(svg_path), f"{svg_path} not found"
            with open(svg_path) as f:
                content = f.read()
            assert "<svg" in content, f"{svg_path} is not valid SVG"

    def test_dot_files_generated(self):
        """All proof files produce corresponding DOT files."""
        subprocess.run(
            ["make", "graph"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        for name in ["ag_arbiter", "ag_cyclic", "casesplit_modes",
                      "partition_bus", "stopat_depth", "helper_fsm",
                      "multi_arbiter"]:
            dot_path = f"/app/graphs/{name}.dot"
            assert os.path.exists(dot_path), f"{dot_path} not found"
            with open(dot_path) as f:
                content = f.read()
            assert "digraph" in content


# ============================================================
# Make obligations target tests
# ============================================================

class TestMakeObligations:
    """Tests for the make obligations target."""

    def test_make_obligations_succeeds(self):
        result = subprocess.run(
            ["make", "obligations"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make obligations failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_obligation_files_generated(self):
        """All proof files produce corresponding obligation JSON files."""
        subprocess.run(
            ["make", "obligations"],
            capture_output=True, text=True, cwd="/app",
            timeout=120,
        )
        for name in ["ag_arbiter", "ag_cyclic", "casesplit_modes",
                      "partition_bus", "stopat_depth", "helper_fsm",
                      "multi_arbiter"]:
            obl_path = f"/app/obligations/{name}.json"
            assert os.path.exists(obl_path), f"{obl_path} not found"
            with open(obl_path) as f:
                data = json.load(f)
            assert "decompositions" in data
            assert "cone_of_influence" in data
            assert "soundness" in data
