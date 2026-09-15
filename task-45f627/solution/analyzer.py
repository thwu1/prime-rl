#!/usr/bin/env python3
"""Flink streaming topology analyzer - solution implementation.

"""

import json
import yaml
import math
import os
import sqlite3
from pathlib import Path
from collections import defaultdict


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_plans(plans_dir):
    plans = []
    for fp in sorted(Path(plans_dir).glob("*.json")):
        with open(fp) as f:
            plans.append(json.load(f))
    return plans


def build_node_index(plan):
    return {n["id"]: n for n in plan["nodes"]}


def effective_rate_and_size(nodes, node_id):
    node = nodes[node_id]
    ntype = node["type"]
    if ntype == "Source":
        return node["rate_per_second"], node["avg_row_size_bytes"]
    elif ntype == "Join":
        return node["estimated_output_rate"], node["estimated_output_row_size"]
    elif ntype in ("AsyncMLPredict", "Calc"):
        return effective_rate_and_size(nodes, node["inputs"][0])
    else:
        raise ValueError(f"Cannot resolve rate/size for node type {ntype}")


def join_side_state(nodes, join_node, ttl):
    left_id, right_id = join_node["inputs"][0], join_node["inputs"][1]
    lr, ls = effective_rate_and_size(nodes, left_id)
    rr, rs = effective_rate_and_size(nodes, right_id)
    left_bytes = int(lr * ttl * ls)
    right_bytes = int(rr * ttl * rs)
    return left_bytes, right_bytes


def per_join_state(plan):
    nodes = build_node_index(plan)
    ttl = plan["state_ttl_seconds"]
    result = []
    for nid in sorted(nodes):
        if nodes[nid]["type"] == "Join":
            lb, rb = join_side_state(nodes, nodes[nid], ttl)
            result.append((nid, nodes[nid]["name"], lb, rb, lb + rb))
    return result


def total_join_state(plan):
    return sum(t for _, _, _, _, t in per_join_state(plan))


ELIGIBLE_JOIN_TYPES = {"INNER", "LEFT"}


def join_key_columns(node):
    cols = set()
    for k in node["join_keys"]:
        cols.add(k["left"])
        cols.add(k["right"])
    return cols


def find_multi_join_opportunities(plan):
    nodes = build_node_index(plan)
    ttl = plan["state_ttl_seconds"]
    join_ids = {nid for nid in nodes if nodes[nid]["type"] == "Join"}

    children = defaultdict(list)
    parents = defaultdict(list)
    for jid in join_ids:
        for inp in nodes[jid]["inputs"]:
            if inp in join_ids:
                children[inp].append(jid)
                parents[jid].append(inp)

    roots = sorted(jid for jid in join_ids if not parents[jid])
    chains = []

    def dfs(nid, path):
        path.append(nid)
        jc = sorted(c for c in children.get(nid, []) if c in join_ids)
        if not jc:
            if len(path) >= 2:
                chains.append(list(path))
        else:
            for c in jc:
                dfs(c, path)
        path.pop()

    for r in roots:
        dfs(r, [])

    opportunities = []
    for chain in chains:
        for subchain in eligible_subchains(nodes, chain):
            opp = build_opportunity(nodes, ttl, subchain)
            if opp:
                opportunities.append(opp)

    return opportunities


def eligible_subchains(nodes, chain):
    n = len(chain)
    result = []
    i = 0
    while i < n:
        j = i + 1
        while j < n:
            segment = chain[i: j + 1]
            if not all(
                nodes[jid]["join_type"] in ELIGIBLE_JOIN_TYPES for jid in segment
            ):
                break
            key_sets = [join_key_columns(nodes[jid]) for jid in segment]
            common = key_sets[0]
            for ks in key_sets[1:]:
                common = common & ks
            if not common:
                break
            j += 1
        if j - i >= 2:
            result.append(chain[i:j])
            i = j
        else:
            i += 1
    return result


def build_opportunity(nodes, ttl, subchain):
    key_sets = [join_key_columns(nodes[jid]) for jid in subchain]
    common = key_sets[0]
    for ks in key_sets[1:]:
        common = common & ks
    if not common:
        return None
    common_key = sorted(common)[0]

    chain_set = set(subchain)
    sources = set()

    def collect(nid):
        node = nodes[nid]
        if node["type"] == "Source":
            sources.add(nid)
        elif nid in chain_set:
            for inp in node["inputs"]:
                collect(inp)
        else:
            sources.add(nid)

    for jid in subchain:
        for inp in nodes[jid]["inputs"]:
            collect(inp)

    source_ids = sorted(sources)

    cascaded = 0
    for jid in subchain:
        lb, rb = join_side_state(nodes, nodes[jid], ttl)
        cascaded += lb + rb

    multi = 0
    for sid in source_ids:
        rate, size = effective_rate_and_size(nodes, sid)
        multi += int(rate * ttl * size)

    savings = cascaded - multi
    pct = round(savings / cascaded * 100, 2)

    return {
        "join_ids": sorted(subchain),
        "common_key": common_key,
        "source_ids": source_ids,
        "cascaded_state_bytes": cascaded,
        "multi_join_state_bytes": multi,
        "savings_bytes": savings,
        "savings_percent": pct,
    }


