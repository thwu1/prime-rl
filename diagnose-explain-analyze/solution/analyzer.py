#!/usr/bin/env python3
"""TiDB EXPLAIN ANALYZE Diagnostic Engine.

Parses TiDB execution plan output, computes operator-level metrics,
detects performance anti-patterns, persists data to SQLite, generates
Graphviz visualizations, and produces structured JSON diagnostics.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys


# ---------------------------------------------------------------------------
# Time / size parsing
# ---------------------------------------------------------------------------

def parse_time_to_ms(s):
    """Parse a time string (e.g. '3.87s', '2.2ms', '412.5us', '0ns', '2m52s')
    into milliseconds."""
    s = s.strip()
    if not s or s == "0":
        return 0.0
    # Composite: 1m44.809s, 2m52s
    m = re.match(r"^(\d+)m([\d.]+)s$", s)
    if m:
        return int(m.group(1)) * 60_000 + float(m.group(2)) * 1000
    if s.endswith("ms"):
        return float(s[:-2])
    if s.endswith("\u00b5s"):          # µs (micro sign U+00B5)
        return float(s[:-2]) / 1000
    if s.endswith("us"):
        return float(s[:-2]) / 1000
    if s.endswith("ns"):
        return float(s[:-2]) / 1_000_000
    if s.endswith("s"):
        return float(s[:-1]) * 1000
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_size_to_mb(s):
    """Parse a size string (e.g. '856.2 MB', '41.0 KB', '128 Bytes', 'N/A')
    into megabytes."""
    s = s.strip()
    if s in ("N/A", "", "0 Bytes"):
        return 0.0
    if "GB" in s:
        return float(s.replace("GB", "").strip()) * 1024
    if "MB" in s:
        return float(s.replace("MB", "").strip())
    if "KB" in s:
        return float(s.replace("KB", "").strip()) / 1024
    if "Bytes" in s:
        return float(s.replace("Bytes", "").strip()) / (1024 * 1024)
    return 0.0


# ---------------------------------------------------------------------------
# Execution-info parser  (recursive descent for nested key:{...} structures)
# ---------------------------------------------------------------------------

def parse_exec_info(s):
    """Parse a TiDB execution info string into a nested dict."""
    result = {}
    s = s.strip()
    if not s:
        return result

    i = 0
    length = len(s)

    while i < length:
        while i < length and s[i] == " ":
            i += 1
        if i >= length:
            break

        colon_pos = None
        brace_depth = 0
        j = i
        while j < length:
            c = s[j]
            if c == "{":
                brace_depth += 1
            elif c == "}":
                brace_depth -= 1
            elif c == ":" and brace_depth == 0:
                colon_pos = j
                break
            j += 1

        if colon_pos is None:
            break

        key = s[i:colon_pos].strip()
        i = colon_pos + 1

        while i < length and s[i] == " ":
            i += 1
        if i >= length:
            result[key] = ""
            break

        if s[i] == "{":
            brace_depth = 1
            j = i + 1
            while j < length and brace_depth > 0:
                if s[j] == "{":
                    brace_depth += 1
                elif s[j] == "}":
                    brace_depth -= 1
                j += 1
            inner = s[i + 1 : j - 1]
            result[key] = parse_exec_info(inner)
            i = j
        else:
            val_start = i
            brace_depth = 0
            while i < length:
                if s[i] == "{":
                    brace_depth += 1
                elif s[i] == "}":
                    brace_depth -= 1
                elif s[i] == "," and brace_depth == 0:
                    break
                i += 1
            result[key] = s[val_start:i].strip()

        if i < length and s[i] == ",":
            i += 1

    return result


# ---------------------------------------------------------------------------
# Plan file parser
# ---------------------------------------------------------------------------

def parse_plan_file(filepath):
    """Parse a TiDB EXPLAIN ANALYZE plan file into structured data."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    query = ""
    operators = []
    header_found = False
    col_names = []

    for line in lines:
        line = line.rstrip("\n")

        if line.startswith("QUERY:"):
            query = line[6:].strip()
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("+") or "rows in set" in stripped.lower():
            continue

        if not stripped.startswith("|"):
            continue

        raw_split = line.split("|")
        raw_parts = raw_split[1:-1]
        stripped_parts = [p.strip() for p in raw_parts]

        if not header_found:
            col_names = stripped_parts
            header_found = True
            continue

        if len(stripped_parts) != len(col_names):
            continue

        row = dict(zip(col_names, stripped_parts))

        id_raw_full = raw_parts[0]
        depth = 0
        for ci, c in enumerate(id_raw_full):
            if c.isalpha():
                depth = ci // 2
                break

        id_stripped = stripped_parts[0]
        op_name = id_stripped
        for ci, c in enumerate(id_stripped):
            if c.isalpha():
                op_name = id_stripped[ci:].strip()
                break

        exec_info = parse_exec_info(row.get("execution info", ""))

        time_ms = None
        if "time" in exec_info:
            time_ms = parse_time_to_ms(exec_info["time"])

        operator = {
            "id": op_name,
            "depth": depth,
            "task_type": row.get("task", "").strip(),
            "est_rows": float(row.get("estRows", "0")),
            "act_rows": int(float(row.get("actRows", "0"))),
            "exec_info": exec_info,
            "operator_info": row.get("operator info", ""),
            "memory": row.get("memory", "N/A"),
            "disk": row.get("disk", "N/A"),
            "time_ms": time_ms,
            "children": [],
        }
        operators.append(operator)

    tree = _build_tree(operators)
    return {"query": query, "operators": operators, "tree": tree}


