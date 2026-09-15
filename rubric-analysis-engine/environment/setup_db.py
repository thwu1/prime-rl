#!/usr/bin/env python3
"""Create the rubrics.db SQLite database with rubric trees, gradings, and verified results."""

import sqlite3
import os

DB_PATH = "/app/data/rubrics.db"


def create_schema(conn):
    conn.executescript("""
        CREATE TABLE rubric_nodes (
            rubric_name TEXT NOT NULL,
            node_id TEXT NOT NULL,
            parent_id TEXT,
            requirements TEXT,
            weight REAL NOT NULL,
            task_category TEXT,
            PRIMARY KEY (rubric_name, node_id)
        );
        CREATE TABLE gradings (
            grading_id TEXT NOT NULL,
            rubric_name TEXT NOT NULL,
            node_id TEXT NOT NULL,
            score INTEGER NOT NULL CHECK(score IN (0, 1)),
            PRIMARY KEY (grading_id, node_id)
        );
        CREATE TABLE verified_results (
            result_id TEXT PRIMARY KEY,
            result_type TEXT NOT NULL,
            rubric_name TEXT NOT NULL,
            grading_id TEXT,
            extra_key TEXT,
            verified_value REAL NOT NULL
        );
        CREATE TABLE agreement_pairs (
            pair_id TEXT PRIMARY KEY,
            rubric_name TEXT NOT NULL,
            grading_id_1 TEXT NOT NULL,
            grading_id_2 TEXT NOT NULL
        );
        CREATE TABLE verified_agreement (
            pair_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            verified_value REAL NOT NULL,
            PRIMARY KEY (pair_id, metric_name)
        );
    """)


def insert_rubric_alpha(conn):
    nodes = [
        ("alpha", "root", None, "The core contributions of the paper have been reproduced.", 1, None),
        ("alpha", "env-setup", "root", "The environment and infrastructure have been set up correctly.", 2, None),
        ("alpha", "deps-installed", "env-setup", "All required dependencies are installed.", 3, "Code Development"),
        ("alpha", "data-loaded", "env-setup", "The required datasets have been downloaded and loaded.", 2, "Code Development"),
        ("alpha", "config-valid", "env-setup", "Configuration files are valid and complete.", 1, "Code Development"),
        ("alpha", "method-impl", "root", "The core methods from the paper have been implemented.", 5, None),
        ("alpha", "model-arch", "method-impl", "The model architecture has been implemented.", 3, None),
        ("alpha", "encoder", "model-arch", "The encoder module has been implemented.", 2, "Code Development"),
        ("alpha", "decoder", "model-arch", "The decoder module has been implemented.", 2, "Code Development"),
        ("alpha", "attention", "model-arch", "The attention mechanism has been implemented.", 1, "Code Development"),
        ("alpha", "training-loop", "method-impl", "The training loop has been implemented.", 2, None),
        ("alpha", "forward-pass", "training-loop", "The forward pass executes correctly.", 1, "Execution"),
        ("alpha", "backward-pass", "training-loop", "The backward pass executes correctly.", 1, "Execution"),
        ("alpha", "optimizer", "training-loop", "The optimizer is correctly configured.", 1, "Code Development"),
        ("alpha", "eval-pipeline", "method-impl", "The evaluation pipeline has been implemented.", 1, None),
        ("alpha", "metrics", "eval-pipeline", "Evaluation metrics are correctly computed.", 1, "Code Development"),
        ("alpha", "eval-exec", "eval-pipeline", "The evaluation script executes successfully.", 1, "Execution"),
        ("alpha", "results", "root", "The experimental results match the paper.", 3, None),
        ("alpha", "table1-match", "results", "Table 1 results are reproduced within tolerance.", 2, "Result Match"),
        ("alpha", "table2-match", "results", "Table 2 results are reproduced within tolerance.", 2, "Result Match"),
        ("alpha", "figure1-match", "results", "Figure 1 results are reproduced.", 1, "Result Match"),
        ("alpha", "ablation-exec", "results", "The ablation study has been executed.", 1, "Execution"),
    ]
    conn.executemany("INSERT INTO rubric_nodes VALUES (?,?,?,?,?,?)", nodes)


def insert_rubric_beta(conn):
    nodes = [
        ("beta", "root-beta", None, "Paper Beta has been reproduced.", 1, None),
        ("beta", "impl", "root-beta", "Implementation is complete.", 3, None),
        ("beta", "algo-core", "impl", "Core algorithm implemented.", 2, "Code Development"),
        ("beta", "algo-ext", "impl", "Algorithm extension implemented.", 1, "Code Development"),
        ("beta", "exp", "root-beta", "Experiments have been run.", 2, None),
        ("beta", "exp-run", "exp", "Experiments executed successfully.", 1, "Execution"),
        ("beta", "exp-match", "exp", "Results match the paper.", 1, "Result Match"),
    ]
    conn.executemany("INSERT INTO rubric_nodes VALUES (?,?,?,?,?,?)", nodes)


