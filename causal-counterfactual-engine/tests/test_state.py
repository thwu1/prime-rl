
"""Tests for the causal SCM analysis system."""

import os
import sys
import json
import math
import subprocess
import pytest
import numpy as np

sys.path.insert(0, "/app")


# ===================================================================
# PIPELINE COMPLETION
# ===================================================================

class TestPipelineCompletion:
    def test_completion_marker(self):
        assert os.path.exists("/app/output/.completed"), \
            "Pipeline did not create completion marker"

    def test_report_exists(self):
        assert os.path.exists("/app/output/analysis_report.json"), \
            "Pipeline did not create analysis_report.json"


# ===================================================================
# REPORT SCHEMA VALIDATION
# ===================================================================

class TestReportSchema:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/analysis_report.json") as f:
            self.report = json.load(f)

    def test_top_level_keys(self):
        required = {"d_separation_tests", "do_calculus_tests",
                     "causal_effects", "timestamp"}
        missing = required - set(self.report.keys())
        assert not missing, f"Missing top-level keys: {missing}"

    def test_dsep_count(self):
        assert len(self.report["d_separation_tests"]) == 10, \
            f"Expected 10 d-sep tests, got {len(self.report['d_separation_tests'])}"

    def test_dsep_entry_fields(self):
        required = {"graph_name", "X_set", "Y_set", "Z_set", "result"}
        for entry in self.report["d_separation_tests"]:
            missing = required - set(entry.keys())
            assert not missing, f"D-sep entry missing fields: {missing}"
            assert isinstance(entry["result"], bool), \
                f"result must be boolean, got {type(entry['result'])}"
            assert isinstance(entry["X_set"], list)
            assert isinstance(entry["Y_set"], list)
            assert isinstance(entry["Z_set"], list)
            assert isinstance(entry["graph_name"], str)

    def test_rule2_count(self):
        assert len(self.report["do_calculus_tests"]) == 4, \
            f"Expected 4 rule2 tests, got {len(self.report['do_calculus_tests'])}"

    def test_rule2_entry_fields(self):
        required = {"graph_name", "X_vars", "Z_vars", "Y_vars",
                     "W_vars", "applicable"}
        for entry in self.report["do_calculus_tests"]:
            missing = required - set(entry.keys())
            assert not missing, f"Rule2 entry missing fields: {missing}"
            assert isinstance(entry["applicable"], bool), \
                f"applicable must be boolean, got {type(entry['applicable'])}"

    def test_effects_count(self):
        assert len(self.report["causal_effects"]) == 3, \
            f"Expected 3 effect entries, got {len(self.report['causal_effects'])}"

    def test_effects_entry_fields(self):
        required = {"graph_name", "treatment", "outcome", "ate",
                     "counterfactual_te", "ate_cf_consistent"}
        for entry in self.report["causal_effects"]:
            missing = required - set(entry.keys())
            assert not missing, f"Effect entry missing fields: {missing}"
            assert isinstance(entry["ate"], (int, float))
            assert isinstance(entry["counterfactual_te"], (int, float))
            assert isinstance(entry["ate_cf_consistent"], bool)
            assert math.isfinite(entry["ate"]), "ATE must be finite"
            assert math.isfinite(entry["counterfactual_te"]), "CTF-TE must be finite"

    def test_timestamp_present(self):
        assert isinstance(self.report["timestamp"], str)
        assert len(self.report["timestamp"]) > 0


# ===================================================================
# D-SEPARATION CORRECTNESS
# ===================================================================

class TestDSeparationCorrectness:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/analysis_report.json") as f:
            self.report = json.load(f)

    def _lookup(self, graph, x_set, y_set, z_set):
        x_key = tuple(sorted(x_set))
        y_key = tuple(sorted(y_set))
        z_key = tuple(sorted(z_set))
        for entry in self.report["d_separation_tests"]:
            if (entry["graph_name"] == graph and
                    tuple(sorted(entry["X_set"])) == x_key and
                    tuple(sorted(entry["Y_set"])) == y_key and
                    tuple(sorted(entry["Z_set"])) == z_key):
                return entry["result"]
        pytest.fail(f"D-sep test not found: {graph} X={x_set} Y={y_set} Z={z_set}")

    def test_chain_conditioned_mediator(self):
        assert self._lookup("chain", ["X"], ["Y"], ["M"]) is True

    def test_chain_unconditioned(self):
        assert self._lookup("chain", ["X"], ["Y"], []) is False

    def test_fork_conditioned_cause(self):
        assert self._lookup("fork", ["X"], ["Y"], ["Z"]) is True

    def test_fork_unconditioned(self):
        assert self._lookup("fork", ["X"], ["Y"], []) is False

    def test_collider_unconditioned(self):
        assert self._lookup("collider", ["X"], ["Y"], []) is True

    def test_collider_conditioned(self):
        assert self._lookup("collider", ["X"], ["Y"], ["M"]) is False

    def test_diamond_unconditioned(self):
        assert self._lookup("diamond", ["X"], ["W"], []) is False

    def test_diamond_conditioned_root(self):
        assert self._lookup("diamond", ["X"], ["W"], ["Z"]) is True

    def test_diamond_conditioned_collider(self):
        assert self._lookup("diamond", ["X"], ["W"], ["Y"]) is False

    def test_diamond_conditioned_both_mediators(self):
        assert self._lookup("diamond", ["Z"], ["Y"], ["X", "W"]) is True


