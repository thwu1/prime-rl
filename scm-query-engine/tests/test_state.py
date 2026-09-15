
"""
Tests for causal inference pipeline: algorithm correctness + tool integration outputs.
"""

import os
import sqlite3
import sys

import numpy as np
import pydot
import pytest

sys.path.insert(0, "/app")

from causal_lib.variable import Variable
from causal_lib.scm import SCM
from causal_lib.query_engine import QueryEngine
from causal_lib.graph_analysis import (
    build_mutilated_graph,
    is_d_separated,
    extract_latent_projection,
    find_backdoor_adjustment,
)


# ------------------------------------------------------------------ #
#  Shared test SCM builder
# ------------------------------------------------------------------ #

def build_test_scm(n_samples=200000, seed=42):
    """
    Build a 5-variable discrete binary SCM for testing.

    Graph (endogenous edges only):
        X --> T --> M --> Y
              ^              ^
              |              |
              H -------------+

    H is hidden (visible=False).
    """
    np.random.seed(seed)
    scm = SCM(n_samples=n_samples)

    X = Variable("X", num_values=2)
    H = Variable("H", num_values=2, visible=False)
    T = Variable("T", num_values=2)
    M = Variable("M", num_values=2)
    Y = Variable("Y", num_values=2)

    for v in [X, H, T, M, Y]:
        scm.add_variable(v)

    scm.add_edge("X", "T")
    scm.add_edge("H", "T")
    scm.add_edge("T", "M")
    scm.add_edge("M", "Y")
    scm.add_edge("H", "Y")

    def mech_X(pv):
        return (pv["U_X"] >= 0.5).astype(float)

    def mech_H(pv):
        return (pv["U_H"] >= 0.5).astype(float)

    def mech_T(pv):
        u_disc = (pv["U_T"] >= 0.5).astype(float)
        return ((pv["X"] + pv["H"] + u_disc) % 2).astype(float)

    def mech_M(pv):
        return (pv["T"] * (pv["U_M"] >= 0.3)).astype(float)

    def mech_Y(pv):
        u_disc = (pv["U_Y"] >= 0.3).astype(float)
        return ((pv["M"] + pv["H"] + u_disc) >= 2).astype(float)

    scm.set_mechanism("X", mech_X)
    scm.set_mechanism("H", mech_H)
    scm.set_mechanism("T", mech_T)
    scm.set_mechanism("M", mech_M)
    scm.set_mechanism("Y", mech_Y)

    return scm


def endogenous_adj():
    return {
        "X": ["T"],
        "H": ["T", "Y"],
        "T": ["M"],
        "M": ["Y"],
        "Y": [],
    }


# ================================================================== #
#  Algorithm tests — direct import verification
# ================================================================== #

class TestATE:

    def test_ate_correct_value(self):
        np.random.seed(42)
        scm = build_test_scm(n_samples=200000, seed=42)
        engine = QueryEngine(n_samples=200000)
        ate = engine.evaluate_ate(scm, "T", "Y", 1.0, 0.0)
        assert abs(ate - 0.35) < 0.03, (
            f"ATE(T->Y) should be ~0.35, got {ate:.4f}"
        )

    def test_ate_upstream_no_effect(self):
        np.random.seed(123)
        scm = build_test_scm(n_samples=200000, seed=123)
        engine = QueryEngine(n_samples=200000)
        ate = engine.evaluate_ate(scm, "T", "X", 1.0, 0.0)
        assert abs(ate) < 0.02, (
            f"ATE(T->X) should be ~0, got {ate:.4f}"
        )