def _build_tree(operators):
    """Build operator tree from flat list using depth information."""
    roots = []
    stack = []
    for op in operators:
        d = op["depth"]
        while stack and stack[-1][0] >= d:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(op)
        else:
            roots.append(op)
        stack.append((d, op))
    return roots


# ---------------------------------------------------------------------------
# Self-time computation
# ---------------------------------------------------------------------------

def compute_self_times(operators):
    """Compute self_time_ms for every root operator (recursively)."""
    for op in operators:
        if op["task_type"] == "root" and op["time_ms"] is not None:
            child_root_time = sum(
                c["time_ms"]
                for c in op["children"]
                if c["task_type"] == "root" and c["time_ms"] is not None
            )
            op["self_time_ms"] = max(0.0, op["time_ms"] - child_root_time)
        else:
            op["self_time_ms"] = None
        compute_self_times(op["children"])


# ---------------------------------------------------------------------------
# Bottleneck identification
# ---------------------------------------------------------------------------

def find_bottleneck(tree):
    """Return the id of the root operator with the highest self_time_ms."""
    best_id = None
    best_time = -1.0

    def _walk(ops):
        nonlocal best_id, best_time
        for op in ops:
            if op["task_type"] == "root" and op.get("self_time_ms") is not None:
                if op["self_time_ms"] > best_time:
                    best_time = op["self_time_ms"]
                    best_id = op["id"]
            _walk(op["children"])

    _walk(tree)
    return best_id


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues(tree):
    issues = []
    _detect_recursive(tree, issues)
    return issues


def _detect_recursive(operators, issues):
    for op in operators:
        ei = op["exec_info"]

        # Lock contention
        if "ResolveLock" in ei and isinstance(ei["ResolveLock"], dict):
            resolve_time = parse_time_to_ms(ei["ResolveLock"].get("total_time", "0s"))
            total = op.get("time_ms") or 0
            if total > 0 and resolve_time / total > 0.5:
                backoff = ei.get("txnNotFound_backoff", {})
                if isinstance(backoff, dict):
                    issues.append(
                        {
                            "type": "lock_contention",
                            "operator": op["id"],
                            "details": {
                                "resolve_lock_time_ms": resolve_time,
                                "resolve_lock_pct": round(
                                    resolve_time / total * 100, 2
                                ),
                                "backoff_count": int(backoff.get("num", 0)),
                                "backoff_total_ms": parse_time_to_ms(
                                    backoff.get("total_time", "0s")
                                ),
                            },
                        }
                    )

        # MVCC tombstone scan
        if "cop_task" in ei and isinstance(ei["cop_task"], dict):
            cop = ei["cop_task"]
            num = int(cop.get("num", 0))
            max_pk = int(cop.get("max_proc_keys", 0))
            if num > 50 and max_pk > 100_000:
                scan_dir = _find_scan_direction(op)
                issues.append(
                    {
                        "type": "mvcc_tombstone",
                        "operator": op["id"],
                        "details": {
                            "cop_task_count": num,
                            "max_proc_keys": max_pk,
                            "scan_direction": scan_dir,
                        },
                    }
                )

        # Memory spill
        disk_mb = parse_size_to_mb(op.get("disk", "N/A"))
        if disk_mb > 0:
            mem_mb = parse_size_to_mb(op.get("memory", "N/A"))
            issues.append(
                {
                    "type": "memory_spill",
                    "operator": op["id"],
                    "details": {
                        "memory_mb": round(mem_mb, 1),
                        "disk_mb": round(disk_mb, 1),
                    },
                }
            )

        # Suboptimal hash-join build side
        if op["id"].startswith("HashJoin"):
            build_child = None
            probe_child = None
            for child in op.get("children", []):
                if "(Build)" in child["id"]:
                    build_child = child
                elif "(Probe)" in child["id"]:
                    probe_child = child
            if build_child and probe_child:
                br = build_child["act_rows"]
                pr = probe_child["act_rows"]
                if br > pr:
                    issues.append(
                        {
                            "type": "suboptimal_join_order",
                            "operator": op["id"],
                            "details": {
                                "build_side_rows": br,
                                "probe_side_rows": pr,
                            },
                        }
                    )

        _detect_recursive(op["children"], issues)


