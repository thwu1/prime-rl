"""
Integration tests for the Proof Decomposition Engine.
These tests exercise the expected API from models.py.

"""

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
    Obligation,
    ConeInfo,
    SoundnessReport,
)


# ============================================================
# Fixtures: reusable proof structure specs
# ============================================================

def ag_spec_acyclic():
    """Assume-Guarantee with valid (acyclic) assumptions."""
    return {
        "properties": {
            "top_prop": {
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
                "target": "top_prop",
                "params": {
                    "sub_properties": {
                        "sp_a": {
                            "expression": "G(req -> X ack_pending)",
                            "assumes": ["sp_c"],
                        },
                        "sp_b": {
                            "expression": "G(ack_pending -> F ack)",
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


def ag_spec_cyclic():
    """Assume-Guarantee with cyclic assumptions."""
    return {
        "properties": {
            "top_prop": {
                "expression": "G(a -> F b)",
                "signals": ["a", "b"],
                "temporal_depth": 5,
            }
        },
        "signal_dependencies": {"a": [], "b": ["a"]},
        "decompositions": [
            {
                "strategy": "assume_guarantee",
                "target": "top_prop",
                "params": {
                    "sub_properties": {
                        "sp_x": {
                            "expression": "G(a -> X b)",
                            "assumes": ["sp_y"],
                        },
                        "sp_y": {
                            "expression": "G(b -> X a)",
                            "assumes": ["sp_z"],
                        },
                        "sp_z": {
                            "expression": "G(a & b)",
                            "assumes": ["sp_x"],
                        },
                    }
                },
            }
        ],
    }


def case_split_spec_valid():
    """Valid case split with exhaustive, mutually exclusive predicates."""
    return {
        "properties": {
            "arb_prop": {
                "expression": "G(grant -> F release)",
                "signals": ["mode_a", "mode_b", "grant", "release"],
                "temporal_depth": 8,
            }
        },
        "signal_dependencies": {
            "mode_a": [],
            "mode_b": [],
            "grant": ["mode_a", "mode_b"],
            "release": ["grant"],
        },
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "arb_prop",
                "params": {
                    "cases": [
                        {"name": "case1", "predicate": "mode_a & ~mode_b"},
                        {"name": "case2", "predicate": "~mode_a & mode_b"},
                        {"name": "case3", "predicate": "~mode_a & ~mode_b"},
                        {"name": "case4", "predicate": "mode_a & mode_b"},
                    ]
                },
            }
        ],
    }


def case_split_spec_not_exhaustive():
    """Invalid case split: missing a case."""
    return {
        "properties": {
            "arb_prop": {
                "expression": "G(grant -> F release)",
                "signals": ["mode_a", "mode_b", "grant", "release"],
                "temporal_depth": 8,
            }
        },
        "signal_dependencies": {
            "mode_a": [],
            "mode_b": [],
            "grant": ["mode_a", "mode_b"],
            "release": ["grant"],
        },
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "arb_prop",
                "params": {
                    "cases": [
                        {"name": "case1", "predicate": "mode_a & ~mode_b"},
                        {"name": "case2", "predicate": "~mode_a & mode_b"},
                        {"name": "case3", "predicate": "~mode_a & ~mode_b"},
                        # Missing: mode_a & mode_b
                    ]
                },
            }
        ],
    }


def case_split_spec_not_exclusive():
    """Invalid case split: overlapping predicates."""
    return {
        "properties": {
            "arb_prop": {
                "expression": "G(grant -> F release)",
                "signals": ["x", "y"],
                "temporal_depth": 4,
            }
        },
        "signal_dependencies": {"x": [], "y": []},
        "decompositions": [
            {
                "strategy": "case_split",
                "target": "arb_prop",
                "params": {
                    "cases": [
                        {"name": "case1", "predicate": "x"},
                        {"name": "case2", "predicate": "y"},
                        {"name": "case3", "predicate": "~x & ~y"},
                    ]
                },
            }
        ],
    }


def partition_spec_valid():
    """Valid partitioning with disjoint fanin cones after cut."""
    return {
        "properties": {
            "bus_prop": {
                "expression": "G(valid -> data_ok)",
                "signals": ["valid", "data_ok", "addr", "ctrl", "clk",
                            "a_in", "b_in", "c_in", "d_in"],
                "temporal_depth": 6,
            }
        },
        "signal_dependencies": {
            "valid": ["addr", "ctrl"],
            "data_ok": ["d_in"],
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
                "target": "bus_prop",
                "params": {
                    "cut_signals": ["clk"],
                    "partitions": [
                        {"name": "addr_part", "root_signals": ["addr"]},
                        {"name": "data_part", "root_signals": ["data_ok"]},
                    ],
                },
            }
        ],
    }


def partition_spec_overlap():
    """Invalid partitioning: overlapping fanin after cut."""
    return {
        "properties": {
            "bus_prop": {
                "expression": "G(valid -> data_ok)",
                "signals": ["valid", "data_ok", "shared", "a", "b"],
                "temporal_depth": 6,
            }
        },
        "signal_dependencies": {
            "valid": ["shared", "a"],
            "data_ok": ["shared", "b"],
            "shared": [],
            "a": [],
            "b": [],
        },
        "decompositions": [
            {
                "strategy": "partition",
                "target": "bus_prop",
                "params": {
                    "cut_signals": [],
                    "partitions": [
                        {"name": "part_a", "root_signals": ["valid"]},
                        {"name": "part_b", "root_signals": ["data_ok"]},
                    ],
                },
            }
        ],
    }


def stopat_spec_valid():
    """Valid stopat decomposition."""
    return {
        "properties": {
            "deep_prop": {
                "expression": "G[0:20](req -> F[0:20] ack)",
                "signals": ["req", "ack"],
                "temporal_depth": 20,
            }
        },
        "signal_dependencies": {
            "req": [],
            "ack": ["mid1"],
            "mid1": ["mid2"],
            "mid2": ["mid3"],
            "mid3": ["src"],
            "src": [],
        },
        "decompositions": [
            {
                "strategy": "stopat",
                "target": "deep_prop",
                "params": {
                    "depth_limit": 2,
                    "free_variable_prefix": "fv_",
                },
            }
        ],
    }


def helper_spec_valid():
    """Valid helper invariant injection."""
    return {
        "properties": {
            "main_prop": {
                "expression": "G(req -> F ack)",
                "signals": ["req", "ack"],
                "temporal_depth": 10,
            },
            "helper1": {
                "expression": "G(ack -> X idle)",
                "signals": ["ack", "idle"],
                "temporal_depth": 5,
            },
            "helper2": {
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
                "target": "main_prop",
                "params": {
                    "helpers": ["helper1", "helper2"],
                    "target": "main_prop",
                },
            }
        ],
    }


def helper_spec_circular():
    """Invalid helper: circular dependency."""
    return {
        "properties": {
            "prop_a": {
                "expression": "G(a)",
                "signals": ["a"],
                "temporal_depth": 5,
            },
            "prop_b": {
                "expression": "G(b)",
                "signals": ["b"],
                "temporal_depth": 5,
            },
        },
        "signal_dependencies": {"a": [], "b": []},
        "decompositions": [
            {
                "strategy": "helper_invariant",
                "target": "prop_a",
                "params": {
                    "helpers": ["prop_b"],
                    "target": "prop_a",
                },
            },
            {
                "strategy": "helper_invariant",
                "target": "prop_b",
                "params": {
                    "helpers": ["prop_a"],
                    "target": "prop_b",
                },
            },
        ],
    }


# ============================================================
# Tests: build_proof_tree
# ============================================================

class TestBuildProofTree:
    def test_valid_spec(self):
        tree = build_proof_tree(ag_spec_acyclic())
        assert "top_prop" in tree.properties
        assert len(tree.decompositions) == 1
        assert tree.decompositions[0].strategy == Strategy.ASSUME_GUARANTEE

    def test_missing_properties_key(self):
        spec = {"signal_dependencies": {}, "decompositions": []}
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_invalid_strategy(self):
        spec = ag_spec_acyclic()
        spec["decompositions"][0]["strategy"] = "invalid_strategy"
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_target_not_found(self):
        spec = ag_spec_acyclic()
        spec["decompositions"][0]["target"] = "nonexistent"
        with pytest.raises(ValidationError):
            build_proof_tree(spec)

    def test_missing_property_fields(self):
        spec = ag_spec_acyclic()
        del spec["properties"]["top_prop"]["temporal_depth"]
        with pytest.raises(ValidationError):
            build_proof_tree(spec)


# ============================================================
# Tests: Assume-Guarantee
# ============================================================

class TestAssumeGuarantee:
    def test_acyclic_valid(self):
        tree = build_proof_tree(ag_spec_acyclic())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is True
        assert "verification_order" in result.details
        order = result.details["verification_order"]
        assert order.index("sp_c") < order.index("sp_a")
        assert order.index("sp_a") < order.index("sp_b")

    def test_cyclic_detected(self):
        tree = build_proof_tree(ag_spec_cyclic())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False
        assert len(result.errors) > 0
        assert any("cycl" in e.lower() for e in result.errors)


# ============================================================
# Tests: Case Split
# ============================================================

class TestCaseSplit:
    def test_valid_exhaustive_exclusive(self):
        tree = build_proof_tree(case_split_spec_valid())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is True
        assert "variables" in result.details
        assert set(result.details["variables"]) == {"mode_a", "mode_b"}
        assert result.details["num_cases"] == 4

    def test_not_exhaustive(self):
        tree = build_proof_tree(case_split_spec_not_exhaustive())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False
        assert any("exhaustive" in e.lower() for e in result.errors)

    def test_not_exclusive(self):
        tree = build_proof_tree(case_split_spec_not_exclusive())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False
        assert any("exclusive" in e.lower() or "overlap" in e.lower()
                    for e in result.errors)


# ============================================================
# Tests: Partitioning
# ============================================================

class TestPartitioning:
    def test_valid_disjoint(self):
        tree = build_proof_tree(partition_spec_valid())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is True
        assert "fanin_cones" in result.details
        cones = result.details["fanin_cones"]
        assert "addr_part" in cones
        assert "data_part" in cones
        addr_cone = set(cones["addr_part"])
        data_cone = set(cones["data_part"])
        assert addr_cone & data_cone == set()
        assert "a_in" in addr_cone
        assert "b_in" in data_cone or "d_in" in data_cone

    def test_overlapping_cones(self):
        tree = build_proof_tree(partition_spec_overlap())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False
        assert any("overlap" in e.lower() or "disjoint" in e.lower()
                    for e in result.errors)


# ============================================================
# Tests: Stopat
# ============================================================

class TestStopat:
    def test_valid_stopat(self):
        tree = build_proof_tree(stopat_spec_valid())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is True
        assert result.details["original_depth"] == 20
        assert result.details["rewritten_depth"] == 2
        assert "free_variables" in result.details
        fvs = result.details["free_variables"]
        assert len(fvs) > 0
        assert all(fv.startswith("fv_") for fv in fvs)

    def test_invalid_depth(self):
        spec = stopat_spec_valid()
        spec["decompositions"][0]["params"]["depth_limit"] = 25
        tree = build_proof_tree(spec)
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False

    def test_zero_depth(self):
        spec = stopat_spec_valid()
        spec["decompositions"][0]["params"]["depth_limit"] = 0
        tree = build_proof_tree(spec)
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False


# ============================================================
# Tests: Helper Invariant
# ============================================================

class TestHelperInvariant:
    def test_valid_helpers(self):
        tree = build_proof_tree(helper_spec_valid())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is True
        assert "dependency_order" in result.details
        order = result.details["dependency_order"]
        assert order.index("helper1") < order.index("main_prop")
        assert order.index("helper2") < order.index("main_prop")

    def test_circular_helpers(self):
        tree = build_proof_tree(helper_spec_circular())
        result = validate_decomposition(tree, 0)
        assert result.is_valid is False
        assert any("cycl" in e.lower() or "circular" in e.lower()
                    for e in result.errors)


# ============================================================
# Tests: Global Scheduling
# ============================================================

class TestScheduling:
    def test_schedule_ag(self):
        tree = build_proof_tree(ag_spec_acyclic())
        schedule = compute_schedule(tree)
        assert isinstance(schedule, list)
        assert len(schedule) > 0

    def test_schedule_cyclic_raises(self):
        tree = build_proof_tree(ag_spec_cyclic())
        with pytest.raises(CyclicDependencyError):
            compute_schedule(tree)

    def test_schedule_multi_strategy(self):
        """Schedule across AG + helper in a combined spec."""
        spec = helper_spec_valid()
        spec["decompositions"].append({
            "strategy": "assume_guarantee",
            "target": "helper1",
            "params": {
                "sub_properties": {
                    "h1_sub_a": {
                        "expression": "G(ack -> X idle)",
                        "assumes": [],
                    },
                    "h1_sub_b": {
                        "expression": "G(idle -> ready)",
                        "assumes": ["h1_sub_a"],
                    },
                }
            },
        })
        tree = build_proof_tree(spec)
        schedule = compute_schedule(tree)
        assert schedule.index("h1_sub_a") < schedule.index("h1_sub_b")
        for h in ["helper1", "helper2"]:
            if h in schedule:
                assert schedule.index(h) < schedule.index("main_prop")


# ============================================================
# Tests: Proof Report
# ============================================================

class TestProofReport:
    def test_report_valid(self):
        tree = build_proof_tree(ag_spec_acyclic())
        report = get_proof_report(tree)
        assert report.has_errors is False
        assert len(report.global_schedule) > 0
        assert len(report.entries) > 0

    def test_report_with_errors(self):
        tree = build_proof_tree(ag_spec_cyclic())
        report = get_proof_report(tree)
        assert report.has_errors is True

    def test_report_entries_have_strategy(self):
        tree = build_proof_tree(case_split_spec_valid())
        report = get_proof_report(tree)
        decomposed = [e for e in report.entries if e.strategy is not None]
        assert len(decomposed) > 0
        assert decomposed[0].strategy == "case_split"


# ============================================================
# Tests: Obligation Generation
# ============================================================

class TestObligations:
    def test_ag_obligations(self):
        tree = build_proof_tree(ag_spec_acyclic())
        obls = generate_obligations(tree, 0)
        assert isinstance(obls, list)
        assert len(obls) == 3
        assert all(isinstance(o, Obligation) for o in obls)

    def test_case_split_obligations(self):
        tree = build_proof_tree(case_split_spec_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 4

    def test_helper_obligations(self):
        tree = build_proof_tree(helper_spec_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 3

    def test_stopat_obligations(self):
        tree = build_proof_tree(stopat_spec_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 1

    def test_partition_obligations(self):
        tree = build_proof_tree(partition_spec_valid())
        obls = generate_obligations(tree, 0)
        assert len(obls) == 2


# ============================================================
# Tests: Cone of Influence
# ============================================================

class TestConeOfInfluence:
    def test_basic_cone(self):
        tree = build_proof_tree(ag_spec_acyclic())
        cone = compute_cone_of_influence(tree, "top_prop")
        assert isinstance(cone, ConeInfo)
        assert "req" in cone.structural_cone
        assert "ack" in cone.structural_cone
        assert "clk" in cone.structural_cone

    def test_helper_cone(self):
        tree = build_proof_tree(helper_spec_valid())
        cone = compute_cone_of_influence(tree, "main_prop")
        assert cone.sequential_depth >= 0

    def test_stopat_cone_depth(self):
        tree = build_proof_tree(stopat_spec_valid())
        cone = compute_cone_of_influence(tree, "deep_prop")
        assert cone.sequential_depth > 0
        assert "src" in cone.structural_cone


# ============================================================
# Tests: Compositional Soundness
# ============================================================

class TestCompositionalSoundness:
    def test_acyclic_sound(self):
        tree = build_proof_tree(ag_spec_acyclic())
        report = check_compositional_soundness(tree)
        assert isinstance(report, SoundnessReport)
        assert report.is_sound is True

    def test_cyclic_unsound(self):
        tree = build_proof_tree(ag_spec_cyclic())
        report = check_compositional_soundness(tree)
        assert report.is_sound is False

    def test_circular_helpers_unsound(self):
        tree = build_proof_tree(helper_spec_circular())
        report = check_compositional_soundness(tree)
        assert report.is_sound is False