class TestCtfTE:

    def test_ctf_te_m_given_t1(self):
        np.random.seed(42)
        scm = build_test_scm(n_samples=200000, seed=42)
        engine = QueryEngine(n_samples=200000)
        ctf = engine.evaluate_ctf_te(
            scm, "T", "M",
            factual_var_names=["T"],
            factual_vals=[1.0],
            t1_val=1.0, t0_val=0.0,
            target_y_val=1.0,
        )
        assert abs(ctf - 0.7) < 0.03, (
            f"Ctf-TE(T->M | T=1) should be ~0.7, got {ctf:.4f}"
        )

    def test_ctf_te_y_given_m0(self):
        np.random.seed(42)
        scm = build_test_scm(n_samples=300000, seed=42)
        engine = QueryEngine(n_samples=300000)
        ctf = engine.evaluate_ctf_te(
            scm, "T", "Y",
            factual_var_names=["M"],
            factual_vals=[0.0],
            t1_val=1.0, t0_val=0.0,
            target_y_val=1.0,
        )
        expected = 3.5 / 13.0
        assert abs(ctf - expected) < 0.03, (
            f"Ctf-TE(T->Y | M=0) should be ~{expected:.4f}, got {ctf:.4f}"
        )


class TestGraphAnalysis:

    def test_mutilated_remove_incoming(self):
        scm = build_test_scm(n_samples=10, seed=0)
        adj = build_mutilated_graph(scm, remove_incoming_to=["T"])
        assert "T" not in adj.get("X", []), "X->T should be removed"
        assert "T" not in adj.get("H", []), "H->T should be removed"
        assert "M" in adj.get("T", []), "T->M should remain"
        assert "Y" in adj.get("H", []), "H->Y should remain"

    def test_d_separation_chain_blocked(self):
        adj = endogenous_adj()
        assert is_d_separated(adj, {"X"}, {"M"}, {"T"}) is True

    def test_d_separation_collider_opened(self):
        adj = endogenous_adj()
        assert is_d_separated(adj, {"X"}, {"Y"}, {"T"}) is False

    def test_d_separation_unconditional_collider_blocks(self):
        """Without conditioning, collider T blocks the path X -> T <- H."""
        adj = endogenous_adj()
        assert is_d_separated(adj, {"X"}, {"H"}, set()) is True

    def test_d_separation_descendant_of_collider(self):
        adj = endogenous_adj()
        assert is_d_separated(adj, {"X"}, {"Y"}, {"M"}) is False

    def test_latent_projection_structure(self):
        scm = build_test_scm(n_samples=10, seed=0)
        directed, bidirected, visible_vars = extract_latent_projection(scm)
        assert set(visible_vars) == {"X", "T", "M", "Y"}
        assert "H" not in visible_vars

        all_directed = set()
        for src, dsts in directed.items():
            for d in dsts:
                all_directed.add((src, d))
        assert all_directed == {("X", "T"), ("T", "M"), ("M", "Y")}, (
            f"Unexpected directed edges: {all_directed}"
        )
        assert frozenset({"T", "Y"}) in bidirected
        assert len(bidirected) == 1

    def test_backdoor_visible_confounder(self):
        adj = {"C": ["X", "Y"], "X": ["Y"], "Y": []}
        result = find_backdoor_adjustment(adj, "X", "Y", hidden_vars=set())
        assert result is not None, "Should find valid adjustment set"
        assert "C" in result, f"C should be in adjustment set, got {result}"

    def test_backdoor_hidden_confounder_fails(self):
        adj = {"H": ["X", "Y"], "X": ["Y"], "Y": []}
        result = find_backdoor_adjustment(adj, "X", "Y", hidden_vars={"H"})
        assert result is None, f"No valid adjustment should exist, got {result}"


# ================================================================== #
#  Pipeline output tests — SQLite database verification
# ================================================================== #

DB_PATH = "/app/results.db"


