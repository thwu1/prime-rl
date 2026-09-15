#!/usr/bin/env python3
"""
dbt Pipeline Execution Planner CLI.

Analyzes a dbt manifest and produces execution plans.
Supports four subcommands: select, schedule, critical-path, impact.
"""

import argparse
import json
import re
import sys
from collections import defaultdict

MANIFEST_PATH = "/app/manifest.json"


# ═══════════════════════════════════════════════
# DATA LOADING (implemented)
# ═══════════════════════════════════════════════

def load_manifest(path):
    """Load manifest and merge nodes, sources, exposures into one dict."""
    with open(path) as f:
        data = json.load(f)
    all_nodes = {}
    for section in ("nodes", "sources", "exposures"):
        if section in data:
            all_nodes.update(data[section])
    return all_nodes


def get_name(unique_id):
    """Derive display name from unique_id (dots after second become underscores)."""
    parts = unique_id.split(".", 2)
    return parts[2].replace(".", "_") if len(parts) >= 3 else unique_id


def get_resource_name(unique_id):
    """Derive resource name from unique_id (dots preserved)."""
    parts = unique_id.split(".", 2)
    return parts[2] if len(parts) >= 3 else unique_id


# ═══════════════════════════════════════════════
# CORE FUNCTIONS — implement these
# ═══════════════════════════════════════════════

def get_effective_tags(node, all_nodes):
    """Return the effective tag set for a node."""
    raise NotImplementedError("get_effective_tags")


def build_children_index(all_nodes):
    """Build a reverse dependency index: parent_id -> [child_ids]."""
    raise NotImplementedError("build_children_index")


def get_ancestors(node_id, all_nodes, max_depth=-1):
    """Return ancestor unique_ids of node_id (excluding itself). max_depth=-1 means unlimited."""
    raise NotImplementedError("get_ancestors")


def get_descendants(node_id, all_nodes, children_index, max_depth=-1):
    """Return descendant unique_ids of node_id (excluding itself). max_depth=-1 means unlimited."""
    raise NotImplementedError("get_descendants")


def match_base_selector(selector, all_nodes):
    """Match nodes by a base selector string (no graph operators). Return set of unique_ids."""
    raise NotImplementedError("match_base_selector")


def parse_graph_selector(expr):
    """Parse a selector expression into (at_operator, precursor_depth, base_selector, descendant_depth)."""
    raise NotImplementedError("parse_graph_selector")


def evaluate_single_selector(expr, all_nodes, children_index):
    """Evaluate one selector expression (no commas). Return set of unique_ids."""
    raise NotImplementedError("evaluate_single_selector")


def evaluate_select_expr(expr, all_nodes, children_index):
    """Evaluate a --select value (may contain commas). Return set of unique_ids."""
    raise NotImplementedError("evaluate_select_expr")


def resolve_selection(selects, excludes, all_nodes, children_index):
    """Resolve full node selection from --select and --exclude argument lists."""
    raise NotImplementedError("resolve_selection")


def filter_executable(selected, all_nodes, test_behavior):
    """Filter selected nodes to only executable ones based on test_behavior mode."""
    raise NotImplementedError("filter_executable")


def compute_schedule(executable, all_nodes, max_parallel, test_behavior, children_index):
    """Compute the parallel execution schedule. Return result dict."""
    raise NotImplementedError("compute_schedule")


def compute_critical_path(executable, all_nodes):
    """Compute the longest weighted path through the DAG. Return result dict."""
    raise NotImplementedError("compute_critical_path")


def compute_impact(node_id, all_nodes, children_index):
    """Compute downstream impact of modifying a node. Return result dict."""
    raise NotImplementedError("compute_impact")


# ═══════════════════════════════════════════════
# CLI (implemented — do not modify)
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="dbt Pipeline Execution Planner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # select
    p_sel = subparsers.add_parser("select")
    p_sel.add_argument("--select", action="append", dest="selects", default=[])
    p_sel.add_argument("--exclude", action="append", dest="excludes", default=[])

    # schedule
    p_sched = subparsers.add_parser("schedule")
    p_sched.add_argument("--select", action="append", dest="selects", default=[])
    p_sched.add_argument("--exclude", action="append", dest="excludes", default=[])
    p_sched.add_argument("--max-parallel", type=int, required=True)
    p_sched.add_argument("--test-behavior", choices=["none", "included", "barrier"],
                         default="none")

    # critical-path
    p_cp = subparsers.add_parser("critical-path")
    p_cp.add_argument("--select", action="append", dest="selects", default=[])
    p_cp.add_argument("--exclude", action="append", dest="excludes", default=[])
    p_cp.add_argument("--test-behavior", choices=["none", "included", "barrier"],
                       default="none")

    # impact
    p_imp = subparsers.add_parser("impact")
    p_imp.add_argument("--node", required=True)

    args = parser.parse_args()
    all_nodes = load_manifest(MANIFEST_PATH)
    children_index = build_children_index(all_nodes)

    if args.command == "select":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        for uid in sorted(selected):
            print(uid)

    elif args.command == "schedule":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        executable = filter_executable(selected, all_nodes, args.test_behavior)
        result = compute_schedule(executable, all_nodes, args.max_parallel,
                                  args.test_behavior, children_index)
        print(json.dumps(result))

    elif args.command == "critical-path":
        selected = resolve_selection(args.selects, args.excludes, all_nodes,
                                     children_index)
        executable = filter_executable(selected, all_nodes, args.test_behavior)
        result = compute_critical_path(executable, all_nodes)
        print(json.dumps(result))

    elif args.command == "impact":
        result = compute_impact(args.node, all_nodes, children_index)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