def insert_rubric_gamma(conn):
    nodes = [
        ("gamma", "root-gamma", None, "Paper Gamma has been reproduced.", 1, None),
        # Research branch
        ("gamma", "research", "root-gamma", "Research foundations are sound.", 5, None),
        ("gamma", "literature", "research", "Literature review is thorough.", 2, None),
        ("gamma", "survey-complete", "literature", "Survey of related work is complete.", 3, "Code Development"),
        ("gamma", "citations-valid", "literature", "All citations are valid and relevant.", 1, "Code Development"),
        ("gamma", "gaps-identified", "literature", "Research gaps are correctly identified.", 2, "Code Development"),
        ("gamma", "methodology", "research", "Methodology is well-designed.", 4, None),
        ("gamma", "design-correct", "methodology", "Experimental design is correct.", 3, "Code Development"),
        ("gamma", "hypotheses", "methodology", "Hypotheses are clearly stated and testable.", 2, "Code Development"),
        ("gamma", "controls", "methodology", "Appropriate controls are in place.", 1, "Code Development"),
        ("gamma", "novelty", "research", "Novel contribution is clear.", 1, None),
        ("gamma", "contribution", "novelty", "Core contribution is well-articulated.", 1, "Code Development"),
        # Implementation branch
        ("gamma", "implementation", "root-gamma", "Implementation is complete and correct.", 7, None),
        ("gamma", "core-algo", "implementation", "Core algorithm is implemented.", 5, None),
        ("gamma", "data-pipeline", "core-algo", "Data pipeline is functional.", 2, None),
        ("gamma", "ingestion", "data-pipeline", "Data ingestion works correctly.", 3, "Code Development"),
        ("gamma", "preprocessing", "data-pipeline", "Data preprocessing is correct.", 2, "Code Development"),
        ("gamma", "validation", "data-pipeline", "Data validation catches errors.", 1, "Code Development"),
        ("gamma", "model", "core-algo", "Model is implemented.", 4, None),
        ("gamma", "architecture", "model", "Model architecture matches the paper.", 3, "Code Development"),
        ("gamma", "loss-function", "model", "Loss function is correctly implemented.", 2, "Code Development"),
        ("gamma", "optimizer-config", "model", "Optimizer configuration is correct.", 1, "Code Development"),
        ("gamma", "inference", "core-algo", "Inference pipeline works.", 1, None),
        ("gamma", "predict", "inference", "Prediction produces correct output.", 1, "Code Development"),
        ("gamma", "testing", "implementation", "Testing is adequate.", 2, None),
        ("gamma", "unit-tests", "testing", "Unit tests pass.", 1, "Execution"),
        ("gamma", "integration-tests", "testing", "Integration tests pass.", 1, "Execution"),
        ("gamma", "coverage", "testing", "Test coverage is sufficient.", 1, "Execution"),
        # Experiments branch
        ("gamma", "experiments", "root-gamma", "Experiments are complete.", 4, None),
        ("gamma", "setup", "experiments", "Experimental setup is reproducible.", 1, None),
        ("gamma", "env-reproducible", "setup", "Environment is reproducible.", 1, "Execution"),
        ("gamma", "execution", "experiments", "Experiments executed successfully.", 2, None),
        ("gamma", "training-runs", "execution", "Training runs completed.", 2, "Execution"),
        ("gamma", "ablation-runs", "execution", "Ablation studies completed.", 1, "Execution"),
        ("gamma", "exp-results", "experiments", "Results match expectations.", 3, None),
        ("gamma", "table-match", "exp-results", "Table results reproduced.", 2, "Result Match"),
        ("gamma", "figure-match", "exp-results", "Figure results reproduced.", 1, "Result Match"),
        ("gamma", "stat-significance", "exp-results", "Statistical significance confirmed.", 1, "Result Match"),
        # Documentation branch
        ("gamma", "documentation", "root-gamma", "Documentation is complete.", 2, None),
        ("gamma", "readme", "documentation", "README is comprehensive.", 2, "Code Development"),
        ("gamma", "api-docs", "documentation", "API documentation is complete.", 1, "Code Development"),
    ]
    conn.executemany("INSERT INTO rubric_nodes VALUES (?,?,?,?,?,?)", nodes)