class TestPipelineDB:

    def _conn(self):
        assert os.path.exists(DB_PATH), (
            f"Pipeline output {DB_PATH} not found — run_pipeline.py must be executed"
        )
        return sqlite3.connect(DB_PATH)

    def test_ate_results_correct(self):
        conn = self._conn()
        rows = conn.execute("SELECT query_id, ate_estimate FROM ate_results").fetchall()
        conn.close()
        results = {r[0]: r[1] for r in rows}
        assert len(results) == 2, f"Expected 2 ATE results, got {len(results)}"
        assert abs(results["ate_t_y"] - 0.35) < 0.03, (
            f"ATE(T->Y) in DB should be ~0.35, got {results['ate_t_y']:.4f}"
        )
        assert abs(results["ate_t_x"]) < 0.02, (
            f"ATE(T->X) in DB should be ~0, got {results['ate_t_x']:.4f}"
        )

    def test_ctf_te_results_correct(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT query_id, ctf_te_estimate FROM ctf_te_results"
        ).fetchall()
        conn.close()
        results = {r[0]: r[1] for r in rows}
        assert len(results) == 2, f"Expected 2 Ctf-TE results, got {len(results)}"
        assert abs(results["ctf_t_m"] - 0.7) < 0.03
        assert abs(results["ctf_t_y"] - 3.5 / 13.0) < 0.03

    def test_dsep_results_correct(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT test_id, is_d_separated FROM d_separation_results"
        ).fetchall()
        conn.close()
        results = {r[0]: bool(r[1]) for r in rows}
        assert results["dsep_chain"] is True, "X _||_ M | T should hold"
        assert results["dsep_collider"] is False, "X _||_ Y | T should NOT hold"
        assert results["dsep_unconditional"] is True, "X _||_ H | {} should hold"
        assert results["dsep_descendant"] is False, "X _||_ Y | M should NOT hold"

    def test_admg_directed_edges_in_db(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT source_node, target_node FROM admg_edges WHERE edge_type='directed'"
        ).fetchall()
        conn.close()
        edges = {(r[0], r[1]) for r in rows}
        assert edges == {("X", "T"), ("T", "M"), ("M", "Y")}, (
            f"Expected directed edges {{X->T, T->M, M->Y}}, got {edges}"
        )

    def test_admg_bidirected_edges_in_db(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT source_node, target_node FROM admg_edges WHERE edge_type='bidirected'"
        ).fetchall()
        conn.close()
        edges = {frozenset({r[0], r[1]}) for r in rows}
        assert frozenset({"T", "Y"}) in edges, "Missing bidirected T<->Y"
        assert len(edges) == 1, f"Expected 1 bidirected edge, got {len(edges)}"

    def test_backdoor_result_in_db(self):
        conn = self._conn()
        row = conn.execute(
            "SELECT is_identifiable FROM backdoor_results "
            "WHERE treatment='T' AND outcome='Y'"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing backdoor result for T->Y"
        assert row[0] == 0, (
            "T->Y should not be identifiable via backdoor (hidden confounder H)"
        )


# ================================================================== #
#  Pipeline output tests — ADMG DOT file verification
# ================================================================== #

DOT_PATH = "/app/admg.dot"


class TestADMGDot:

    def _load_graph(self):
        assert os.path.exists(DOT_PATH), (
            f"ADMG DOT file {DOT_PATH} not found — run_pipeline.py must be executed"
        )
        graphs = pydot.graph_from_dot_file(DOT_PATH)
        assert graphs is not None and len(graphs) > 0, "Failed to parse ADMG DOT file"
        return graphs[0]

    def test_dot_has_visible_nodes_only(self):
        g = self._load_graph()
        node_names = {
            n.get_name().strip('"')
            for n in g.get_nodes()
            if n.get_name().strip('"') not in ("node", "edge", "graph", "")
        }
        assert {"X", "T", "M", "Y"}.issubset(node_names), (
            f"Missing visible nodes, got {node_names}"
        )
        assert "H" not in node_names, "Hidden node H should not appear in ADMG"

    def test_dot_has_bidirected_edge(self):
        g = self._load_graph()
        bidirected_found = False
        for edge in g.get_edges():
            src = edge.get_source().strip('"')
            dst = edge.get_destination().strip('"')
            attrs = edge.obj_dict.get("attributes", {})
            dir_attr = str(attrs.get("dir", "")).strip('"')
            if {src, dst} == {"T", "Y"} and dir_attr == "both":
                bidirected_found = True
        assert bidirected_found, "ADMG should contain bidirected edge T <-> Y with dir=both"
