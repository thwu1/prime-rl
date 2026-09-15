#!/usr/bin/env python3

"""Solve the BigSpender architecture drift forensics task."""

import json
import gzip
import csv
import os
import re
import sqlite3


DB_PATH = "/app/architecture/governance.db"


# ── Database Access ──────────────────────────────────────────────────

def db_load_components():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, layer, abstract_types, concrete_types, business_criticality FROM components")
    components = {}
    for row in c.fetchall():
        components[row[0]] = {
            "layer": row[1],
            "abstract_types": row[2],
            "concrete_types": row[3],
            "business_criticality": row[4],
        }
    conn.close()
    return components


def db_load_classification_rules():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT in_intended, in_static, in_runtime, classification FROM classification_rules")
    rules = {}
    for row in c.fetchall():
        rules[(row[0], row[1], row[2])] = row[3]
    conn.close()
    return rules


def db_load_violation_config():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT classification, erosion_weight, primary_action, primary_action_cost FROM violation_config")
    config = {}
    for row in c.fetchall():
        config[row[0]] = {
            "erosion_weight": row[1],
            "primary_action": row[2],
            "primary_action_cost": row[3],
        }
    conn.close()
    return config


def db_load_config():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM config")
    config = dict(c.fetchall())
    conn.close()
    return config


# ── Data Parsing ─────────────────────────────────────────────────────

def parse_dot_edges(path, valid_components):
    """Extract directed edges from DOT file, handling chains and filtering legend."""
    with open(path) as f:
        content = f.read()
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//[^\n]*', '', content)

    edges = set()
    for line in content.split('\n'):
        if '->' not in line:
            continue
        clean = re.sub(r'\[[^\]]*\]', '', line)
        parts = re.split(r'\s*->\s*', clean)
        nodes = []
        for part in parts:
            m = re.search(r'"([^"]+)"', part)
            if m:
                nodes.append(m.group(1))
        for i in range(len(nodes) - 1):
            src, tgt = nodes[i], nodes[i + 1]
            if src in valid_components and tgt in valid_components:
                edges.add((src, tgt))

    return sorted([list(e) for e in edges])


def parse_import_edges(directory):
    edges = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".imports"):
            continue
        component = filename[:-8]
        with open(os.path.join(directory, filename)) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    edges.append([component, line])
    return sorted(edges)


def parse_trace_edges():
    """Parse runtime edges from both gateway (JSONL) and monitoring (CSV) traces."""
    edge_set = set()

    with gzip.open("/app/architecture/traces/gateway.jsonl.gz", "rt") as f:
        for line in f:
            rec = json.loads(line)
            edge_set.add((rec["caller"], rec["callee"]))

    with gzip.open("/app/architecture/traces/monitoring.csv.gz", "rt") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edge_set.add((row["source"], row["destination"]))

    return sorted([list(e) for e in edge_set])


# ── Conformance Analysis ─────────────────────────────────────────────

def classify_conformance(intended, static, runtime, classification_rules):
    i_set = {tuple(e) for e in intended}
    s_set = {tuple(e) for e in static}
    r_set = {tuple(e) for e in runtime}
    all_edges = sorted(i_set | s_set | r_set)

    results = []
    for edge in all_edges:
        in_i = edge in i_set
        in_s = edge in s_set
        in_r = edge in r_set

        key = (int(in_i), int(in_s), int(in_r))
        cls = classification_rules.get(key, "unknown")

        results.append({
            "source": edge[0],
            "target": edge[1],
            "in_intended": in_i,
            "in_static": in_s,
            "in_runtime": in_r,
            "classification": cls,
        })
    return results


# ── Quality Metrics ──────────────────────────────────────────────────

def compute_metrics(components, static_edges):
    ca = {name: 0 for name in components}
    ce = {name: 0 for name in components}
    for src, tgt in static_edges:
        if src in components and tgt in components:
            ce[src] += 1
            ca[tgt] += 1

    metrics = {}
    for name, meta in components.items():
        total = meta["abstract_types"] + meta["concrete_types"]
        a = meta["abstract_types"] / total if total > 0 else 0.0
        ca_v = ca[name]
        ce_v = ce[name]
        i_val = ce_v / (ca_v + ce_v) if (ca_v + ce_v) > 0 else 0.0
        d = abs(a + i_val - 1)
        metrics[name] = {
            "Ca": ca_v,
            "Ce": ce_v,
            "I": round(i_val, 6),
            "A": round(a, 6),
            "D": round(d, 6),
        }
    return metrics


# ── Cycle Detection ──────────────────────────────────────────────────

def find_sccs(components, static_edges):
    comp_names = sorted(components.keys())
    adj = {n: [] for n in comp_names}
    for src, tgt in static_edges:
        if src in adj and tgt in adj:
            adj[src].append(tgt)

    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj[v]:
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in comp_names:
        if v not in index:
            strongconnect(v)

    return sorted(sccs, key=lambda x: (-len(x), x[0]))