def insert_gradings(conn):
    gradings_data = {
        ("alpha_judge1", "alpha"): {
            "deps-installed": 1, "data-loaded": 1, "config-valid": 1,
            "encoder": 1, "decoder": 0, "attention": 1,
            "forward-pass": 1, "backward-pass": 0, "optimizer": 1,
            "metrics": 1, "eval-exec": 0,
            "table1-match": 0, "table2-match": 0, "figure1-match": 0,
            "ablation-exec": 1,
        },
        ("alpha_judge2", "alpha"): {
            "deps-installed": 1, "data-loaded": 0, "config-valid": 1,
            "encoder": 1, "decoder": 1, "attention": 0,
            "forward-pass": 0, "backward-pass": 1, "optimizer": 1,
            "metrics": 0, "eval-exec": 1,
            "table1-match": 1, "table2-match": 0, "figure1-match": 1,
            "ablation-exec": 0,
        },
        ("alpha_ground_truth", "alpha"): {
            "deps-installed": 1, "data-loaded": 1, "config-valid": 1,
            "encoder": 1, "decoder": 1, "attention": 1,
            "forward-pass": 1, "backward-pass": 1, "optimizer": 1,
            "metrics": 1, "eval-exec": 1,
            "table1-match": 1, "table2-match": 0, "figure1-match": 0,
            "ablation-exec": 1,
        },
        ("beta_judge1", "beta"): {
            "algo-core": 1, "algo-ext": 0, "exp-run": 1, "exp-match": 0,
        },
        ("gamma_judge1", "gamma"): {
            "survey-complete": 1, "citations-valid": 0, "gaps-identified": 1,
            "design-correct": 1, "hypotheses": 1, "controls": 0,
            "contribution": 1,
            "ingestion": 1, "preprocessing": 1, "validation": 0,
            "architecture": 1, "loss-function": 0, "optimizer-config": 0,
            "predict": 1,
            "unit-tests": 0, "integration-tests": 1, "coverage": 0,
            "env-reproducible": 1,
            "training-runs": 1, "ablation-runs": 0,
            "table-match": 0, "figure-match": 0, "stat-significance": 0,
            "readme": 1, "api-docs": 0,
        },
        ("gamma_judge2", "gamma"): {
            "survey-complete": 0, "citations-valid": 1, "gaps-identified": 1,
            "design-correct": 0, "hypotheses": 1, "controls": 1,
            "contribution": 0,
            "ingestion": 1, "preprocessing": 0, "validation": 1,
            "architecture": 1, "loss-function": 1, "optimizer-config": 1,
            "predict": 0,
            "unit-tests": 1, "integration-tests": 0, "coverage": 1,
            "env-reproducible": 0,
            "training-runs": 0, "ablation-runs": 1,
            "table-match": 1, "figure-match": 1, "stat-significance": 0,
            "readme": 0, "api-docs": 1,
        },
    }
    for (gid, rubric), scores in gradings_data.items():
        for nid, score in scores.items():
            conn.execute(
                "INSERT INTO gradings VALUES (?,?,?,?)",
                (gid, rubric, nid, score),
            )


def insert_verified_results(conn):
    """Insert a subset of verified results for the agent to calibrate against."""
    verified = [
        # Root scores (4 of 6 — agent must generalize to alpha_judge2 and gamma_judge2)
        ("vs_alpha_j1", "root_score", "alpha", "alpha_judge1", None, 0.552778),
        ("vs_alpha_gt", "root_score", "alpha", "alpha_ground_truth", None, 0.850000),
        ("vs_beta_j1", "root_score", "beta", "beta_judge1", None, 0.600000),
        ("vs_gamma_j1", "root_score", "gamma", "gamma_judge1", None, 0.620811),
        # Sensitivity (effective weight) samples
        ("vw_alpha_deps", "sensitivity", "alpha", None, "deps-installed", 0.100000),
        ("vw_alpha_attn", "sensitivity", "alpha", None, "attention", 0.050000),
        ("vw_alpha_cfg", "sensitivity", "alpha", None, "config-valid", 0.033333),
        ("vw_beta_core", "sensitivity", "beta", None, "algo-core", 0.400000),
        ("vw_gamma_arch", "sensitivity", "gamma", None, "architecture", 0.079365),
        # Category scores (3 verified)
        ("vc_alpha_j1_cd", "category_score", "alpha", "alpha_judge1", "Code Development", 0.817259),
        ("vc_alpha_j1_ex", "category_score", "alpha", "alpha_judge1", "Execution", 0.520548),
        ("vc_gamma_j1_cd", "category_score", "gamma", "gamma_judge1", "Code Development", 0.746032),
    ]
    conn.executemany(
        "INSERT INTO verified_results VALUES (?,?,?,?,?,?)", verified
    )


def insert_agreement_pairs(conn):
    pairs = [
        ("alpha_j1_vs_j2", "alpha", "alpha_judge1", "alpha_judge2"),
        ("alpha_j1_vs_gt", "alpha", "alpha_judge1", "alpha_ground_truth"),
        ("gamma_j1_vs_j2", "gamma", "gamma_judge1", "gamma_judge2"),
    ]
    conn.executemany("INSERT INTO agreement_pairs VALUES (?,?,?,?)", pairs)

    # Verified agreement values reflect weighted metrics per scoring policy
    verified_agree = [
        ("alpha_j1_vs_j2", "cohens_kappa", -0.258381),
        ("alpha_j1_vs_j2", "accuracy", 0.388889),
        ("alpha_j1_vs_gt", "cohens_kappa", 0.358128),
        ("alpha_j1_vs_gt", "accuracy", 0.702778),
        ("gamma_j1_vs_j2", "accuracy", 0.226190),
    ]
    conn.executemany(
        "INSERT INTO verified_agreement VALUES (?,?,?)", verified_agree
    )


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)
    insert_rubric_alpha(conn)
    insert_rubric_beta(conn)
    insert_rubric_gamma(conn)
    insert_gradings(conn)
    insert_verified_results(conn)
    insert_agreement_pairs(conn)
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