# ===================================================================
# DO-CALCULUS RULE 2 CORRECTNESS
# ===================================================================

class TestDoCalculusCorrectness:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/analysis_report.json") as f:
            self.report = json.load(f)

    def _lookup(self, graph, x_vars, z_vars):
        x_key = tuple(sorted(x_vars))
        z_key = tuple(sorted(z_vars))
        for entry in self.report["do_calculus_tests"]:
            if (entry["graph_name"] == graph and
                    tuple(sorted(entry["X_vars"])) == x_key and
                    tuple(sorted(entry["Z_vars"])) == z_key):
                return entry["applicable"]
        pytest.fail(f"Rule2 test not found: {graph} X={x_vars} Z={z_vars}")

    def test_chain_rule2(self):
        assert self._lookup("chain", ["X"], ["M"]) is True

    def test_fork_rule2(self):
        assert self._lookup("fork", [], ["X"]) is False

    def test_diamond_rule2_with_intervention(self):
        assert self._lookup("diamond", ["Z"], ["X"]) is True

    def test_diamond_rule2_without_intervention(self):
        assert self._lookup("diamond", [], ["X"]) is False


# ===================================================================
# CAUSAL EFFECTS CORRECTNESS
# ===================================================================

class TestCausalEffectsCorrectness:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/analysis_report.json") as f:
            self.report = json.load(f)
        self.effects = {e["graph_name"]: e for e in self.report["causal_effects"]}

    def test_chain_ate(self):
        ate = self.effects["chain"]["ate"]
        assert abs(ate - 3.0) < 0.2, f"Chain ATE should be ~3.0, got {ate}"

    def test_fork_ate(self):
        ate = self.effects["fork"]["ate"]
        assert abs(ate - 0.0) < 0.2, f"Fork ATE should be ~0.0, got {ate}"

    def test_diamond_ate(self):
        ate = self.effects["diamond"]["ate"]
        assert abs(ate - 1.5) < 0.2, f"Diamond ATE should be ~1.5, got {ate}"

    def test_chain_ctf_te(self):
        ctf = self.effects["chain"]["counterfactual_te"]
        assert abs(ctf - 3.0) < 0.2, f"Chain CTF-TE should be ~3.0, got {ctf}"

    def test_fork_ctf_te(self):
        ctf = self.effects["fork"]["counterfactual_te"]
        assert abs(ctf - 0.0) < 0.2, f"Fork CTF-TE should be ~0.0, got {ctf}"

    def test_diamond_ctf_te(self):
        ctf = self.effects["diamond"]["counterfactual_te"]
        assert abs(ctf - 1.5) < 0.2, f"Diamond CTF-TE should be ~1.5, got {ctf}"

    def test_ate_cf_consistency_all_true(self):
        for name, effect in self.effects.items():
            assert effect["ate_cf_consistent"] is True, \
                f"ate_cf_consistent must be true for {name}"


# ===================================================================
# JQ PARSING
# ===================================================================