# ── Erosion Scores ───────────────────────────────────────────────────

def compute_erosion(conformance, components, violation_config):
    scores = {}
    for entry in conformance:
        cls = entry["classification"]
        if cls not in violation_config:
            continue
        w = violation_config[cls]["erosion_weight"]
        src = entry["source"]
        tgt = entry["target"]
        crit = max(components[src]["business_criticality"],
                   components[tgt]["business_criticality"])
        erosion_val = w * crit
        scores[src] = scores.get(src, 0.0) + erosion_val
        scores[tgt] = scores.get(tgt, 0.0) + erosion_val
    return scores


# ── Remediation Optimization ─────────────────────────────────────────

def solve_remediation(conformance, components, violation_config, global_config):
    budget = int(global_config["remediation_budget"])
    alt_action = global_config["alternate_action"]
    alt_cost = int(global_config["alternate_action_cost"])
    alt_factor = float(global_config["alternate_reduction_factor"])

    groups = []
    for entry in conformance:
        cls = entry["classification"]
        if cls not in violation_config:
            continue
        vc = violation_config[cls]
        src = entry["source"]
        tgt = entry["target"]
        crit = max(components[src]["business_criticality"],
                   components[tgt]["business_criticality"])
        erosion_val = vc["erosion_weight"] * crit

        groups.append({
            "edge": [src, tgt],
            "options": [
                {"action": vc["primary_action"], "cost": vc["primary_action_cost"],
                 "reduction": erosion_val},
                {"action": alt_action, "cost": alt_cost,
                 "reduction": erosion_val * alt_factor},
            ]
        })

    n = len(groups)
    scale = 100000

    dp = [0] * (budget + 1)
    choice = [[-1] * (budget + 1) for _ in range(n)]

    for i in range(n):
        new_dp = dp[:]
        new_choice = [-1] * (budget + 1)
        for j, opt in enumerate(groups[i]["options"]):
            c = opt["cost"]
            v = int(round(opt["reduction"] * scale))
            for w in range(c, budget + 1):
                candidate = dp[w - c] + v
                if candidate > new_dp[w]:
                    new_dp[w] = candidate
                    new_choice[w] = j
        dp = new_dp
        choice[i] = new_choice

    actions = []
    w = budget
    total_cost = 0
    total_reduction = 0.0
    for i in range(n - 1, -1, -1):
        j = choice[i][w]
        if j >= 0:
            opt = groups[i]["options"][j]
            actions.append({
                "edge": groups[i]["edge"],
                "action": opt["action"],
                "cost": opt["cost"],
                "reduction": opt["reduction"],
            })
            w -= opt["cost"]
            total_cost += opt["cost"]
            total_reduction += opt["reduction"]

    actions.sort(key=lambda a: (a["edge"][0], a["edge"][1]))
    return {
        "actions": actions,
        "total_cost": total_cost,
        "total_reduction": round(total_reduction, 6),
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Load governance rules from database
    components = db_load_components()
    classification_rules = db_load_classification_rules()
    violation_config = db_load_violation_config()
    global_config = db_load_config()

    # Parse data sources
    intended = parse_dot_edges("/app/architecture/intended.dot", components)
    static = parse_import_edges("/app/architecture/source_deps")
    runtime = parse_trace_edges()

    # Conformance analysis
    conformance = classify_conformance(
        intended, static, runtime, classification_rules)

    # Quality metrics on static graph
    metrics = compute_metrics(components, static)

    # Cycle detection in static graph
    cycles = find_sccs(components, static)

    # Erosion scores
    erosion = compute_erosion(conformance, components, violation_config)

    # Remediation plan
    plan = solve_remediation(
        conformance, components, violation_config, global_config)

    # Write outputs
    os.makedirs("/app/results", exist_ok=True)

    with open("/app/results/dependency_graphs.json", "w") as f:
        json.dump({"intended": intended, "static": static, "runtime": runtime},
                  f, indent=2)

    with open("/app/results/conformance.json", "w") as f:
        json.dump(conformance, f, indent=2)

    with open("/app/results/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    with open("/app/results/cycles.json", "w") as f:
        json.dump(cycles, f, indent=2)

    with open("/app/results/erosion_scores.json", "w") as f:
        json.dump(erosion, f, indent=2)

    with open("/app/results/remediation_plan.json", "w") as f:
        json.dump(plan, f, indent=2)

    budget = int(global_config["remediation_budget"])
    print("Architecture drift forensics complete.")
    print(f"  Intended edges: {len(intended)}")
    print(f"  Static edges: {len(static)}")
    print(f"  Runtime edges: {len(runtime)}")
    print(f"  Unique edges classified: {len(conformance)}")
    print(f"  SCCs found: {len(cycles)}")
    print(f"  Components with erosion: {len(erosion)}")
    print(f"  Remediation cost: {plan['total_cost']}/{budget}")
    print(f"  Erosion reduction: {plan['total_reduction']:.2f}")


if __name__ == "__main__":
    main()
