#!/usr/bin/env python3
"""
Pipeline: load graph from YAML, run causal queries, write results to SQLite + DOT.
"""

import json
import os
import sqlite3
import sys

import numpy as np
import pydot
import yaml

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
from mechanisms import MECHANISMS


def load_scm_from_yaml(yaml_path, n_samples=200000):
    """Load graph definition from YAML, construct SCM with mechanisms."""
    with open(yaml_path) as f:
        graph_def = yaml.safe_load(f)

    scm = SCM(n_samples=n_samples)

    for node_def in graph_def["nodes"]:
        visible = node_def.get("visible", True)
        num_values = node_def.get("num_values", 2)
        var = Variable(node_def["name"], num_values=num_values, visible=visible)
        scm.add_variable(var)

    for edge in graph_def["edges"]:
        scm.add_edge(edge[0], edge[1])

    for name, mech_fn in MECHANISMS.items():
        if name in scm.variables:
            scm.set_mechanism(name, mech_fn)

    return scm


def run_ate_queries(config, conn):
    """Run ATE queries and write to database."""
    for q in config.get("ate_queries", []):
        np.random.seed(q["seed"])
        scm = load_scm_from_yaml("/app/graph.yaml", n_samples=q["n_samples"])
        engine = QueryEngine(n_samples=q["n_samples"])
        ate = engine.evaluate_ate(scm, q["treatment"], q["outcome"], q["t1"], q["t0"])

        conn.execute(
            "INSERT INTO ate_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            (q["id"], q["treatment"], q["outcome"], q["t1"], q["t0"],
             ate, q["n_samples"]),
        )
    conn.commit()


def run_ctf_te_queries(config, conn):
    """Run Ctf-TE queries and write to database."""
    for q in config.get("ctf_te_queries", []):
        np.random.seed(q["seed"])
        scm = load_scm_from_yaml("/app/graph.yaml", n_samples=q["n_samples"])
        engine = QueryEngine(n_samples=q["n_samples"])
        ctf = engine.evaluate_ctf_te(
            scm, q["treatment"], q["outcome"],
            q["factual_vars"], q["factual_vals"],
            q["t1"], q["t0"], q.get("target_y_val"),
        )

        factual_cond = json.dumps(
            dict(zip(q["factual_vars"], [float(v) for v in q["factual_vals"]]))
        )
        conn.execute(
            "INSERT INTO ctf_te_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (q["id"], q["treatment"], q["outcome"], factual_cond,
             q["t1"], q["t0"], ctf, q["n_samples"]),
        )
    conn.commit()


def run_dsep_tests(config, conn):
    """Run d-separation tests and write to database."""
    scm = load_scm_from_yaml("/app/graph.yaml", n_samples=10)
    adj = build_mutilated_graph(scm)

    for t in config.get("d_separation_tests", []):
        result = is_d_separated(
            adj, set(t["x_nodes"]), set(t["y_nodes"]), set(t["z_nodes"])
        )
        conn.execute(
            "INSERT INTO d_separation_results VALUES (?, ?, ?, ?, ?)",
            (t["id"], json.dumps(t["x_nodes"]), json.dumps(t["y_nodes"]),
             json.dumps(t["z_nodes"]), int(result)),
        )
    conn.commit()


def write_admg(conn):
    """Compute ADMG and write edges to database + DOT file."""
    scm = load_scm_from_yaml("/app/graph.yaml", n_samples=10)
    directed, bidirected, visible_vars = extract_latent_projection(scm)

    for src, dsts in directed.items():
        for dst in dsts:
            conn.execute(
                "INSERT INTO admg_edges VALUES (?, ?, ?)",
                ("directed", src, dst),
            )
    for edge in bidirected:
        nodes = sorted(edge)
        conn.execute(
            "INSERT INTO admg_edges VALUES (?, ?, ?)",
            ("bidirected", nodes[0], nodes[1]),
        )
    conn.commit()

    graph = pydot.Dot("admg", graph_type="digraph")
    for v in visible_vars:
        graph.add_node(pydot.Node(v))

    for src, dsts in directed.items():
        for dst in dsts:
            graph.add_edge(pydot.Edge(src, dst))

    for edge in bidirected:
        nodes = sorted(edge)
        graph.add_edge(pydot.Edge(nodes[0], nodes[1], dir="both", style="dashed"))

    with open("/app/admg.dot", "w") as f:
        f.write(graph.to_string())


def run_backdoor(config, conn):
    """Run backdoor queries and write to database."""
    scm = load_scm_from_yaml("/app/graph.yaml", n_samples=10)
    adj = build_mutilated_graph(scm)

    hidden = set()
    for name, var in scm.variables.items():
        if not var.visible and not var.exogenous:
            hidden.add(name)

    for q in config.get("backdoor_queries", []):
        result = find_backdoor_adjustment(
            adj, q["treatment"], q["outcome"], hidden_vars=hidden
        )
        if result is not None:
            adj_set = json.dumps(sorted(result))
            is_id = 1
        else:
            adj_set = None
            is_id = 0

        conn.execute(
            "INSERT INTO backdoor_results VALUES (?, ?, ?, ?)",
            (q["treatment"], q["outcome"], adj_set, is_id),
        )
    conn.commit()


def main():
    with open("/app/queries.yaml") as f:
        config = yaml.safe_load(f)

    if os.path.exists("/app/results.db"):
        os.remove("/app/results.db")

    conn = sqlite3.connect("/app/results.db")
    with open("/app/schema.sql") as f:
        conn.executescript(f.read())

    run_ate_queries(config, conn)
    run_ctf_te_queries(config, conn)
    run_dsep_tests(config, conn)
    write_admg(conn)
    run_backdoor(config, conn)

    conn.close()
    print("Pipeline complete. Results in /app/results.db, ADMG in /app/admg.dot")


if __name__ == "__main__":
    main()
