
"""
MIB Circuit Evaluation Pipeline.
Evaluates circuit discovery methods using the MIB benchmark protocol.
"""

import gzip
import json
import math
import sqlite3
import sys

sys.path.insert(0, '/app')
from simulator import CircuitSimulator

SPARSITY_LEVELS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]


class MIBEvaluator:
    """Evaluate circuit discovery methods on the MIB benchmark."""

    def __init__(self, db_path, simulator_config_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.simulator = CircuitSimulator(simulator_config_path)
        self._load_data()

    def _load_data(self):
        """Load all required data from the database."""
        self.edge_meta = {}
        for row in self.conn.execute("SELECT edge_name, edge_type, weight FROM edges"):
            self.edge_meta[row["edge_name"]] = {
                "type": row["edge_type"],
                "weight": row["weight"],
            }
        self.n_edges = len(self.edge_meta)

        self.importance_scores = {}
        for row in self.conn.execute(
            "SELECT method, task, edge_name, score FROM importance_scores"
        ):
            key = (row["method"], row["task"])
            if key not in self.importance_scores:
                self.importance_scores[key] = {}
            self.importance_scores[key][row["edge_name"]] = row["score"]

        self.task_params = {}
        for row in self.conn.execute(
            "SELECT task, baseline_score, corrupted_score FROM simulator_config"
        ):
            self.task_params[row["task"]] = {
                "baseline": row["baseline_score"],
                "corrupted": row["corrupted_score"],
            }

        self.ground_truth = {}
        for row in self.conn.execute(
            "SELECT task, edge_name FROM ground_truth WHERE in_circuit = 1"
        ):
            self.ground_truth.setdefault(row["task"], set()).add(row["edge_name"])

    def _rank_edges(self, scores_dict, k):
        """Select top-k edges ranked by importance score, ties broken by name."""
        ranked = sorted(scores_dict.items(), key=lambda x: (-x[1], x[0]))
        return [name for name, _ in ranked[:k]]

    def _faithfulness(self, active_edges, task):
        """Compute normalized faithfulness for a set of active edges."""
        baseline = self.task_params[task]["baseline"]
        corrupted = self.task_params[task]["corrupted"]
        raw = self.simulator.evaluate(active_edges, task)
        return (baseline - raw) / (baseline - corrupted)

    def _weighted_edge_count(self, active_edges):
        """Sum of parameter weights for active edges."""
        return sum(self.edge_meta[e]["weight"] for e in active_edges)

    def _trapezoidal(self, xs, ys):
        """Trapezoidal numerical integration."""
        area = 0.0
        for i in range(len(xs) - 1):
            area += (xs[i + 1] - xs[i]) * (ys[i] + ys[i + 1]) / 2
        return area

    def evaluate_pair(self, method, task):
        """Evaluate one method-task pair at all sparsity levels."""
        scores = self.importance_scores[(method, task)]
        faithfulnesses = []
        wecs = []

        for p in SPARSITY_LEVELS:
            k = round(p * self.n_edges)
            if k == 0:
                faithfulnesses.append(0.0)
                wecs.append(0)
            else:
                selected = self._rank_edges(scores, k)
                faithfulnesses.append(self._faithfulness(selected, task))
                wecs.append(self._weighted_edge_count(selected))

        # Linear-scale aggregate metrics
        cpr = self._trapezoidal(SPARSITY_LEVELS, faithfulnesses)
        cmd_vals = [abs(1 - f) for f in faithfulnesses]
        cmd = self._trapezoidal(SPARSITY_LEVELS, cmd_vals)

        # Log-scale aggregate metrics
        log_x = [math.log10(p) for p in SPARSITY_LEVELS]
        cpr_log = self._trapezoidal(log_x, faithfulnesses)
        cmd_log = self._trapezoidal(log_x, cmd_vals)

        return {
            "faithfulnesses": faithfulnesses,
            "weighted_edge_counts": wecs,
            "cpr": cpr,
            "cmd": cmd,
            "cpr_log": cpr_log,
            "cmd_log": cmd_log,
        }

    def compute_auroc(self, method, task):
        """Compute AUROC for edge-importance quality assessment."""
        scores = self.importance_scores[(method, task)]
        gt = self.ground_truth[task]
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))

        n_pos = len(gt)
        n_neg = self.n_edges - n_pos
        if n_pos == 0 or n_neg == 0:
            return 0.5

        tp = fp = 0
        tprs, fprs = [0.0], [0.0]
        for name, _ in ranked:
            if name in gt:
                tp += 1
            else:
                fp += 1
            tprs.append(tp / n_pos)
            fprs.append(fp / n_neg)

        return self._trapezoidal(fprs, tprs)

    def run_full_evaluation(self, methods, tasks):
        """Run complete evaluation across all method-task pairs."""
        results = {"methods": {}, "auroc": {}, "ranking": {}}

        for method in methods:
            results["methods"][method] = {}
            results["auroc"][method] = {}
            for task in tasks:
                results["methods"][method][task] = self.evaluate_pair(method, task)
                results["auroc"][method][task] = self.compute_auroc(method, task)

        # Method rankings
        avg_cpr = {
            m: sum(results["methods"][m][t]["cpr"] for t in tasks) / len(tasks)
            for m in methods
        }
        avg_cmd = {
            m: sum(results["methods"][m][t]["cmd"] for t in tasks) / len(tasks)
            for m in methods
        }
        results["ranking"]["by_cpr"] = sorted(
            methods, key=lambda m: avg_cpr[m], reverse=True
        )
        results["ranking"]["by_cmd"] = sorted(methods, key=lambda m: avg_cmd[m])

        return results


if __name__ == "__main__":
    evaluator = MIBEvaluator("/app/mib.db", "/app/simulator_config.json")
    results = evaluator.run_full_evaluation(
        methods=["eap", "eap_ig", "act_patch"], tasks=["ioi", "mcqa"]
    )
    with open("/app/pipeline_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/pipeline_results.json")
