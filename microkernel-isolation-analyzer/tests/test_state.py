"""
Test suite for Microkernel System Isolation Analyzer.
Includes a reference implementation to verify correctness.
All tests are invariant-based (no hardcoded PD names or constraint indices)
to work with any randomly-generated system configuration.

"""

import json
import os
import pytest
from collections import defaultdict, deque


# ============================================================
# Reference implementation
# ============================================================

def load_system():
    with open("/app/system.json") as f:
        return json.load(f)


def ref_compute_info_flow(system):
    """Reference: compute direct information flow graph."""
    resource_writers = defaultdict(set)
    resource_readers = defaultdict(set)

    for ar in system["access_rights"]:
        pd = ar["pd_id"]
        res = ar["resource_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            resource_writers[res].add(pd)
        if perm in ("read", "readwrite"):
            resource_readers[res].add(pd)

    edges = defaultdict(lambda: defaultdict(list))
    all_resources = set(resource_writers.keys()) | set(resource_readers.keys())
    for res_id in all_resources:
        for writer in resource_writers[res_id]:
            for reader in resource_readers[res_id]:
                if writer != reader:
                    edges[writer][reader].append(res_id)

    result = {}
    for src in sorted(edges.keys()):
        result[src] = {}
        for dst in sorted(edges[src].keys()):
            result[src][dst] = sorted(edges[src][dst])
    return result


def ref_get_adj(info_flow):
    adj = defaultdict(set)
    for src, targets in info_flow.items():
        for dst in targets:
            adj[src].add(dst)
    return adj


def ref_reachability(adj, pds):
    reachable = {}
    for pd in pds:
        visited = {pd}
        queue = deque([pd])
        while queue:
            node = queue.popleft()
            for nb in adj.get(node, set()):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        reachable[pd] = visited
    return reachable


def ref_tcb(reachable, pds):
    return {pd: sorted([o for o in pds if pd in reachable[o]]) for pd in pds}


def ref_impact(reachable, pds):
    return {pd: sorted(list(reachable[pd])) for pd in pds}


def ref_bfs(adj, src, tgt):
    if src == tgt:
        return [src]
    visited = {src}
    queue = deque([(src, [src])])
    while queue:
        node, path = queue.popleft()
        for nb in sorted(adj.get(node, set())):
            if nb not in visited:
                np_ = path + [nb]
                if nb == tgt:
                    return np_
                visited.add(nb)
                queue.append((nb, np_))
    return None


def ref_min_cut(system, source_pd, sink_pd, adj):
    """Reference min resource cut via max-flow."""
    path = ref_bfs(adj, source_pd, sink_pd)
    if path is None:
        return 0, []

    INF = 10000
    cap = defaultdict(lambda: defaultdict(int))
    all_resources = set()
    for ar in system["access_rights"]:
        all_resources.add(ar["resource_id"])

    for res in all_resources:
        cap[f"{res}_in"][f"{res}_out"] += 1

    for ar in system["access_rights"]:
        pd = ar["pd_id"]
        res = ar["resource_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            cap[pd][f"{res}_in"] += INF
        if perm in ("read", "readwrite"):
            cap[f"{res}_out"][pd] += INF

    flow = defaultdict(lambda: defaultdict(int))

    # Edmonds-Karp
    total = 0
    while True:
        visited = {source_pd}
        q = deque([(source_pd, [source_pd], float("inf"))])
        found_path = None
        found_bn = 0
        while q:
            nd, p, bn = q.popleft()
            all_neighbors = set(cap[nd].keys())
            for other in list(flow.keys()):
                if flow[other][nd] > 0:
                    all_neighbors.add(other)
            for nb in sorted(all_neighbors):
                if nb in visited:
                    continue
                res_ = cap[nd][nb] - flow[nd][nb]
                if res_ > 0:
                    nbn = min(bn, res_)
                    np_ = p + [nb]
                    if nb == sink_pd:
                        found_path = np_
                        found_bn = nbn
                        break
                    visited.add(nb)
                    q.append((nb, np_, nbn))
            if found_path:
                break

        if found_path is None:
            break
        total += found_bn
        for i in range(len(found_path) - 1):
            u, v = found_path[i], found_path[i + 1]
            flow[u][v] += found_bn
            flow[v][u] -= found_bn

    reachable = {source_pd}
    q = deque([source_pd])
    while q:
        nd = q.popleft()
        all_neighbors = set(cap[nd].keys())
        for other in list(flow.keys()):
            if flow[other][nd] > 0:
                all_neighbors.add(other)
        for nb in all_neighbors:
            res_ = cap[nd][nb] - flow[nd][nb]
            if nb not in reachable and res_ > 0:
                reachable.add(nb)
                q.append(nb)

    cut_res = []
    for res in sorted(all_resources):
        if f"{res}_in" in reachable and f"{res}_out" not in reachable:
            cut_res.append(res)

    return total, sorted(cut_res)


# ============================================================
# Test fixtures
# ============================================================

@pytest.fixture(scope="module")
def system():
    return load_system()


@pytest.fixture(scope="module")
def dna_token(system):
    return system["dna_token"]


@pytest.fixture(scope="module")
def pds(system):
    return [pd["id"] for pd in system["protection_domains"]]


@pytest.fixture(scope="module")
def ref_info(system):
    return ref_compute_info_flow(system)


@pytest.fixture(scope="module")
def ref_adj(ref_info):
    return ref_get_adj(ref_info)


@pytest.fixture(scope="module")
def ref_reach(ref_adj, pds):
    return ref_reachability(ref_adj, pds)


@pytest.fixture(scope="module")
def ref_tcb_data(ref_reach, pds):
    return ref_tcb(ref_reach, pds)


@pytest.fixture(scope="module")
def ref_impact_data(ref_reach, pds):
    return ref_impact(ref_reach, pds)


# ============================================================
# Load agent outputs
# ============================================================

def load_json(name):
    path = f"/app/results/{name}"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


def load_output_data(name):
    """Load output file and return the 'data' sub-key."""
    obj = load_json(name)
    assert "data" in obj, f"{name} missing 'data' key"
    return obj["data"]


# ============================================================
# Tests: DNA / Instance Token integrity
# ============================================================

class TestDNA:
    def test_dna_file_exists(self):
        assert os.path.exists("/app/.dna"), "DNA file /app/.dna missing"

    def test_system_has_dna_token(self, system):
        assert "dna_token" in system, "system.json missing dna_token field"
        assert len(system["dna_token"]) > 0, "dna_token is empty"

    def test_dna_consistency(self, system):
        with open("/app/.dna") as f:
            dna = f.read().strip()
        assert system["dna_token"] == dna, \
            f"DNA mismatch: .dna={dna} system={system['dna_token']}"

    def test_info_flow_has_instance_token(self, dna_token):
        obj = load_json("info_flow.json")
        assert "_instance_token" in obj, "info_flow.json missing _instance_token"
        assert obj["_instance_token"] == dna_token, \
            f"info_flow.json _instance_token mismatch: got {obj['_instance_token']}"

    def test_tcb_has_instance_token(self, dna_token):
        obj = load_json("tcb.json")
        assert "_instance_token" in obj, "tcb.json missing _instance_token"
        assert obj["_instance_token"] == dna_token, \
            f"tcb.json _instance_token mismatch: got {obj['_instance_token']}"

    def test_impact_has_instance_token(self, dna_token):
        obj = load_json("impact.json")
        assert "_instance_token" in obj, "impact.json missing _instance_token"
        assert obj["_instance_token"] == dna_token, \
            f"impact.json _instance_token mismatch: got {obj['_instance_token']}"

    def test_violations_has_instance_token(self, dna_token):
        obj = load_json("violations.json")
        assert "_instance_token" in obj, "violations.json missing _instance_token"
        assert obj["_instance_token"] == dna_token, \
            f"violations.json _instance_token mismatch: got {obj['_instance_token']}"

    def test_min_cuts_has_instance_token(self, dna_token):
        obj = load_json("min_cuts.json")
        assert "_instance_token" in obj, "min_cuts.json missing _instance_token"
        assert obj["_instance_token"] == dna_token, \
            f"min_cuts.json _instance_token mismatch: got {obj['_instance_token']}"

    def test_dna_token_is_nontrivial(self, dna_token):
        """Ensure the DNA token is a real random hex, not a short stub."""
        assert len(dna_token) >= 16, \
            f"DNA token too short ({len(dna_token)} chars) — should be random hex"

    def test_system_has_enough_pds(self, system):
        """Verify the generated instance has sufficient complexity."""
        assert len(system["protection_domains"]) >= 19, \
            f"Too few PDs: {len(system['protection_domains'])}"

    def test_system_has_enough_constraints(self, system):
        assert len(system["isolation_constraints"]) >= 8, \
            f"Too few constraints: {len(system['isolation_constraints'])}"


# ============================================================
# Tests: info_flow.json
# ============================================================

class TestInfoFlow:
    def test_output_exists(self):
        assert os.path.exists("/app/results/info_flow.json")

    def test_edges_match_reference(self, ref_info):
        agent = load_output_data("info_flow.json")
        assert set(agent.keys()) == set(ref_info.keys()), \
            f"Source PD mismatch: agent={sorted(agent.keys())} ref={sorted(ref_info.keys())}"

        for src in ref_info:
            assert src in agent, f"Missing source PD: {src}"
            assert set(agent[src].keys()) == set(ref_info[src].keys()), \
                f"Target PD mismatch for {src}: agent={sorted(agent[src].keys())} ref={sorted(ref_info[src].keys())}"
            for dst in ref_info[src]:
                assert sorted(agent[src][dst]) == ref_info[src][dst], \
                    f"Resource mismatch for {src}->{dst}: agent={agent[src][dst]} ref={ref_info[src][dst]}"

    def test_edge_count(self, ref_info):
        agent = load_output_data("info_flow.json")
        ref_count = sum(len(targets) for targets in ref_info.values())
        agent_count = sum(len(targets) for targets in agent.values())
        assert agent_count == ref_count, f"Edge count: agent={agent_count} ref={ref_count}"


# ============================================================
# Tests: tcb.json
# ============================================================

class TestTCB:
    def test_output_exists(self):
        assert os.path.exists("/app/results/tcb.json")

    def test_all_pds_present(self, pds):
        agent = load_output_data("tcb.json")
        for pd in pds:
            assert pd in agent, f"Missing PD in TCB: {pd}"

    def test_self_in_tcb(self, pds):
        agent = load_output_data("tcb.json")
        for pd in pds:
            assert pd in agent[pd], f"{pd} should be in its own TCB"

    def test_tcb_matches_reference(self, ref_tcb_data, pds):
        agent = load_output_data("tcb.json")
        for pd in pds:
            assert sorted(agent[pd]) == ref_tcb_data[pd], \
                f"TCB mismatch for {pd}: agent={sorted(agent[pd])} ref={ref_tcb_data[pd]}"

    def test_singleton_tcb_exists(self, ref_tcb_data, pds):
        """At least one PD should have a singleton TCB (unreachable from others)."""
        singletons = [pd for pd in pds if ref_tcb_data[pd] == [pd]]
        agent = load_output_data("tcb.json")
        for pd in singletons:
            assert agent[pd] == [pd], \
                f"{pd} should have singleton TCB, got {agent[pd]}"


# ============================================================
# Tests: impact.json
# ============================================================

class TestImpact:
    def test_output_exists(self):
        assert os.path.exists("/app/results/impact.json")

    def test_all_pds_present(self, pds):
        agent = load_output_data("impact.json")
        for pd in pds:
            assert pd in agent, f"Missing PD in impact: {pd}"

    def test_self_in_impact(self, pds):
        agent = load_output_data("impact.json")
        for pd in pds:
            assert pd in agent[pd], f"{pd} should be in its own impact boundary"

    def test_impact_matches_reference(self, ref_impact_data, pds):
        agent = load_output_data("impact.json")
        for pd in pds:
            assert sorted(agent[pd]) == ref_impact_data[pd], \
                f"Impact mismatch for {pd}: agent has {len(agent[pd])} ref has {len(ref_impact_data[pd])}"

    def test_sink_pd_exists(self, ref_impact_data, pds):
        """At least one PD should only impact itself (sink node)."""
        sinks = [pd for pd in pds if ref_impact_data[pd] == [pd]]
        agent = load_output_data("impact.json")
        for pd in sinks:
            assert agent[pd] == [pd], \
                f"{pd} should only impact itself, got {agent[pd]}"

    def test_tcb_impact_consistency(self, pds):
        """pd_b in TCB(pd_a) iff pd_a in Impact(pd_b)."""
        tcb = load_output_data("tcb.json")
        impact = load_output_data("impact.json")
        for a in pds:
            for b in pds:
                in_tcb = b in tcb[a]
                in_impact = a in impact[b]
                assert in_tcb == in_impact, \
                    f"Inconsistency: {b} in TCB({a})={in_tcb} but {a} in Impact({b})={in_impact}"


# ============================================================
# Tests: violations.json
# ============================================================

class TestViolations:
    def test_output_exists(self):
        assert os.path.exists("/app/results/violations.json")

    def test_correct_count(self, system):
        agent = load_output_data("violations.json")
        assert len(agent) == len(system["isolation_constraints"]), \
            f"Expected {len(system['isolation_constraints'])} violations entries, got {len(agent)}"

    def test_constraint_order(self, system):
        agent = load_output_data("violations.json")
        for i, c in enumerate(system["isolation_constraints"]):
            assert agent[i]["pd_a"] == c["pd_a"], f"Constraint {i} pd_a mismatch"
            assert agent[i]["pd_b"] == c["pd_b"], f"Constraint {i} pd_b mismatch"

    def test_violated_flags(self, system, ref_adj, ref_reach):
        agent = load_output_data("violations.json")
        for i, c in enumerate(system["isolation_constraints"]):
            a, b = c["pd_a"], c["pd_b"]
            expected = b in ref_reach.get(a, set()) or a in ref_reach.get(b, set())
            assert agent[i]["violated"] == expected, \
                f"Constraint {i} ({a},{b}): expected violated={expected}, got {agent[i]['violated']}"

    def test_has_both_violated_and_non_violated(self, system, ref_reach):
        """System should have both violated and non-violated constraints."""
        agent = load_output_data("violations.json")
        violated = [v for v in agent if v["violated"]]
        non_violated = [v for v in agent if not v["violated"]]
        assert len(violated) >= 1, "Expected at least one violated constraint"
        assert len(non_violated) >= 1, "Expected at least one non-violated constraint"

    def test_forward_path_lengths(self, system, ref_adj):
        agent = load_output_data("violations.json")
        for i, v in enumerate(agent):
            if v["forward_path"] is not None:
                ref_path = ref_bfs(ref_adj, v["pd_a"], v["pd_b"])
                assert ref_path is not None
                ref_len = len(ref_path) - 1
                assert v["forward_length"] == ref_len, \
                    f"Constraint {i} forward length: agent={v['forward_length']} ref={ref_len}"

    def test_reverse_path_lengths(self, system, ref_adj):
        agent = load_output_data("violations.json")
        for i, v in enumerate(agent):
            if v["reverse_path"] is not None:
                ref_path = ref_bfs(ref_adj, v["pd_b"], v["pd_a"])
                assert ref_path is not None
                ref_len = len(ref_path) - 1
                assert v["reverse_length"] == ref_len, \
                    f"Constraint {i} reverse length: agent={v['reverse_length']} ref={ref_len}"

    def test_paths_are_valid(self, ref_info):
        """Every reported path must follow actual info flow edges."""
        agent = load_output_data("violations.json")
        adj = ref_get_adj(ref_info)
        for i, v in enumerate(agent):
            for direction in ["forward_path", "reverse_path"]:
                path = v[direction]
                if path is None:
                    continue
                assert len(path) >= 2, f"Constraint {i} {direction}: path too short"
                for j in range(len(path) - 1):
                    src, dst = path[j], path[j + 1]
                    assert dst in adj.get(src, set()), \
                        f"Constraint {i} {direction}: no edge {src}->{dst}"

    def test_null_paths_for_non_violated(self):
        agent = load_output_data("violations.json")
        for i, v in enumerate(agent):
            if not v["violated"]:
                assert v["forward_path"] is None, \
                    f"Non-violated constraint {i} should have null forward_path"
                assert v["reverse_path"] is None, \
                    f"Non-violated constraint {i} should have null reverse_path"


# ============================================================
# Tests: min_cuts.json
# ============================================================

class TestMinCuts:
    def test_output_exists(self):
        assert os.path.exists("/app/results/min_cuts.json")

    def test_only_violated_constraints(self, system, ref_adj, ref_reach):
        agent = load_output_data("min_cuts.json")
        violations = load_output_data("violations.json")
        violated_pairs = [(v["pd_a"], v["pd_b"]) for v in violations if v["violated"]]
        agent_pairs = [(m["pd_a"], m["pd_b"]) for m in agent]
        assert set(agent_pairs) == set(violated_pairs), \
            f"Min cuts should only be for violated constraints"

    def test_cut_sizes(self, system, ref_adj):
        agent = load_output_data("min_cuts.json")
        for m in agent:
            ref_fwd_size, _ = ref_min_cut(system, m["pd_a"], m["pd_b"], ref_adj)
            ref_rev_size, _ = ref_min_cut(system, m["pd_b"], m["pd_a"], ref_adj)
            assert m["forward_cut_size"] == ref_fwd_size, \
                f"({m['pd_a']},{m['pd_b']}) forward cut size: agent={m['forward_cut_size']} ref={ref_fwd_size}"
            assert m["reverse_cut_size"] == ref_rev_size, \
                f"({m['pd_a']},{m['pd_b']}) reverse cut size: agent={m['reverse_cut_size']} ref={ref_rev_size}"

    def test_cut_resource_count_matches_size(self):
        agent = load_output_data("min_cuts.json")
        for m in agent:
            assert len(m["forward_cut_resources"]) == m["forward_cut_size"], \
                f"({m['pd_a']},{m['pd_b']}) forward: resource count {len(m['forward_cut_resources'])} != size {m['forward_cut_size']}"
            assert len(m["reverse_cut_resources"]) == m["reverse_cut_size"], \
                f"({m['pd_a']},{m['pd_b']}) reverse: resource count {len(m['reverse_cut_resources'])} != size {m['reverse_cut_size']}"

    def test_cut_validity_forward(self, system, ref_info):
        """Removing cut resources must actually disconnect the PDs."""
        agent = load_output_data("min_cuts.json")
        for m in agent:
            if m["forward_cut_size"] == 0:
                continue
            cut_set = set(m["forward_cut_resources"])
            adj = _rebuild_adj_without_resources(system, cut_set)
            path = ref_bfs(adj, m["pd_a"], m["pd_b"])
            assert path is None, \
                f"Forward cut for ({m['pd_a']},{m['pd_b']}) doesn't actually disconnect: path={path}"

    def test_cut_validity_reverse(self, system, ref_info):
        """Removing cut resources must actually disconnect the PDs."""
        agent = load_output_data("min_cuts.json")
        for m in agent:
            if m["reverse_cut_size"] == 0:
                continue
            cut_set = set(m["reverse_cut_resources"])
            adj = _rebuild_adj_without_resources(system, cut_set)
            path = ref_bfs(adj, m["pd_b"], m["pd_a"])
            assert path is None, \
                f"Reverse cut for ({m['pd_a']},{m['pd_b']}) doesn't actually disconnect: path={path}"

    def test_zero_cut_means_no_path(self, ref_adj):
        agent = load_output_data("min_cuts.json")
        for m in agent:
            if m["forward_cut_size"] == 0:
                path = ref_bfs(ref_adj, m["pd_a"], m["pd_b"])
                assert path is None, \
                    f"Forward cut size 0 but path exists for ({m['pd_a']},{m['pd_b']})"
            if m["reverse_cut_size"] == 0:
                path = ref_bfs(ref_adj, m["pd_b"], m["pd_a"])
                assert path is None, \
                    f"Reverse cut size 0 but path exists for ({m['pd_a']},{m['pd_b']})"

    def test_resources_are_sorted(self):
        agent = load_output_data("min_cuts.json")
        for m in agent:
            assert m["forward_cut_resources"] == sorted(m["forward_cut_resources"]), \
                f"Forward cut resources not sorted for ({m['pd_a']},{m['pd_b']})"
            assert m["reverse_cut_resources"] == sorted(m["reverse_cut_resources"]), \
                f"Reverse cut resources not sorted for ({m['pd_a']},{m['pd_b']})"


def _rebuild_adj_without_resources(system, excluded_resources):
    """Rebuild information flow adjacency list excluding certain resources."""
    resource_writers = defaultdict(set)
    resource_readers = defaultdict(set)

    for ar in system["access_rights"]:
        res = ar["resource_id"]
        if res in excluded_resources:
            continue
        pd = ar["pd_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            resource_writers[res].add(pd)
        if perm in ("read", "readwrite"):
            resource_readers[res].add(pd)

    adj = defaultdict(set)
    for res in set(resource_writers.keys()) | set(resource_readers.keys()):
        for w in resource_writers[res]:
            for r in resource_readers[res]:
                if w != r:
                    adj[w].add(r)
    return adj


# ============================================================
# Overall structure tests
# ============================================================

class TestStructure:
    def test_results_directory_exists(self):
        assert os.path.isdir("/app/results"), "/app/results directory missing"

    def test_all_output_files_exist(self):
        expected = ["info_flow.json", "tcb.json", "impact.json",
                     "violations.json", "min_cuts.json"]
        for f in expected:
            assert os.path.exists(f"/app/results/{f}"), f"Missing: /app/results/{f}"

    def test_all_files_valid_json(self):
        for f in ["info_flow.json", "tcb.json", "impact.json",
                   "violations.json", "min_cuts.json"]:
            path = f"/app/results/{f}"
            if os.path.exists(path):
                with open(path) as fh:
                    try:
                        json.load(fh)
                    except json.JSONDecodeError as e:
                        pytest.fail(f"{f} is not valid JSON: {e}")

    def test_all_files_have_data_key(self):
        for f in ["info_flow.json", "tcb.json", "impact.json",
                   "violations.json", "min_cuts.json"]:
            path = f"/app/results/{f}"
            if os.path.exists(path):
                with open(path) as fh:
                    obj = json.load(fh)
                    assert "data" in obj, f"{f} missing 'data' key"
                    assert "_instance_token" in obj, f"{f} missing '_instance_token' key"
