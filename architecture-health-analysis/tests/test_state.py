
import json
import gzip
import csv
import os
import re
import sqlite3
import pytest


# ── Database helpers ──────────────────────────────────────────────────

DB_PATH = "/app/architecture/governance.db"


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


# ── Data parsing helpers ─────────────────────────────────────────────

def parse_dot_edges(path, valid_components):
    """Parse directed edges from DOT file, handling chains and filtering legend."""
    with open(path) as f:
        content = f.read()
    # Remove block comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Remove line comments
    content = re.sub(r'//[^\n]*', '', content)

    edges = set()
    for line in content.split('\n'):
        if '->' not in line:
            continue
        # Remove attribute blocks [...]
        clean = re.sub(r'\[[^\]]*\]', '', line)
        # Split by -> to handle chains (A -> B -> C)
        parts = re.split(r'\s*->\s*', clean)
        nodes = []
        for part in parts:
            m = re.search(r'"([^"]+)"', part)
            if m:
                nodes.append(m.group(1))
        # Create edges between consecutive valid components
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

    # Gateway: gzipped JSONL
    with gzip.open("/app/architecture/traces/gateway.jsonl.gz", "rt") as f:
        for line in f:
            rec = json.loads(line)
            edge_set.add((rec["caller"], rec["callee"]))

    # Monitoring: gzipped CSV
    with gzip.open("/app/architecture/traces/monitoring.csv.gz", "rt") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edge_set.add((row["source"], row["destination"]))

    return sorted([list(e) for e in edge_set])


# ── Expected computation ─────────────────────────────────────────────

def compute_conformance(intended, static, runtime, classification_rules):
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
        i = ce_v / (ca_v + ce_v) if (ca_v + ce_v) > 0 else 0.0
        d = abs(a + i - 1)
        metrics[name] = {"Ca": ca_v, "Ce": ce_v, "I": i, "A": a, "D": d}
    return metrics


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


def solve_mckp(conformance, components, violation_config, global_config):
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
        "total_reduction": total_reduction,
    }


# ── Test class ────────────────────────────────────────────────────────