def _find_scan_direction(op):
    """Walk descendants to find the IndexFullScan/IndexRangeScan and determine
    scan direction."""
    for child in op.get("children", []):
        if "Scan" in child["id"]:
            oi = child.get("operator_info", "").lower()
            if "desc" in oi:
                return "descending"
            if "keep order:true" in oi:
                return "ascending"
        result = _find_scan_direction(child)
        if result:
            return result
    return "ascending"


# ---------------------------------------------------------------------------
# Concurrency analysis
# ---------------------------------------------------------------------------

def _find_operator(tree, op_id):
    for op in tree:
        if op["id"] == op_id:
            return op
        found = _find_operator(op["children"], op_id)
        if found:
            return found
    return None


def analyze_concurrency(plan, config, operator_id):
    op = _find_operator(plan["tree"], operator_id)
    if not op:
        return None

    ei = op["exec_info"]

    index_conc = 1
    if "index_task" in ei and isinstance(ei["index_task"], dict):
        if "concurrency" in ei["index_task"]:
            index_conc = int(ei["index_task"]["concurrency"])

    table_conc = 1
    if "table_task" in ei and isinstance(ei["table_task"], dict):
        if "concurrency" in ei["table_task"]:
            table_conc = int(ei["table_task"]["concurrency"])

    distsql_conc = config.get("tidb_distsql_scan_concurrency", 15)
    for child in op.get("children", []):
        child_ei = child.get("exec_info", {})
        if "cop_task" in child_ei and isinstance(child_ei["cop_task"], dict):
            dc = child_ei["cop_task"].get("distsql_concurrency")
            if dc is not None:
                distsql_conc = int(dc)
                break

    return {
        "index_task_concurrency": index_conc,
        "table_task_concurrency": table_conc,
        "distsql_concurrency": distsql_conc,
        "max_table_cop_tasks": table_conc * distsql_conc,
    }


# ---------------------------------------------------------------------------
# Comparative analysis
# ---------------------------------------------------------------------------