def async_capacity(plan, safety_factor):
    configs = []
    for node in plan["nodes"]:
        if node["type"] != "AsyncMLPredict":
            continue
        qps = node["target_qps"]
        lat = node["p99_latency_seconds"]
        req_sz = node["avg_request_size_bytes"]
        max_ops = node["max_ops_per_subtask"]

        depth = math.ceil(qps * lat * safety_factor)
        par = math.ceil(depth / max_ops)

        configs.append({
            "node_id": node["id"],
            "name": node["name"],
            "required_queue_depth": depth,
            "min_parallelism": par,
            "memory_per_subtask_bytes": max_ops * req_sz,
            "total_async_memory_bytes": depth * req_sz,
        })
    return configs


def generate_dot(plan):
    nodes = build_node_index(plan)
    lines = [f'digraph {plan["plan_name"]} {{']
    lines.append('    rankdir=TB;')
    lines.append('    node [shape=box, style=filled, fontname="Helvetica"];')
    lines.append('')

    for nid in sorted(nodes):
        node = nodes[nid]
        ntype = node["type"]
        name = node["name"]

        if ntype == "Source":
            label = f'{name}\\nSource\\n{node["rate_per_second"]} rps'
            color = "#b3d9ff"
        elif ntype == "Join":
            keys = ", ".join(k["left"] for k in node["join_keys"])
            label = f'{name}\\n{node["join_type"]} Join\\n{keys}'
            color = "#ffffb3"
        elif ntype == "AsyncMLPredict":
            label = f'{name}\\nAsyncMLPredict\\n{node["target_qps"]} QPS'
            color = "#d9b3ff"
        elif ntype == "Sink":
            label = f'{name}\\nSink'
            color = "#ffb3b3"
        elif ntype == "Calc":
            label = f'{name}\\nCalc'
            color = "#b3ffb3"
        else:
            label = f'{name}\\n{ntype}'
            color = "#e0e0e0"

        lines.append(f'    {nid} [label="{label}", fillcolor="{color}"];')

    lines.append('')

    for nid in sorted(nodes):
        node = nodes[nid]
        for inp_id in node.get("inputs", []):
            lines.append(f'    {inp_id} -> {nid};')

    lines.append('}')
    return '\n'.join(lines)


def create_database(db_path, plans, report):
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE join_state (
        plan_name TEXT,
        node_id INTEGER,
        node_name TEXT,
        left_state_bytes INTEGER,
        right_state_bytes INTEGER,
        total_state_bytes INTEGER
    )''')

    c.execute('''CREATE TABLE multi_join_opportunities (
        plan_name TEXT,
        join_ids TEXT,
        common_key TEXT,
        source_ids TEXT,
        cascaded_state_bytes INTEGER,
        multi_join_state_bytes INTEGER,
        savings_bytes INTEGER,
        savings_percent REAL
    )''')

    c.execute('''CREATE TABLE async_ml_configs (
        plan_name TEXT,
        node_id INTEGER,
        node_name TEXT,
        required_queue_depth INTEGER,
        min_parallelism INTEGER,
        memory_per_subtask_bytes INTEGER,
        total_async_memory_bytes INTEGER
    )''')

    for plan in plans:
        plan_name = plan["plan_name"]

        for nid, name, left, right, total in per_join_state(plan):
            c.execute(
                "INSERT INTO join_state VALUES (?, ?, ?, ?, ?, ?)",
                (plan_name, nid, name, left, right, total)
            )

        plan_report = report["plans"][plan_name]
        for opp in plan_report["multi_join_opportunities"]:
            c.execute(
                "INSERT INTO multi_join_opportunities VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_name,
                    json.dumps(opp["join_ids"]),
                    opp["common_key"],
                    json.dumps(opp["source_ids"]),
                    opp["cascaded_state_bytes"],
                    opp["multi_join_state_bytes"],
                    opp["savings_bytes"],
                    opp["savings_percent"],
                )
            )

        for config in plan_report["async_ml_predict"]:
            c.execute(
                "INSERT INTO async_ml_configs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_name,
                    config["node_id"],
                    config["name"],
                    config["required_queue_depth"],
                    config["min_parallelism"],
                    config["memory_per_subtask_bytes"],
                    config["total_async_memory_bytes"],
                )
            )

    conn.commit()
    conn.close()


def generate_report(config):
    plans = load_plans(config["plans_dir"])
    sf = config["safety_factor"]
    report = {"plans": {}}
    for plan in plans:
        name = plan["plan_name"]
        report["plans"][name] = {
            "total_join_state_bytes": total_join_state(plan),
            "multi_join_opportunities": find_multi_join_opportunities(plan),
            "async_ml_predict": async_capacity(plan, sf),
        }
    return report, plans


def main():
    config = load_config("/app/config.yaml")
    report, plans = generate_report(config)

    out_dir = Path(config["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {out_dir / 'report.json'}")

    for plan in plans:
        dot_content = generate_dot(plan)
        dot_path = out_dir / f'{plan["plan_name"]}.dot'
        with open(dot_path, "w") as f:
            f.write(dot_content)
        print(f"DOT written to {dot_path}")

    db_path = str(out_dir / "analysis.db")
    create_database(db_path, plans, report)
    print(f"Database written to {db_path}")


if __name__ == "__main__":
    main()