class TestArchitectureDriftForensics:
    @classmethod
    def setup_class(cls):
        cls.components = db_load_components()
        cls.classification_rules = db_load_classification_rules()
        cls.violation_config = db_load_violation_config()
        cls.global_config = db_load_config()

        cls.intended = parse_dot_edges(
            "/app/architecture/intended.dot", cls.components)
        cls.static = parse_import_edges("/app/architecture/source_deps")
        cls.runtime = parse_trace_edges()

        cls.conformance = compute_conformance(
            cls.intended, cls.static, cls.runtime, cls.classification_rules)
        cls.metrics = compute_metrics(cls.components, cls.static)
        cls.sccs = find_sccs(cls.components, cls.static)
        cls.erosion = compute_erosion(
            cls.conformance, cls.components, cls.violation_config)
        cls.plan = solve_mckp(
            cls.conformance, cls.components, cls.violation_config,
            cls.global_config)

    # ── File existence ──────────────────────────────────────────────

    def test_dependency_graphs_exists(self):
        assert os.path.isfile("/app/results/dependency_graphs.json")

    def test_conformance_exists(self):
        assert os.path.isfile("/app/results/conformance.json")

    def test_metrics_exists(self):
        assert os.path.isfile("/app/results/metrics.json")

    def test_cycles_exists(self):
        assert os.path.isfile("/app/results/cycles.json")

    def test_erosion_exists(self):
        assert os.path.isfile("/app/results/erosion_scores.json")

    def test_remediation_exists(self):
        assert os.path.isfile("/app/results/remediation_plan.json")

    # ── Dependency graphs ───────────────────────────────────────────

    def test_intended_graph(self):
        with open("/app/results/dependency_graphs.json") as f:
            graphs = json.load(f)
        agent = sorted([sorted(e) if isinstance(e, list) else e
                        for e in graphs["intended"]])
        expected = sorted([sorted(e) for e in self.intended])
        assert agent == expected, (
            f"Intended graph mismatch: {len(expected)} expected, "
            f"{len(agent)} found"
        )

    def test_static_graph(self):
        with open("/app/results/dependency_graphs.json") as f:
            graphs = json.load(f)
        agent = sorted([sorted(e) if isinstance(e, list) else e
                        for e in graphs["static"]])
        expected = sorted([sorted(e) for e in self.static])
        assert agent == expected, (
            f"Static graph mismatch: {len(expected)} expected, "
            f"{len(agent)} found"
        )

    def test_runtime_graph(self):
        with open("/app/results/dependency_graphs.json") as f:
            graphs = json.load(f)
        agent = sorted([sorted(e) if isinstance(e, list) else e
                        for e in graphs["runtime"]])
        expected = sorted([sorted(e) for e in self.runtime])
        assert agent == expected, (
            f"Runtime graph mismatch: {len(expected)} expected, "
            f"{len(agent)} found"
        )

    # ── Conformance ─────────────────────────────────────────────────

    def test_conformance_count(self):
        with open("/app/results/conformance.json") as f:
            agent = json.load(f)
        assert len(agent) == len(self.conformance), (
            f"Expected {len(self.conformance)} edges, got {len(agent)}"
        )

    def test_conformance_classifications(self):
        with open("/app/results/conformance.json") as f:
            agent = json.load(f)
        agent_map = {(e["source"], e["target"]): e for e in agent}
        for exp in self.conformance:
            key = (exp["source"], exp["target"])
            assert key in agent_map, f"Missing edge {key}"
            a = agent_map[key]
            assert a["classification"] == exp["classification"], (
                f"Edge {key}: expected '{exp['classification']}', "
                f"got '{a['classification']}'"
            )

    def test_conformance_flags(self):
        with open("/app/results/conformance.json") as f:
            agent = json.load(f)
        agent_map = {(e["source"], e["target"]): e for e in agent}
        for exp in self.conformance:
            key = (exp["source"], exp["target"])
            a = agent_map[key]
            assert a["in_intended"] == exp["in_intended"], (
                f"Edge {key}: in_intended expected {exp['in_intended']}"
            )
            assert a["in_static"] == exp["in_static"], (
                f"Edge {key}: in_static expected {exp['in_static']}"
            )
            assert a["in_runtime"] == exp["in_runtime"], (
                f"Edge {key}: in_runtime expected {exp['in_runtime']}"
            )

    # ── Metrics ─────────────────────────────────────────────────────

    def test_metrics_completeness(self):
        with open("/app/results/metrics.json") as f:
            agent = json.load(f)
        expected_names = set(self.metrics.keys())
        agent_names = set(agent.keys())
        assert expected_names == agent_names, (
            f"Missing: {expected_names - agent_names}, "
            f"Extra: {agent_names - expected_names}"
        )

    def test_metrics_coupling(self):
        with open("/app/results/metrics.json") as f:
            agent = json.load(f)
        for name, exp in self.metrics.items():
            a = agent[name]
            assert a["Ca"] == exp["Ca"], (
                f"{name}: Ca expected {exp['Ca']}, got {a['Ca']}"
            )
            assert a["Ce"] == exp["Ce"], (
                f"{name}: Ce expected {exp['Ce']}, got {a['Ce']}"
            )

    def test_metrics_instability(self):
        with open("/app/results/metrics.json") as f:
            agent = json.load(f)
        for name, exp in self.metrics.items():
            assert abs(agent[name]["I"] - exp["I"]) < 1e-4, (
                f"{name}: I expected {exp['I']:.6f}, got {agent[name]['I']}"
            )

    def test_metrics_abstractness(self):
        with open("/app/results/metrics.json") as f:
            agent = json.load(f)
        for name, exp in self.metrics.items():
            assert abs(agent[name]["A"] - exp["A"]) < 1e-4, (
                f"{name}: A expected {exp['A']:.6f}, got {agent[name]['A']}"
            )

    def test_metrics_distance(self):
        with open("/app/results/metrics.json") as f:
            agent = json.load(f)
        for name, exp in self.metrics.items():
            assert abs(agent[name]["D"] - exp["D"]) < 1e-4, (
                f"{name}: D expected {exp['D']:.6f}, got {agent[name]['D']}"
            )

    # ── Cycles ──────────────────────────────────────────────────────

    def test_cycles_count(self):
        with open("/app/results/cycles.json") as f:
            agent = json.load(f)
        assert len(agent) == len(self.sccs), (
            f"Expected {len(self.sccs)} SCCs, got {len(agent)}"
        )

    def test_cycles_content(self):
        with open("/app/results/cycles.json") as f:
            agent = json.load(f)
        agent_sorted = sorted(
            [sorted(scc) for scc in agent],
            key=lambda x: (-len(x), x[0]),
        )
        expected_sorted = sorted(
            [sorted(scc) for scc in self.sccs],
            key=lambda x: (-len(x), x[0]),
        )
        assert agent_sorted == expected_sorted, (
            f"SCCs mismatch.\nExpected: {expected_sorted}\n"
            f"Got: {agent_sorted}"
        )

    # ── Erosion scores ──────────────────────────────────────────────

    def test_erosion_components(self):
        with open("/app/results/erosion_scores.json") as f:
            agent = json.load(f)
        expected_keys = set(self.erosion.keys())
        agent_keys = set(agent.keys())
        assert expected_keys == agent_keys, (
            f"Erosion components mismatch.\n"
            f"Missing: {expected_keys - agent_keys}\n"
            f"Extra: {agent_keys - expected_keys}"
        )

    def test_erosion_values(self):
        with open("/app/results/erosion_scores.json") as f:
            agent = json.load(f)
        for name, exp_val in self.erosion.items():
            assert abs(agent[name] - exp_val) < 1e-4, (
                f"{name}: erosion expected {exp_val}, got {agent[name]}"
            )

    # ── Remediation plan ────────────────────────────────────────────

    def test_remediation_budget(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        budget = int(self.global_config["remediation_budget"])
        assert plan["total_cost"] <= budget, (
            f"Plan exceeds budget: {plan['total_cost']} > {budget}"
        )

    def test_remediation_valid_edges(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        violation_edges = {
            (e["source"], e["target"])
            for e in self.conformance
            if e["classification"] in self.violation_config
        }
        for action in plan["actions"]:
            edge = tuple(action["edge"])
            assert edge in violation_edges, (
                f"Invalid violation edge: {edge}"
            )

    def test_remediation_no_duplicates(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        edges = [tuple(a["edge"]) for a in plan["actions"]]
        assert len(edges) == len(set(edges)), "Duplicate edges in plan"

    def test_remediation_cost_consistent(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        computed_cost = sum(a["cost"] for a in plan["actions"])
        assert plan["total_cost"] == computed_cost, (
            f"Stated cost {plan['total_cost']} != computed {computed_cost}"
        )

    def test_remediation_reduction_consistent(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        computed_red = sum(a["reduction"] for a in plan["actions"])
        assert abs(plan["total_reduction"] - computed_red) < 1e-4, (
            f"Stated reduction {plan['total_reduction']:.6f} != "
            f"computed {computed_red:.6f}"
        )

    def test_remediation_optimal(self):
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        assert abs(
            plan["total_reduction"] - self.plan["total_reduction"]
        ) < 1e-2, (
            f"Suboptimal plan: expected reduction "
            f"{self.plan['total_reduction']:.4f}, "
            f"got {plan['total_reduction']:.4f}"
        )

    def test_remediation_action_types(self):
        """Verify action names match violation classification."""
        with open("/app/results/remediation_plan.json") as f:
            plan = json.load(f)
        conf_map = {
            (e["source"], e["target"]): e["classification"]
            for e in self.conformance
            if e["classification"] in self.violation_config
        }
        alt_action = self.global_config["alternate_action"]
        for action in plan["actions"]:
            edge = tuple(action["edge"])
            cls = conf_map[edge]
            vc = self.violation_config[cls]
            valid_actions = {vc["primary_action"], alt_action}
            assert action["action"] in valid_actions, (
                f"Edge {edge} ({cls}): invalid action "
                f"'{action['action']}', expected one of {valid_actions}"
            )
