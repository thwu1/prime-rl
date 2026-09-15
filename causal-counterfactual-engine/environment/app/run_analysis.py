#!/usr/bin/env python3

"""Causal analysis pipeline: builds test SCMs, runs d-separation,
do-calculus Rule 2 verification, and causal effect estimation."""

import json
import os
import numpy as np
from datetime import datetime

from scm import SCM
from variable import Variable
from mechanism import linear_mechanism, identity_mechanism
from graph_utils import is_d_separated
from do_calculus import verify_rule2
from query_engine import compute_ate, compute_counterfactual_te


def build_chain():
    """Chain: X -> M -> Y
    X = U_X, M = 2*X + U_M, Y = 1.5*M + U_Y
    """
    scm = SCM()
    scm.add_variable(Variable("X"))
    scm.add_variable(Variable("M"))
    scm.add_variable(Variable("Y"))
    scm.add_edge("X", "M")
    scm.add_edge("M", "Y")
    scm.set_mechanism("X", identity_mechanism())
    scm.set_mechanism("M", linear_mechanism({"X": 2.0}))
    scm.set_mechanism("Y", linear_mechanism({"M": 1.5}))
    pm = {"X": [], "M": ["X"], "Y": ["M"]}
    return scm, pm


def build_fork():
    """Fork: X <- Z -> Y
    Z = U_Z, X = 0.8*Z + U_X, Y = 1.2*Z + U_Y
    """
    scm = SCM()
    scm.add_variable(Variable("Z"))
    scm.add_variable(Variable("X"))
    scm.add_variable(Variable("Y"))
    scm.add_edge("Z", "X")
    scm.add_edge("Z", "Y")
    scm.set_mechanism("Z", identity_mechanism())
    scm.set_mechanism("X", linear_mechanism({"Z": 0.8}))
    scm.set_mechanism("Y", linear_mechanism({"Z": 1.2}))
    pm = {"Z": [], "X": ["Z"], "Y": ["Z"]}
    return scm, pm


def build_collider():
    """Collider: X -> M <- Y
    X = U_X, Y = U_Y, M = X + Y + U_M
    """
    scm = SCM()
    scm.add_variable(Variable("X"))
    scm.add_variable(Variable("Y"))
    scm.add_variable(Variable("M"))
    scm.add_edge("X", "M")
    scm.add_edge("Y", "M")
    scm.set_mechanism("X", identity_mechanism())
    scm.set_mechanism("Y", identity_mechanism())
    scm.set_mechanism("M", linear_mechanism({"X": 1.0, "Y": 1.0}))
    pm = {"X": [], "Y": [], "M": ["X", "Y"]}
    return scm, pm


def build_diamond():
    """Diamond: Z -> X, Z -> W, X -> Y, W -> Y
    Z = U_Z, X = 0.8*Z + U_X, W = 0.6*Z + U_W, Y = 1.5*X + 0.9*W + U_Y
    """
    scm = SCM()
    scm.add_variable(Variable("Z"))
    scm.add_variable(Variable("X"))
    scm.add_variable(Variable("W"))
    scm.add_variable(Variable("Y"))
    scm.add_edge("Z", "X")
    scm.add_edge("Z", "W")
    scm.add_edge("X", "Y")
    scm.add_edge("W", "Y")
    scm.set_mechanism("Z", identity_mechanism())
    scm.set_mechanism("X", linear_mechanism({"Z": 0.8}))
    scm.set_mechanism("W", linear_mechanism({"Z": 0.6}))
    scm.set_mechanism("Y", linear_mechanism({"X": 1.5, "W": 0.9}))
    pm = {"Z": [], "X": ["Z"], "W": ["Z"], "Y": ["X", "W"]}
    return scm, pm


