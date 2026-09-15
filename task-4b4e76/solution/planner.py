#!/usr/bin/env python3
"""Codemod Workflow Execution Planner.

Parses Codemod workflow YAML files, validates them, resolves the DAG,
expands matrix strategies, evaluates conditions, tracks state mutations,
and produces a deterministic JSON execution plan.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict

import yaml

CONFIG_PATH = "/app/planner_config.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_workflow(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return data


def validate_workflow(wf):
    errors = []
    if "version" not in wf:
        errors.append("Missing required field: version")
    if "nodes" not in wf or not isinstance(wf.get("nodes"), list):
        errors.append("Missing or invalid required field: nodes")
        return errors

    node_ids = set()
    for node in wf["nodes"]:
        if "id" not in node:
            errors.append("Node missing required field: id")
            continue
        if node["id"] in node_ids:
            errors.append(f"Duplicate node id: {node['id']}")
        node_ids.add(node["id"])

    for node in wf["nodes"]:
        nid = node.get("id", "<unknown>")
        for dep in node.get("depends_on", []):
            if dep not in node_ids:
                errors.append(
                    f"Node '{nid}' depends on nonexistent node '{dep}'"
                )
        if "steps" not in node:
            errors.append(f"Node '{nid}' missing required field: steps")

    return errors


def detect_cycles(nodes):
    graph = {}
    for node in nodes:
        graph[node["id"]] = node.get("depends_on", [])

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in graph}
    path = []
    errors = []

    def dfs(node_id):
        color[node_id] = GRAY
        path.append(node_id)
        for dep in graph.get(node_id, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                idx = path.index(dep)
                cycle = path[idx:] + [dep]
                errors.append(
                    f"Cyclic dependency detected: {' -> '.join(cycle)}"
                )
                return
            if color[dep] == WHITE:
                dfs(dep)
                if errors:
                    return
        path.pop()
        color[node_id] = BLACK

    for nid in sorted(graph):
        if color[nid] == WHITE:
            dfs(nid)
            if errors:
                break

    return errors


def topological_sort(nodes, priority_weights):
    graph = defaultdict(list)
    in_degree = {}
    default_weight = priority_weights.get("_default", 40)

    def sort_key(nid):
        return (priority_weights.get(nid, default_weight), nid)

    for node in nodes:
        nid = node["id"]
        in_degree.setdefault(nid, 0)
        for dep in node.get("depends_on", []):
            graph[dep].append(nid)
            in_degree[nid] = in_degree.get(nid, 0) + 1

    queue = sorted(
        (nid for nid, deg in in_degree.items() if deg == 0),
        key=sort_key,
    )
    result = []

    while queue:
        nid = queue.pop(0)
        result.append(nid)
        for neighbor in graph[nid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=sort_key)

    return result


def resolve_params(wf, overrides):
    params = {}
    schema = wf.get("params", {}) or {}
    schema = schema.get("schema", {}) or {}
    for key, prop in schema.items():
        if key in overrides:
            val = overrides[key]
            ptype = prop.get("type", "string")
            if ptype == "boolean":
                if isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes")
                else:
                    val = bool(val)
            elif ptype == "number":
                val = float(val) if isinstance(val, str) else val
            params[key] = val
        elif "default" in prop:
            params[key] = prop["default"]
    return params


def init_state(wf):
    state = {}
    state_config = wf.get("state") or {}
    state_schema = state_config.get("schema") or {}

    if isinstance(state_schema, list):
        for item in state_schema:
            name = item.get("name")
            if not name:
                continue
            stype = item.get("type", "string")
            if stype == "array":
                state[name] = []
            elif stype == "number":
                state[name] = 0
            else:
                state[name] = None
    elif isinstance(state_schema, dict):
        for name, prop in state_schema.items():
            stype = prop.get("type", "string")
            if stype == "array":
                state[name] = []
            elif stype == "number":
                state[name] = 0
            else:
                state[name] = None

    return state


def resolve_expression(template, context):
    def replace_expr(match):
        expr = match.group(1).strip()
        parts = expr.split(".")
        if len(parts) >= 2:
            ns = parts[0]
            if ns in context:
                val = context[ns]
                for p in parts[1:]:
                    if isinstance(val, dict):
                        val = val.get(p)
                    else:
                        val = None
                        break
                if val is not None:
                    if isinstance(val, bool):
                        return "true" if val else "false"
                    return str(val)
        return match.group(0)

    return re.sub(r"\$\{\{\s*(.+?)\s*\}\}", replace_expr, template)


def resolve_variable(expr, context):
    parts = expr.split(".")
    if len(parts) >= 2:
        ns = parts[0]
        if ns in context:
            val = context[ns]
            for p in parts[1:]:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    return None
            return val
    return expr


def parse_literal(s):
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def evaluate_condition(condition, context):
    if condition is None:
        return True

    condition = condition.strip()

    if " || " in condition:
        parts = condition.split(" || ", 1)
        return evaluate_condition(parts[0], context) or evaluate_condition(
            parts[1], context
        )

    if " && " in condition:
        parts = condition.split(" && ", 1)
        return evaluate_condition(parts[0], context) and evaluate_condition(
            parts[1], context
        )

    for op in ("==", "!=", ">=", "<=", ">", "<"):
        if f" {op} " in condition:
            left_str, right_str = condition.split(f" {op} ", 1)
            left_val = resolve_variable(left_str.strip(), context)
            right_val = parse_literal(right_str.strip())

            if isinstance(right_val, bool):
                if isinstance(left_val, str):
                    left_val = left_val.lower() in ("true", "1", "yes")
                else:
                    left_val = bool(left_val)
            elif isinstance(right_val, (int, float)) and isinstance(
                left_val, str
            ):
                try:
                    left_val = float(left_val)
                except ValueError:
                    pass

            if op == "==":
                return left_val == right_val
            elif op == "!=":
                return left_val != right_val
            elif op == ">":
                return left_val > right_val
            elif op == "<":
                return left_val < right_val
            elif op == ">=":
                return left_val >= right_val
            elif op == "<=":
                return left_val <= right_val

    val = resolve_variable(condition, context)
    return bool(val)


def parse_state_mutations(run_text):
    mutations = []
    for line in run_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_.]*?)(@?=)(.+)$", line)
        if m:
            mutations.append((m.group(1), m.group(2), m.group(3)))
    return mutations


def apply_state_mutations(state, mutations):
    for key, op, value in mutations:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value

        if op == "@=":
            if key not in state or state[key] is None:
                state[key] = []
            state[key].append(parsed)
        else:
            parts = key.split(".")
            target = state
            for p in parts[:-1]:
                if p not in target:
                    target[p] = {}
                target = target[p]
            target[parts[-1]] = parsed


def get_step_type(step):
    for key in (
        "run",
        "js-ast-grep",
        "ast-grep",
        "codemod",
        "ai",
        "shard",
        "install-skill",
    ):
        if key in step:
            return key
    return "unknown"


def compute_plan_digest(execution_plan, digest_salt):
    entries = "|".join(
        f"{t['node_id']}:{t['task_index']}" for t in execution_plan
    )
    digest_input = digest_salt + entries
    return hashlib.sha256(digest_input.encode()).hexdigest()[:16]


def plan_execution(wf, param_overrides, config):
    plan_format_version = config.get("plan_format_version", "unknown")
    priority_weights = config.get("priority_weights", {"_default": 40})
    digest_salt = config.get("digest_salt", "")

    errors = validate_workflow(wf)
    if errors:
        return {
            "plan_format_version": plan_format_version,
            "valid": False,
            "errors": errors,
            "execution_plan": [],
            "final_state": {},
            "plan_digest": compute_plan_digest([], digest_salt),
        }

    cycle_errors = detect_cycles(wf["nodes"])
    if cycle_errors:
        return {
            "plan_format_version": plan_format_version,
            "valid": False,
            "errors": cycle_errors,
            "execution_plan": [],
            "final_state": {},
            "plan_digest": compute_plan_digest([], digest_salt),
        }

    params = resolve_params(wf, param_overrides)
    state = init_state(wf)
    order = topological_sort(wf["nodes"], priority_weights)
    node_map = {n["id"]: n for n in wf["nodes"]}

    execution_plan = []

    for node_id in order:
        node = node_map[node_id]
        strategy = node.get("strategy")

        if strategy and strategy.get("type") == "matrix":
            if strategy.get("values"):
                matrix_items = strategy["values"]
            elif strategy.get("from_state"):
                state_key = strategy["from_state"]
                matrix_items = state.get(state_key, [])
            else:
                matrix_items = [{}]
        else:
            matrix_items = [{}]

        for task_idx, matrix_vals in enumerate(matrix_items):
            if not isinstance(matrix_vals, dict):
                matrix_vals = {}

            context = {
                "params": params,
                "state": state,
                "matrix": matrix_vals,
            }

            steps_plan = []
            for step in node.get("steps", []):
                step_type = get_step_type(step)
                step_entry = {
                    "name": step.get("name", ""),
                    "type": step_type,
                }

                condition = step.get("if")
                will_execute = (
                    evaluate_condition(condition, context)
                    if condition
                    else True
                )
                step_entry["will_execute"] = will_execute

                if step_type == "run":
                    resolved = resolve_expression(step["run"], context)
                    step_entry["resolved_run"] = resolved.strip()
                    if will_execute:
                        mutations = parse_state_mutations(resolved)
                        apply_state_mutations(state, mutations)

                steps_plan.append(step_entry)

            execution_plan.append(
                {
                    "node_id": node_id,
                    "node_name": node.get("name", ""),
                    "task_index": task_idx,
                    "matrix_values": matrix_vals,
                    "steps": steps_plan,
                }
            )

    return {
        "plan_format_version": plan_format_version,
        "valid": True,
        "errors": [],
        "execution_plan": execution_plan,
        "final_state": state,
        "plan_digest": compute_plan_digest(execution_plan, digest_salt),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Codemod Workflow Execution Planner"
    )
    parser.add_argument("workflow", help="Path to workflow YAML file")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Parameter override (key=value)",
    )
    args = parser.parse_args()

    param_overrides = {}
    for p in args.param:
        key, _, value = p.partition("=")
        param_overrides[key] = value

    config = load_config()
    wf = load_workflow(args.workflow)
    result = plan_execution(wf, param_overrides, config)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
