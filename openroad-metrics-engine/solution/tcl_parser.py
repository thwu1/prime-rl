#!/usr/bin/env python3
"""
Parse OpenROAD flow_metrics.tcl to extract metric definitions
and variable resolution mappings into metric_defs.json.
"""

import re
import json


def parse_tcl_metrics(tcl_path):
    """
    Extract metric definitions and variable mappings from the Tcl source.

    Parses define_metric calls to get metric names, comparison operators,
    and tolerance expressions. Analyzes save_metric_limits to discover
    which metrics are used as variables in tolerance expressions and how
    variable names are derived from metric keys via regexp decomposition.
    """
    with open(tcl_path) as f:
        content = f.read()

    # Handle Tcl line continuations (backslash-newline joins lines)
    content_joined = content.replace('\\\n', ' ')

    # Extract define_metric calls
    # Tcl format: define_metric "name" "header1" "header2" field_width "fmt" "cmp_op" {limit_expr}
    metrics = []
    pattern = (
        r'define_metric\s+'
        r'"([^"]+)"\s+'       # name (required, non-empty)
        r'"([^"]*)"\s+'       # header1 (may be empty)
        r'"([^"]*)"\s+'       # header2 (may be empty)
        r'(\d+)\s+'           # field_width
        r'"([^"]+)"\s+'       # fmt
        r'"([^"]+)"\s+'       # cmp_op
        r'\{([^}]+)\}'        # limit_expr in Tcl braces
    )

    for match in re.finditer(pattern, content_joined):
        name = match.group(1)
        cmp_op = match.group(6)
        limit_expr_tcl = match.group(7).strip()

        # Convert Tcl expression to Python-compatible expression:
        # Remove $ prefix from variable references ($value -> value)
        py_expr = limit_expr_tcl.replace('$', '')

        metrics.append({
            "name": name,
            "comparison": cmp_op,
            "tolerance_expr": py_expr
        })

    # Extract variable mapping from save_metric_limits procedure.
    # The Tcl code iterates over specific metric keys and uses:
    #   regexp "(...)::(.*)" $metric ignore tool var
    #   set $var $value
    # This dynamically creates local variables (e.g., clock_period, instance_count)
    # from the metric values, which are then available when evaluating
    # tolerance expressions via Tcl's expr command.
    variable_map = {}

    var_foreach = re.search(
        r'foreach\s+metric\s+\{([^}]+)\}',
        content_joined
    )
    if var_foreach:
        metric_refs = re.findall(r'"([^"]+)"', var_foreach.group(1))
        for metric_ref in metric_refs:
            # Apply the same regexp the Tcl code uses: "(...)::(.*)"
            # First group matches exactly 3 chars (tool prefix),
            # second group captures everything after :: (variable name)
            m = re.match(r'(.{3})::(.*)', metric_ref)
            if m:
                var_name = m.group(2)
                variable_map[var_name] = metric_ref

    return {
        "variable_map": variable_map,
        "metrics": metrics
    }


if __name__ == "__main__":
    defs = parse_tcl_metrics("/app/tcl_source/flow_metrics.tcl")
    with open("/app/metric_defs.json", "w") as f:
        json.dump(defs, f, indent=4)
    print(f"Extracted {len(defs['metrics'])} metric definitions")
    print(f"Variable map: {defs['variable_map']}")