class TestJQParsing:
    def test_jq_valid_json(self):
        result = subprocess.run(
            ["jq", ".", "/app/output/analysis_report.json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"jq failed: {result.stderr}"

    def test_jq_count_dsep(self):
        result = subprocess.run(
            ["jq", ".d_separation_tests | length",
             "/app/output/analysis_report.json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert int(result.stdout.strip()) == 10

    def test_jq_extract_effects(self):
        result = subprocess.run(
            ["jq", "[.causal_effects[].ate]",
             "/app/output/analysis_report.json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        ates = json.loads(result.stdout)
        assert len(ates) == 3
        assert all(isinstance(a, (int, float)) for a in ates)

    def test_jq_extract_graph_names(self):
        result = subprocess.run(
            ["jq", "-r", ".d_separation_tests[].graph_name",
             "/app/output/analysis_report.json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        names = result.stdout.strip().split("\n")
        assert len(names) == 10


# ===================================================================
# DIRECT FUNCTION TESTS (anti-cheat: novel graphs not in pipeline)
# ===================================================================

class TestDirectDSeparation:
    """Test is_d_separated on graphs NOT used by the pipeline."""

    def test_instrument_graph_basic(self):
        from graph_utils import is_d_separated
        # Instrumental variable: I -> X -> Y, Z -> X, Z -> Y
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # I and Y not d-sep (path I -> X -> Y)
        assert is_d_separated(pm, {"I"}, {"Y"}, set()) is False

    def test_instrument_graph_independent(self):
        from graph_utils import is_d_separated
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # I and Z d-sep (no path)
        assert is_d_separated(pm, {"I"}, {"Z"}, set()) is True

    def test_instrument_graph_collider_activation(self):
        from graph_utils import is_d_separated
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # I and Z not d-sep given X (X is collider, conditioning opens)
        assert is_d_separated(pm, {"I"}, {"Z"}, {"X"}) is False

    def test_instrument_graph_full_conditioning(self):
        from graph_utils import is_d_separated
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # I and Y d-sep given {X, Z}: chain blocked by X, collider
        # opened by X but then Z is non-collider in Z_set -> blocked
        assert is_d_separated(pm, {"I"}, {"Y"}, {"X", "Z"}) is True

    def test_simple_two_node(self):
        from graph_utils import is_d_separated
        pm = {"A": [], "B": ["A"]}
        assert is_d_separated(pm, {"A"}, {"B"}, set()) is False
        assert is_d_separated(pm, {"A"}, {"B"}, {"A"}) is True


class TestDirectRule2:
    """Test verify_rule2 on a graph NOT used by the pipeline."""

    def test_instrument_rule2_not_applicable(self):
        from do_calculus import verify_rule2
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # X_vars={}, Z_vars={X}: can we replace do(X) with observe(X) for Y?
        # G_underline_X: remove outgoing from X (X->Y removed)
        # Remaining: I->X, Z->X, Z->Y
        # d-sep({Y},{X},{})? Path Y<-Z->X active. False.
        assert verify_rule2(pm, set(), {"X"}, {"Y"}, set()) is False

    def test_instrument_rule2_with_conditioning(self):
        from do_calculus import verify_rule2
        pm = {"I": [], "Z": [], "X": ["I", "Z"], "Y": ["X", "Z"]}
        # X_vars={}, Z_vars={X}, W_vars={Z}
        # G_underline_X: remove outgoing from X (X->Y removed)
        # Remaining: I->X, Z->X, Z->Y
        # d-sep({Y},{X},{Z})? Fork Y<-Z->X blocked by Z. True.
        assert verify_rule2(pm, set(), {"X"}, {"Y"}, {"Z"}) is True


class TestDirectCounterfactual:
    """Test compute_counterfactual_te on SCMs NOT used by the pipeline."""

    def test_simple_direct_effect(self):
        from query_engine import compute_counterfactual_te
        from scm import SCM
        from variable import Variable
        from mechanism import linear_mechanism, identity_mechanism

        np.random.seed(99)
        scm = SCM()
        scm.add_variable(Variable("X"))
        scm.add_variable(Variable("Y"))
        scm.add_edge("X", "Y")
        scm.set_mechanism("X", identity_mechanism())
        scm.set_mechanism("Y", linear_mechanism({"X": 2.0}))

        ctf = compute_counterfactual_te(
            scm, "X", "Y", 1.0, 0.0, ["X"], [0.0])
        assert abs(ctf - 2.0) < 0.2, f"CTF-TE should be ~2.0, got {ctf}"

    def test_no_causal_effect(self):
        from query_engine import compute_counterfactual_te
        from scm import SCM
        from variable import Variable
        from mechanism import linear_mechanism, identity_mechanism

        np.random.seed(77)
        scm = SCM()
        scm.add_variable(Variable("Z"))
        scm.add_variable(Variable("X"))
        scm.add_variable(Variable("Y"))
        scm.add_edge("Z", "X")
        scm.add_edge("Z", "Y")
        scm.set_mechanism("Z", identity_mechanism())
        scm.set_mechanism("X", linear_mechanism({"Z": 0.5}))
        scm.set_mechanism("Y", linear_mechanism({"Z": 1.0}))

        ctf = compute_counterfactual_te(
            scm, "X", "Y", 1.0, 0.0, ["X"], [0.0])
        assert abs(ctf) < 0.2, f"CTF-TE should be ~0, got {ctf}"