def compare_plans(all_plans, comparison):
    fast_name = comparison["fast"]
    slow_name = comparison["slow"]
    fast_plan = all_plans.get(fast_name)
    slow_plan = all_plans.get(slow_name)
    if not fast_plan or not slow_plan:
        return None

    fast_time = fast_plan["tree"][0]["time_ms"] if fast_plan["tree"] else 0
    slow_time = slow_plan["tree"][0]["time_ms"] if slow_plan["tree"] else 0

    ratio = slow_time / fast_time if fast_time > 0 else float("inf")

    root_cause = "unknown"
    slow_issues = detect_issues(slow_plan["tree"])
    for issue in slow_issues:
        if issue["type"] == "mvcc_tombstone":
            root_cause = "mvcc_tombstone"
            break

    return {
        "fast_plan": fast_name,
        "slow_plan": slow_name,
        "time_ratio": round(ratio, 1),
        "root_cause": root_cause,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def flatten_operators(operators):
    """Flatten the operator tree into a list for JSON output."""
    result = []
    for op in operators:
        result.append(
            {
                "id": op["id"],
                "task_type": op["task_type"],
                "est_rows": op["est_rows"],
                "act_rows": op["act_rows"],
                "time_ms": op.get("time_ms"),
                "self_time_ms": op.get("self_time_ms"),
            }
        )
        result.extend(flatten_operators(op["children"]))
    return result


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def create_sqlite_db(output, all_plans):
    """Persist parsed operator data and issues into a SQLite database."""
    db_path = "/app/output/operators.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE operators (
        plan_file TEXT,
        operator_id TEXT,
        depth INTEGER,
        task_type TEXT,
        est_rows REAL,
        act_rows INTEGER,
        time_ms REAL,
        self_time_ms REAL,
        parent_operator_id TEXT
    )""")

    c.execute("""CREATE TABLE issues (
        plan_file TEXT,
        issue_type TEXT,
        operator_id TEXT,
        details_json TEXT
    )""")

    for plan_name, plan_data in all_plans.items():
        _insert_operators_recursive(c, plan_name, plan_data["tree"], None)

    for plan_name, plan_out in output["plans"].items():
        for issue in plan_out["issues"]:
            c.execute(
                "INSERT INTO issues VALUES (?,?,?,?)",
                (
                    plan_name,
                    issue["type"],
                    issue["operator"],
                    json.dumps(issue["details"]),
                ),
            )

    conn.commit()
    conn.close()


def _insert_operators_recursive(cursor, plan_file, operators, parent_id):
    for op in operators:
        cursor.execute(
            "INSERT INTO operators VALUES (?,?,?,?,?,?,?,?,?)",
            (
                plan_file,
                op["id"],
                op["depth"],
                op["task_type"],
                op["est_rows"],
                op["act_rows"],
                op.get("time_ms"),
                op.get("self_time_ms"),
                parent_id,
            ),
        )
        _insert_operators_recursive(cursor, plan_file, op["children"], op["id"])


# ---------------------------------------------------------------------------
# Graphviz DOT generation
# ---------------------------------------------------------------------------

def _sanitize_dot_id(name):
    """Create a safe DOT node identifier from an operator name."""
    return name.replace("(", "_").replace(")", "_").replace(".", "_")


def _gen_dot_nodes(operators, lines):
    for op in operators:
        node_id = _sanitize_dot_id(op["id"])
        label = f"{op['id']}\\n{op['task_type']}"
        lines.append(f'    "{node_id}" [label="{label}"];')
        _gen_dot_nodes(op["children"], lines)


def _gen_dot_edges(operators, lines):
    for op in operators:
        parent_id = _sanitize_dot_id(op["id"])
        for child in op["children"]:
            child_id = _sanitize_dot_id(child["id"])
            lines.append(f'    "{parent_id}" -> "{child_id}";')
        _gen_dot_edges(op["children"], lines)


def generate_graphviz(all_plans):
    """Generate DOT and SVG operator tree visualizations for each plan."""
    tree_dir = "/app/output/trees"
    os.makedirs(tree_dir, exist_ok=True)

    for plan_name, plan_data in all_plans.items():
        dot_path = os.path.join(tree_dir, f"{plan_name}.dot")
        svg_path = os.path.join(tree_dir, f"{plan_name}.svg")

        lines = [
            "digraph operators {",
            "    rankdir=TB;",
            '    node [shape=box, fontsize=10, fontname="monospace"];',
        ]
        _gen_dot_nodes(plan_data["tree"], lines)
        _gen_dot_edges(plan_data["tree"], lines)
        lines.append("}")

        with open(dot_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        subprocess.run(
            ["dot", "-Tsvg", dot_path, "-o", svg_path],
            check=True,
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/config.json", "r") as f:
        config = json.load(f)
    with open("/app/manifest.json", "r") as f:
        manifest = json.load(f)

    all_plans = {}
    for plan_file in manifest["plans"]:
        filepath = f"/app/plans/{plan_file}"
        all_plans[plan_file] = parse_plan_file(filepath)

    for plan in all_plans.values():
        compute_self_times(plan["tree"])

    output = {
        "plans": {},
        "concurrency_analysis": {},
        "comparative_analysis": {},
    }

    for name, plan in all_plans.items():
        total_time = plan["tree"][0]["time_ms"] if plan["tree"] else 0
        bottleneck = find_bottleneck(plan["tree"])
        issues = detect_issues(plan["tree"])
        operators = flatten_operators(plan["tree"])

        output["plans"][name] = {
            "total_time_ms": total_time,
            "bottleneck_operator": bottleneck,
            "operators": operators,
            "issues": issues,
        }

    for target in manifest.get("concurrency_targets", []):
        plan_name = target["plan"]
        op_id = target["operator"]
        plan = all_plans.get(plan_name)
        if plan:
            result = analyze_concurrency(plan, config, op_id)
            if result:
                output["concurrency_analysis"].setdefault(plan_name, {})[op_id] = result

    for comp in manifest.get("paired_comparisons", []):
        result = compare_plans(all_plans, comp)
        if result:
            output["comparative_analysis"][comp["name"]] = result

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/diagnostics.json", "w") as f:
        json.dump(output, f, indent=2)

    create_sqlite_db(output, all_plans)
    generate_graphviz(all_plans)

    print("Diagnostics written to /app/output/diagnostics.json")
    print("SQLite database written to /app/output/operators.db")
    print("Graphviz trees written to /app/output/trees/")


if __name__ == "__main__":
    main()
