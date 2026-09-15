#!/usr/bin/env python3
"""OpenROAD Flow Metrics Regression Engine.

Replicates the OpenROAD metrics validation system (from flow_metrics.tcl)
in Python. Supports generating tolerance limits from reference runs,
checking metrics against limits, margin analysis, and run comparison.

Metric limit expressions reference:
  $value          - the metric's own value from the reference run
  $clock_period   - resolved from DRT::clock_period in the same metrics file
  $instance_count - resolved from IFP::instance_count in the same metrics file

Expressions may use min(), int(), and standard arithmetic.
"""

import json
import sys
import os
import argparse
import math


def load_json(path):
    """Load and return parsed JSON from a file path."""
    with open(path) as f:
        return json.load(f)


def save_json(data, path):
    """Write data as formatted JSON to a file path."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_metric_defs():
    """Load metric definitions from /app/metric_defs.json."""
    defs_path = os.environ.get("METRIC_DEFS", "/app/metric_defs.json")
    return load_json(defs_path)


def resolve_cross_metric_variables(metrics):
    """Extract cross-metric variables ($clock_period, $instance_count)
    from the metrics dictionary. These are used in limit expressions
    for TNS and slack metrics."""
    variables = {}
    if "DRT::clock_period" in metrics:
        variables["clock_period"] = float(metrics["DRT::clock_period"])
    if "IFP::instance_count" in metrics:
        variables["instance_count"] = float(metrics["IFP::instance_count"])
    return variables


def evaluate_limit_expr(expr, value, variables):
    """Evaluate a limit expression with variable substitution.

    Replaces $value, $clock_period, $instance_count in the expression
    string with their numeric values, then evaluates the resulting
    Python expression using a restricted namespace.
    """
    s = expr.replace("$value", repr(float(value)))
    s = s.replace("$clock_period", repr(float(variables.get("clock_period", 0.0))))
    s = s.replace("$instance_count", repr(float(variables.get("instance_count", 0.0))))

    safe_globals = {"__builtins__": {}}
    safe_locals = {
        "min": min,
        "max": max,
        "int": int,
        "abs": abs,
    }
    return eval(s, safe_globals, safe_locals)


def check_comparison(value, limit, cmp_op):
    """Check if a metric value passes the comparison against its limit.

    Returns True if the comparison holds (metric passes), False otherwise.
    """
    v = float(value)
    l = float(limit)
    if cmp_op == "<":
        return v < l
    elif cmp_op == "<=":
        return v <= l
    elif cmp_op == ">":
        return v > l
    elif cmp_op == ">=":
        return v >= l
    elif cmp_op == "==":
        return v == l
    else:
        raise ValueError(f"Unknown comparison operator: {cmp_op}")


def compute_margin(value, limit, cmp_op):
    """Compute absolute margin between a metric value and its limit.

    For < and <=: margin = limit - value (value should be below limit)
    For > and >=: margin = value - limit (value should be above limit)

    Positive margin means passing; negative means failing.
    """
    v = float(value)
    l = float(limit)
    if cmp_op in ("<", "<="):
        return l - v
    elif cmp_op in (">", ">="):
        return v - l
    elif cmp_op == "==":
        return 0.0 if v == l else -abs(v - l)
    else:
        raise ValueError(f"Unknown comparison operator: {cmp_op}")


def cmd_generate_limits(args):
    """Generate tolerance limits from a reference metrics file."""
    metric_defs = load_metric_defs()
    metrics = load_json(args.metrics_file)
    variables = resolve_cross_metric_variables(metrics)

    limits = {}
    for mdef in metric_defs:
        name = mdef["name"]
        if name in metrics:
            value = float(metrics[name])
            limit = evaluate_limit_expr(mdef["limit_expr"], value, variables)
            limits[name] = str(limit)

    save_json(limits, args.output)


def cmd_check(args):
    """Check metrics against limits and report pass/fail."""
    metric_defs = load_metric_defs()
    metrics = load_json(args.metrics_file)
    limits = load_json(args.limits_file)

    results = []
    errors = []
    all_pass = True

    for mdef in metric_defs:
        name = mdef["name"]
        cmp_op = mdef["cmp_op"]

        if name not in metrics:
            errors.append(f"missing {name} in metrics")
            continue
        if name not in limits:
            errors.append(f"missing {name} in limits")
            continue

        value = float(metrics[name])
        limit = float(limits[name])
        passed = check_comparison(value, limit, cmp_op)

        if not passed:
            all_pass = False

        results.append({
            "name": name,
            "value": value,
            "limit": limit,
            "cmp_op": cmp_op,
            "status": "pass" if passed else "fail",
        })

    output = {
        "overall": "pass" if all_pass and not errors else "fail",
        "metrics": results,
        "errors": errors,
    }

    print(json.dumps(output, indent=2))
    sys.exit(0 if all_pass and not errors else 1)


def cmd_margin_report(args):
    """Compute margin analysis for each metric."""
    metric_defs = load_metric_defs()
    metrics = load_json(args.metrics_file)
    limits = load_json(args.limits_file)

    results = []

    for mdef in metric_defs:
        name = mdef["name"]
        cmp_op = mdef["cmp_op"]

        if name not in metrics or name not in limits:
            continue

        value = float(metrics[name])
        limit = float(limits[name])
        margin = compute_margin(value, limit, cmp_op)
        passed = check_comparison(value, limit, cmp_op)

        results.append({
            "name": name,
            "value": value,
            "limit": limit,
            "cmp_op": cmp_op,
            "margin": margin,
            "status": "pass" if passed else "fail",
        })

    output = {"metrics": results}
    print(json.dumps(output, indent=2))


def cmd_compare(args):
    """Compare two metrics runs and compute deltas."""
    metric_defs = load_metric_defs()
    metrics1 = load_json(args.metrics_file1)
    metrics2 = load_json(args.metrics_file2)

    results = []

    for mdef in metric_defs:
        name = mdef["name"]

        if name not in metrics1 or name not in metrics2:
            continue

        v1 = float(metrics1[name])
        v2 = float(metrics2[name])
        delta = v2 - v1

        if abs(v1) > 1e-15:
            percent_change = (delta / abs(v1)) * 100.0
        else:
            percent_change = None

        results.append({
            "name": name,
            "value1": v1,
            "value2": v2,
            "delta": delta,
            "percent_change": percent_change,
        })

    output = {"metrics": results}
    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="OpenROAD Flow Metrics Regression Engine"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_parser = subparsers.add_parser("generate-limits",
        help="Generate tolerance limits from reference metrics")
    gen_parser.add_argument("metrics_file", help="Path to reference metrics JSON")
    gen_parser.add_argument("-o", "--output", required=True,
        help="Path to write generated limits JSON")

    check_parser = subparsers.add_parser("check",
        help="Check metrics against limits")
    check_parser.add_argument("metrics_file", help="Path to metrics JSON to check")
    check_parser.add_argument("limits_file", help="Path to limits JSON")

    margin_parser = subparsers.add_parser("margin-report",
        help="Compute margin analysis")
    margin_parser.add_argument("metrics_file", help="Path to metrics JSON")
    margin_parser.add_argument("limits_file", help="Path to limits JSON")

    compare_parser = subparsers.add_parser("compare",
        help="Compare two metrics runs")
    compare_parser.add_argument("metrics_file1", help="Path to first metrics JSON")
    compare_parser.add_argument("metrics_file2", help="Path to second metrics JSON")

    args = parser.parse_args()

    if args.command == "generate-limits":
        cmd_generate_limits(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "margin-report":
        cmd_margin_report(args)
    elif args.command == "compare":
        cmd_compare(args)


if __name__ == "__main__":
    main()
