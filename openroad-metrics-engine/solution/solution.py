#!/usr/bin/env python3
"""
OpenROAD Flow Metrics Regression Engine.

Implements the metrics limit-checking and regression analysis system
used in OpenROAD's CI infrastructure for physical design flows.
"""

import ast
import json
import operator
import sys
from pathlib import Path

DEFAULT_DEFS_PATH = "/app/metric_defs.json"

COMPARISON_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}

SAFE_FUNCTIONS = {
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "abs": abs,
}


class ExpressionEvaluator:
    """Safely evaluates OpenROAD tolerance expressions using AST parsing."""

    def evaluate(self, expr, variables):
        """
        Evaluate a tolerance expression with variable substitution.

        Args:
            expr: Python-compatible arithmetic expression string.
            variables: Dict mapping variable names to float values.
                       'value' = golden value of current metric.
                       Other keys come from variable_map in definitions.

        Returns:
            Computed float result.
        """
        tree = ast.parse(expr, mode='eval')
        return self._eval_node(tree.body, variables)

    def _eval_node(self, node, variables):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise ValueError(f"Unknown variable: {node.id}")
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, variables)
            right = self._eval_node(node.right, variables)
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                return left / right
            elif isinstance(node.op, ast.FloorDiv):
                return left // right
            elif isinstance(node.op, ast.Mod):
                return left % right
            elif isinstance(node.op, ast.Pow):
                return left ** right
            else:
                raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, variables)
            if isinstance(node.op, ast.USub):
                return -operand
            elif isinstance(node.op, ast.UAdd):
                return +operand
            else:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            else:
                raise ValueError(f"Unsupported call expression")
            if func_name not in SAFE_FUNCTIONS:
                raise ValueError(f"Unsupported function: {func_name}")
            args = [self._eval_node(arg, variables) for arg in node.args]
            return SAFE_FUNCTIONS[func_name](*args)
        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")


class MetricsChecker:
    """Checks flow metrics against golden-derived limits."""

    def __init__(self, defs):
        """
        Args:
            defs: Parsed metric_defs.json dict with 'variable_map' and 'metrics' keys.
        """
        self.variable_map = defs.get("variable_map", {})
        self.definitions = {m["name"]: m for m in defs["metrics"]}
        self.evaluator = ExpressionEvaluator()

    def _resolve_variables(self, metric_name, golden):
        """Build variable dict for expression evaluation."""
        variables = {"value": float(golden[metric_name])}
        for var_name, metric_ref in self.variable_map.items():
            if metric_ref in golden:
                variables[var_name] = float(golden[metric_ref])
        return variables

    def compute_limits(self, golden):
        """
        Compute limit values from golden metrics using tolerance expressions.

        Args:
            golden: Dict mapping metric names to values (float or string).

        Returns:
            Dict mapping metric names to computed limit values.
        """
        limits = {}
        for name, defn in self.definitions.items():
            if name not in golden:
                continue
            variables = self._resolve_variables(name, golden)
            limit = self.evaluator.evaluate(defn["tolerance_expr"], variables)
            limits[name] = limit
        return limits

    def check_metric(self, name, actual, limit):
        """
        Check if a single metric passes its comparison test.

        Args:
            name: Metric name (must be in definitions).
            actual: Actual metric value.
            limit: Computed limit value.

        Returns:
            True if the metric passes.
        """
        defn = self.definitions[name]
        op = COMPARISON_OPS[defn["comparison"]]
        return op(float(actual), float(limit))

    def check_run(self, golden, actual):
        """
        Check all metrics in a run against golden-derived limits.

        Args:
            golden: Golden reference metrics dict.
            actual: Actual run metrics dict.

        Returns:
            Dict with 'metrics' (list of per-metric results) and
            'summary' with total/passed/failed/pass_rate.
        """
        limits = self.compute_limits(golden)
        results = []

        for name in sorted(self.definitions.keys()):
            if name not in actual or name not in limits:
                continue
            actual_val = float(actual[name])
            limit_val = limits[name]
            passed = self.check_metric(name, actual_val, limit_val)
            results.append({
                "name": name,
                "actual": actual_val,
                "limit": limit_val,
                "comparison": self.definitions[name]["comparison"],
                "passed": passed,
            })

        total = len(results)
        passed_count = sum(1 for r in results if r["passed"])
        failed_count = total - passed_count

        return {
            "metrics": results,
            "summary": {
                "total": total,
                "passed": passed_count,
                "failed": failed_count,
                "pass_rate": passed_count / total if total > 0 else 0.0,
            }
        }


class RegressionAnalyzer:
    """Analyzes regression patterns across multiple flow runs."""

    def __init__(self, checker):
        """
        Args:
            checker: MetricsChecker instance.
        """
        self.checker = checker

    def analyze(self, golden, runs):
        """
        Analyze multiple runs for regression patterns.

        Args:
            golden: Golden reference metrics dict.
            runs: List of run metrics dicts.

        Returns:
            Dict with:
            - 'runs': per-run check results
            - 'systematic_failures': metrics failing in ALL runs (name -> count)
            - 'severity_score': total failures / total checks (0.0 to 1.0)
        """
        run_results = []
        metric_failure_counts = {}

        for run in runs:
            result = self.checker.check_run(golden, run)
            run_results.append(result)
            for m in result["metrics"]:
                if not m["passed"]:
                    metric_failure_counts[m["name"]] = (
                        metric_failure_counts.get(m["name"], 0) + 1
                    )

        num_runs = len(runs)
        systematic = {
            name: count
            for name, count in metric_failure_counts.items()
            if count == num_runs
        }

        total_checks = sum(r["summary"]["total"] for r in run_results)
        total_failures = sum(r["summary"]["failed"] for r in run_results)
        severity = total_failures / total_checks if total_checks > 0 else 0.0

        return {
            "runs": run_results,
            "systematic_failures": systematic,
            "severity_score": severity,
        }


def load_metrics(path):
    """Load a metrics JSON file, converting all values to float."""
    with open(path) as f:
        data = json.load(f)
    return {k: float(v) for k, v in data.items()}


def load_defs(path):
    """Load metric definitions from JSON file."""
    with open(path) as f:
        return json.load(f)


def main():
    if len(sys.argv) < 2:
        print("Usage: metrics_engine.py <command> [args]", file=sys.stderr)
        print("Commands: limits, check, analyze", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    # Extract --defs flag
    defs_path = DEFAULT_DEFS_PATH
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--defs" and i + 1 < len(args):
            defs_path = args[i + 1]
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1
    args = filtered_args

    defs = load_defs(defs_path)
    checker = MetricsChecker(defs)

    if command == "limits":
        if len(args) < 1:
            print("Usage: metrics_engine.py limits <golden.json>", file=sys.stderr)
            sys.exit(1)
        golden = load_metrics(args[0])
        limits = checker.compute_limits(golden)
        print(json.dumps(limits, indent=2))

    elif command == "check":
        if len(args) < 2:
            print("Usage: metrics_engine.py check <golden.json> <run.json>",
                  file=sys.stderr)
            sys.exit(1)
        golden = load_metrics(args[0])
        actual = load_metrics(args[1])
        result = checker.check_run(golden, actual)
        print(json.dumps(result, indent=2))

    elif command == "analyze":
        if len(args) < 2:
            print("Usage: metrics_engine.py analyze <golden.json> <run1.json> ...",
                  file=sys.stderr)
            sys.exit(1)
        golden = load_metrics(args[0])
        runs = [load_metrics(p) for p in args[1:]]
        analyzer = RegressionAnalyzer(checker)
        result = analyzer.analyze(golden, runs)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