def main():
    np.random.seed(42)

    chain_scm, chain_pm = build_chain()
    fork_scm, fork_pm = build_fork()
    collider_scm, collider_pm = build_collider()
    diamond_scm, diamond_pm = build_diamond()

    os.makedirs("/app/output", exist_ok=True)

    # D-separation tests
    dsep_tests = [
        {"graph_name": "chain", "X_set": ["X"], "Y_set": ["Y"], "Z_set": ["M"],
         "result": is_d_separated(chain_pm, {"X"}, {"Y"}, {"M"})},
        {"graph_name": "chain", "X_set": ["X"], "Y_set": ["Y"], "Z_set": [],
         "result": is_d_separated(chain_pm, {"X"}, {"Y"}, set())},
        {"graph_name": "fork", "X_set": ["X"], "Y_set": ["Y"], "Z_set": ["Z"],
         "result": is_d_separated(fork_pm, {"X"}, {"Y"}, {"Z"})},
        {"graph_name": "fork", "X_set": ["X"], "Y_set": ["Y"], "Z_set": [],
         "result": is_d_separated(fork_pm, {"X"}, {"Y"}, set())},
        {"graph_name": "collider", "X_set": ["X"], "Y_set": ["Y"], "Z_set": [],
         "result": is_d_separated(collider_pm, {"X"}, {"Y"}, set())},
        {"graph_name": "collider", "X_set": ["X"], "Y_set": ["Y"], "Z_set": ["M"],
         "result": is_d_separated(collider_pm, {"X"}, {"Y"}, {"M"})},
        {"graph_name": "diamond", "X_set": ["X"], "Y_set": ["W"], "Z_set": [],
         "result": is_d_separated(diamond_pm, {"X"}, {"W"}, set())},
        {"graph_name": "diamond", "X_set": ["X"], "Y_set": ["W"], "Z_set": ["Z"],
         "result": is_d_separated(diamond_pm, {"X"}, {"W"}, {"Z"})},
        {"graph_name": "diamond", "X_set": ["X"], "Y_set": ["W"], "Z_set": ["Y"],
         "result": is_d_separated(diamond_pm, {"X"}, {"W"}, {"Y"})},
        {"graph_name": "diamond", "X_set": ["Z"], "Y_set": ["Y"],
         "Z_set": ["X", "W"],
         "result": is_d_separated(diamond_pm, {"Z"}, {"Y"}, {"X", "W"})},
    ]

    # Do-calculus Rule 2 tests
    rule2_tests = [
        {"graph_name": "chain",
         "X_vars": ["X"], "Z_vars": ["M"], "Y_vars": ["Y"], "W_vars": [],
         "applicable": verify_rule2(chain_pm, {"X"}, {"M"}, {"Y"}, set())},
        {"graph_name": "fork",
         "X_vars": [], "Z_vars": ["X"], "Y_vars": ["Y"], "W_vars": [],
         "applicable": verify_rule2(fork_pm, set(), {"X"}, {"Y"}, set())},
        {"graph_name": "diamond",
         "X_vars": ["Z"], "Z_vars": ["X"], "Y_vars": ["Y"], "W_vars": [],
         "applicable": verify_rule2(diamond_pm, {"Z"}, {"X"}, {"Y"}, set())},
        {"graph_name": "diamond",
         "X_vars": [], "Z_vars": ["X"], "Y_vars": ["Y"], "W_vars": [],
         "applicable": verify_rule2(diamond_pm, set(), {"X"}, {"Y"}, set())},
    ]

    # Causal effect estimation
    effects = []

    chain_ate = compute_ate(chain_scm, "X", "Y", 1.0, 0.0)
    chain_ctf = compute_counterfactual_te(
        chain_scm, "X", "Y", 1.0, 0.0, ["X"], [0.0])
    effects.append({
        "graph_name": "chain", "treatment": "X", "outcome": "Y",
        "ate": float(chain_ate), "counterfactual_te": float(chain_ctf),
        "ate_cf_consistent": abs(chain_ate - chain_ctf) < 0.5
    })

    fork_ate = compute_ate(fork_scm, "X", "Y", 1.0, 0.0)
    fork_ctf = compute_counterfactual_te(
        fork_scm, "X", "Y", 1.0, 0.0, ["X"], [0.0])
    effects.append({
        "graph_name": "fork", "treatment": "X", "outcome": "Y",
        "ate": float(fork_ate), "counterfactual_te": float(fork_ctf),
        "ate_cf_consistent": abs(fork_ate - fork_ctf) < 0.5
    })

    diamond_ate = compute_ate(diamond_scm, "X", "Y", 1.0, 0.0)
    diamond_ctf = compute_counterfactual_te(
        diamond_scm, "X", "Y", 1.0, 0.0, ["X"], [0.0])
    effects.append({
        "graph_name": "diamond", "treatment": "X", "outcome": "Y",
        "ate": float(diamond_ate), "counterfactual_te": float(diamond_ctf),
        "ate_cf_consistent": abs(diamond_ate - diamond_ctf) < 0.5
    })

    # Write report
    report = {
        "d_separation_tests": dsep_tests,
        "do_calculus_tests": rule2_tests,
        "causal_effects": effects,
        "timestamp": datetime.now().isoformat()
    }

    with open("/app/output/analysis_report.json", "w") as f:
        json.dump(report, f, indent=2)

    with open("/app/output/.completed", "w") as f:
        f.write("done")

    print(f"Analysis complete: {len(dsep_tests)} d-sep tests, "
          f"{len(rule2_tests)} rule2 tests, {len(effects)} effect estimates")


if __name__ == "__main__":
    main()
