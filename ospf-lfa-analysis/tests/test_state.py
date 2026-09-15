
"""
Independent verification of OSPF LFA coverage and link-failure sensitivity analysis.
Re-implements SPF and RFC 5286 LFA computation from reference topology data
and compares against agent-produced outputs including SQLite DB and SVG.
"""

import pytest
import json
import heapq
import os
import re
import sqlite3
from collections import defaultdict

RESULTS_DIR = "/app/results"

REFERENCE_TOPO = {
    "routers": [
        "R1", "R2", "R3", "R4", "R5", "R6", "R7",
        "R8", "R9", "R10", "R11", "R12", "R13", "R14"
    ],
    "links": [
        {"from": "R1", "to": "R2", "cost": 10},
        {"from": "R1", "to": "R3", "cost": 20},
        {"from": "R1", "to": "R4", "cost": 25},
        {"from": "R1", "to": "R13", "cost": 1},
        {"from": "R2", "to": "R3", "cost": 5},
        {"from": "R2", "to": "R5", "cost": 10},
        {"from": "R3", "to": "R6", "cost": 10},
        {"from": "R3", "to": "R7", "cost": 25},
        {"from": "R4", "to": "R7", "cost": 5},
        {"from": "R4", "to": "R8", "cost": 10},
        {"from": "R4", "to": "R14", "cost": 10},
        {"from": "R5", "to": "R6", "cost": 8},
        {"from": "R5", "to": "R9", "cost": 20},
        {"from": "R6", "to": "R7", "cost": 12},
        {"from": "R7", "to": "R8", "cost": 10},
        {"from": "R7", "to": "R10", "cost": 15},
        {"from": "R8", "to": "R9", "cost": 15},
        {"from": "R9", "to": "R10", "cost": 5},
        {"from": "R9", "to": "R11", "cost": 5},
        {"from": "R10", "to": "R12", "cost": 20},
        {"from": "R11", "to": "R12", "cost": 5}
    ],
    "source": "R1"
}

REFERENCE_ROUTERS = {
    "R1": {"router_id": "1.1.1.1", "loopback": "1.1.1.1"},
    "R2": {"router_id": "2.2.2.2", "loopback": "2.2.2.2"},
    "R3": {"router_id": "3.3.3.3", "loopback": "3.3.3.3"},
    "R4": {"router_id": "4.4.4.4", "loopback": "4.4.4.4"},
    "R5": {"router_id": "5.5.5.5", "loopback": "5.5.5.5"},
    "R6": {"router_id": "6.6.6.6", "loopback": "6.6.6.6"},
    "R7": {"router_id": "7.7.7.7", "loopback": "7.7.7.7"},
    "R8": {"router_id": "8.8.8.8", "loopback": "8.8.8.8"},
    "R9": {"router_id": "9.9.9.9", "loopback": "9.9.9.9"},
    "R10": {"router_id": "10.10.10.10", "loopback": "10.10.10.10"},
    "R11": {"router_id": "11.11.11.11", "loopback": "11.11.11.11"},
    "R12": {"router_id": "12.12.12.12", "loopback": "12.12.12.12"},
    "R13": {"router_id": "13.13.13.13", "loopback": "13.13.13.13"},
    "R14": {"router_id": "14.14.14.14", "loopback": "14.14.14.14"},
}

REFERENCE_SUBNETS = {
    ("R1", "R13"): "10.0.4.0/30",
    ("R1", "R2"): "10.0.1.0/30",
    ("R1", "R3"): "10.0.2.0/30",
    ("R1", "R4"): "10.0.3.0/30",
    ("R10", "R12"): "10.0.20.0/30",
    ("R10", "R7"): "10.0.16.0/30",
    ("R10", "R9"): "10.0.18.0/30",
    ("R11", "R12"): "10.0.21.0/30",
    ("R11", "R9"): "10.0.19.0/30",
    ("R14", "R4"): "10.0.11.0/30",
    ("R2", "R3"): "10.0.5.0/30",
    ("R2", "R5"): "10.0.6.0/30",
    ("R3", "R6"): "10.0.7.0/30",
    ("R3", "R7"): "10.0.8.0/30",
    ("R4", "R7"): "10.0.9.0/30",
    ("R4", "R8"): "10.0.10.0/30",
    ("R5", "R6"): "10.0.12.0/30",
    ("R5", "R9"): "10.0.13.0/30",
    ("R6", "R7"): "10.0.14.0/30",
    ("R7", "R8"): "10.0.15.0/30",
    ("R8", "R9"): "10.0.17.0/30",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


class ReferenceAnalyzer:
    """Independent RFC 5286 LFA implementation for verification.
    Supports optional link exclusion for sensitivity analysis."""

    def __init__(self, topo, exclude_link=None):
        self.routers = topo["routers"]
        self.source = topo["source"]
        self.adj = self._build_adj(topo, exclude_link)
        self._dist_cache = {}

    def _build_adj(self, topo, exclude_link=None):
        adj = defaultdict(dict)
        for link in topo["links"]:
            if exclude_link:
                key = tuple(sorted([link["from"], link["to"]]))
                if key == exclude_link:
                    continue
            adj[link["from"]][link["to"]] = link["cost"]
            adj[link["to"]][link["from"]] = link["cost"]
        for r in topo["routers"]:
            if r not in adj:
                adj[r] = {}
        return dict(adj)

    def dijkstra(self, source):
        dist = {r: float("inf") for r in self.adj}
        dist[source] = 0
        preds = {r: [] for r in self.adj}
        visited = set()
        heap = [(0, source)]

        while heap:
            d, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)
            for v, w in self.adj[u].items():
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    preds[v] = [u]
                    heapq.heappush(heap, (nd, v))
                elif nd == dist[v] and u not in preds[v]:
                    preds[v].append(u)

        return dist, preds

    def get_dist(self, node):
        if node not in self._dist_cache:
            d, _ = self.dijkstra(node)
            self._dist_cache[node] = d
        return self._dist_cache[node]

    def trace_next_hops(self, preds, dest):
        if dest == self.source:
            return []
        nhs = set()
        stack = [dest]
        visited = set()
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            for p in preds[n]:
                if p == self.source:
                    nhs.add(n)
                else:
                    stack.append(p)
        return sorted(nhs)

    def compute_spf(self):
        dist, preds = self.dijkstra(self.source)
        result = {}
        for r in sorted(self.adj.keys()):
            if r == self.source:
                continue
            if dist[r] == float("inf"):
                continue
            result[r] = {
                "distance": dist[r],
                "next_hops": self.trace_next_hops(preds, r),
            }
        return result

    def compute_lfa(self):
        source_dist = self.get_dist(self.source)
        _, preds = self.dijkstra(self.source)
        neighbors = sorted(self.adj[self.source].keys())

        result = {}
        for dest in sorted(self.adj.keys()):
            if dest == self.source:
                continue
            if source_dist[dest] == float("inf"):
                continue
            nhs = self.trace_next_hops(preds, dest)
            if not nhs:
                continue
            result[dest] = {}
            for nh in nhs:
                best_lfa = None
                best_type = "none"
                best_dd = float("inf")

                for n in neighbors:
                    if n == nh:
                        continue

                    d_n_d = self.get_dist(n)[dest]
                    if d_n_d == float("inf"):
                        continue
                    d_n_s = self.get_dist(n)[self.source]
                    d_s_d = source_dist[dest]

                    # Loop-free criterion
                    if d_n_d >= d_n_s + d_s_d:
                        continue

                    # Determine protection type
                    if dest == nh:
                        ptype = "link"
                    else:
                        d_n_nh = self.get_dist(n)[nh]
                        d_nh_d = self.get_dist(nh)[dest]
                        if d_n_nh == float("inf") or d_nh_d == float("inf"):
                            ptype = "node"
                        elif d_n_d < d_n_nh + d_nh_d:
                            ptype = "node"
                        else:
                            ptype = "link"

                    # Selection: node > link > none; then shortest dist; then alpha
                    if ptype == "node" and best_type != "node":
                        best_lfa, best_type, best_dd = n, ptype, d_n_d
                    elif ptype == best_type:
                        if d_n_d < best_dd or (
                            d_n_d == best_dd
                            and (best_lfa is None or n < best_lfa)
                        ):
                            best_lfa, best_type, best_dd = n, ptype, d_n_d
                    elif ptype == "link" and best_type == "none":
                        best_lfa, best_type, best_dd = n, ptype, d_n_d

                result[dest][nh] = {"lfa": best_lfa, "type": best_type}

        return result

    def compute_coverage(self, lfa_results):
        total = len(lfa_results)
        full = partial = unprotected = 0
        unprotected_list = []
        partial_list = []

        for dest in sorted(lfa_results.keys()):
            nh_map = lfa_results[dest]
            has_none = any(v["type"] == "none" for v in nh_map.values())
            has_link_only = any(
                v["type"] == "link" and dest != nh for nh, v in nh_map.items()
            )

            if has_none:
                unprotected += 1
                unprotected_list.append(dest)
            elif has_link_only:
                partial += 1
                partial_list.append(dest)
            else:
                full += 1

        return {
            "total_destinations": total,
            "fully_protected": full,
            "partially_protected": partial,
            "unprotected": unprotected,
            "unprotected_list": sorted(unprotected_list),
            "partially_protected_list": sorted(partial_list),
        }


def compute_expected_sensitivity(topo):
    """Compute expected sensitivity analysis for all links."""
    all_dests = set(r for r in topo["routers"] if r != topo["source"])
    results = {}

    for link in topo["links"]:
        key = "-".join(sorted([link["from"], link["to"]]))
        exclude = tuple(sorted([link["from"], link["to"]]))

        analyzer = ReferenceAnalyzer(topo, exclude_link=exclude)
        spf = analyzer.compute_spf()

        reachable = set(spf.keys())
        unreachable = sorted(all_dests - reachable)

        lfa = analyzer.compute_lfa()
        coverage = analyzer.compute_coverage(lfa)

        results[key] = {
            "unreachable": unreachable,
            "coverage": {
                "total_destinations": coverage["total_destinations"],
                "fully_protected": coverage["fully_protected"],
                "partially_protected": coverage["partially_protected"],
                "unprotected": coverage["unprotected"],
            },
        }

    return results


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def analyzer():
    return ReferenceAnalyzer(REFERENCE_TOPO)


@pytest.fixture(scope="module")
def expected_spf(analyzer):
    return analyzer.compute_spf()


@pytest.fixture(scope="module")
def expected_lfa(analyzer):
    return analyzer.compute_lfa()


@pytest.fixture(scope="module")
def expected_coverage(analyzer, expected_lfa):
    return analyzer.compute_coverage(expected_lfa)


@pytest.fixture(scope="module")
def expected_sensitivity():
    return compute_expected_sensitivity(REFERENCE_TOPO)


# ── File existence tests ────────────────────────────────────────


class TestFilesExist:
    def test_spf_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/spf.json"), "spf.json not found"

    def test_lfa_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/lfa.json"), "lfa.json not found"

    def test_coverage_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/coverage.json"), "coverage.json not found"

    def test_sensitivity_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/sensitivity.json"), "sensitivity.json not found"

    def test_sqlite_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/ospf_rib.db"), "ospf_rib.db not found"

    def test_svg_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/topology.svg"), "topology.svg not found"


# ── SPF tests ───────────────────────────────────────────────────


class TestSPF:
    @pytest.fixture(autouse=True)
    def setup(self, expected_spf):
        self.expected = expected_spf
        self.actual = load_json(f"{RESULTS_DIR}/spf.json")

    def test_all_destinations_present(self):
        assert set(self.actual.keys()) == set(self.expected.keys()), (
            f"Destination set mismatch: missing={set(self.expected.keys()) - set(self.actual.keys())}, "
            f"extra={set(self.actual.keys()) - set(self.expected.keys())}"
        )

    def test_distances_correct(self):
        for dest, exp in self.expected.items():
            assert dest in self.actual, f"Missing destination {dest}"
            actual_dist = self.actual[dest]["distance"]
            assert actual_dist == exp["distance"], (
                f"Distance to {dest}: expected {exp['distance']}, got {actual_dist}"
            )

    def test_next_hops_correct(self):
        for dest, exp in self.expected.items():
            assert dest in self.actual
            actual_nhs = sorted(self.actual[dest]["next_hops"])
            expected_nhs = sorted(exp["next_hops"])
            assert actual_nhs == expected_nhs, (
                f"Next-hops for {dest}: expected {expected_nhs}, got {actual_nhs}"
            )


# ── LFA tests ───────────────────────────────────────────────────


class TestLFA:
    @pytest.fixture(autouse=True)
    def setup(self, expected_lfa):
        self.expected = expected_lfa
        self.actual = load_json(f"{RESULTS_DIR}/lfa.json")

    def test_all_destinations_present(self):
        assert set(self.actual.keys()) == set(self.expected.keys()), "LFA destination set mismatch"

    def test_all_next_hops_present(self):
        for dest, exp_nhs in self.expected.items():
            assert dest in self.actual, f"Missing LFA dest {dest}"
            actual_nhs = set(self.actual[dest].keys())
            expected_nh_set = set(exp_nhs.keys())
            assert actual_nhs == expected_nh_set, (
                f"Next-hop set for {dest}: expected {expected_nh_set}, got {actual_nhs}"
            )

    def test_lfa_types_correct(self):
        for dest, exp_nhs in self.expected.items():
            for nh, exp_info in exp_nhs.items():
                actual_info = self.actual[dest][nh]
                assert actual_info["type"] == exp_info["type"], (
                    f"LFA type for {dest} via {nh}: "
                    f"expected '{exp_info['type']}', got '{actual_info['type']}'"
                )

    def test_lfa_neighbors_correct(self):
        for dest, exp_nhs in self.expected.items():
            for nh, exp_info in exp_nhs.items():
                actual_info = self.actual[dest][nh]
                assert actual_info["lfa"] == exp_info["lfa"], (
                    f"LFA neighbor for {dest} via {nh}: "
                    f"expected '{exp_info['lfa']}', got '{actual_info['lfa']}'"
                )


# ── Coverage tests ──────────────────────────────────────────────


class TestCoverage:
    @pytest.fixture(autouse=True)
    def setup(self, expected_coverage):
        self.expected = expected_coverage
        self.actual = load_json(f"{RESULTS_DIR}/coverage.json")

    def test_total_destinations(self):
        assert self.actual["total_destinations"] == self.expected["total_destinations"]

    def test_fully_protected_count(self):
        assert self.actual["fully_protected"] == self.expected["fully_protected"]

    def test_partially_protected_count(self):
        assert self.actual["partially_protected"] == self.expected["partially_protected"]

    def test_unprotected_count(self):
        assert self.actual["unprotected"] == self.expected["unprotected"]

    def test_unprotected_list(self):
        assert sorted(self.actual["unprotected_list"]) == sorted(self.expected["unprotected_list"])

    def test_partially_protected_list(self):
        assert sorted(self.actual["partially_protected_list"]) == sorted(
            self.expected["partially_protected_list"]
        )


# ── SQLite database tests ──────────────────────────────────────


class TestSQLite:
    @pytest.fixture(autouse=True)
    def setup(self, expected_spf, expected_lfa):
        self.db_path = f"{RESULTS_DIR}/ospf_rib.db"
        self.expected_spf = expected_spf
        self.expected_lfa = expected_lfa

    def _query(self, sql):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
        conn.close()
        return rows

    def test_routers_table_exists(self):
        rows = self._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routers'"
        )
        assert len(rows) == 1, "routers table not found"

    def test_routers_count(self):
        rows = self._query("SELECT COUNT(*) as cnt FROM routers")
        assert rows[0]["cnt"] == 14, f"Expected 14 routers, got {rows[0]['cnt']}"

    def test_routers_data(self):
        rows = self._query("SELECT name, router_id, loopback FROM routers ORDER BY name")
        router_map = {r["name"]: r for r in rows}
        for name, expected in REFERENCE_ROUTERS.items():
            assert name in router_map, f"Router {name} not in database"
            assert router_map[name]["router_id"] == expected["router_id"], (
                f"Router {name} router_id mismatch"
            )
            assert router_map[name]["loopback"] == expected["loopback"], (
                f"Router {name} loopback mismatch"
            )

    def test_links_table_exists(self):
        rows = self._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='links'"
        )
        assert len(rows) == 1, "links table not found"

    def test_links_count(self):
        rows = self._query("SELECT COUNT(*) as cnt FROM links")
        assert rows[0]["cnt"] == 21, f"Expected 21 links, got {rows[0]['cnt']}"

    def test_links_data(self):
        rows = self._query("SELECT router_a, router_b, cost, subnet FROM links")
        link_map = {}
        for r in rows:
            link_map[(r["router_a"], r["router_b"])] = {
                "cost": r["cost"],
                "subnet": r["subnet"],
            }
        for link in REFERENCE_TOPO["links"]:
            key = tuple(sorted([link["from"], link["to"]]))
            assert key in link_map, f"Link {key} not in database"
            assert link_map[key]["cost"] == link["cost"], (
                f"Link {key} cost: expected {link['cost']}, got {link_map[key]['cost']}"
            )

    def test_links_subnets(self):
        rows = self._query("SELECT router_a, router_b, subnet FROM links")
        for r in rows:
            key = (r["router_a"], r["router_b"])
            if key in REFERENCE_SUBNETS:
                assert r["subnet"] == REFERENCE_SUBNETS[key], (
                    f"Link {key} subnet: expected {REFERENCE_SUBNETS[key]}, got {r['subnet']}"
                )

    def test_links_alphabetical_order(self):
        rows = self._query("SELECT router_a, router_b FROM links")
        for r in rows:
            assert r["router_a"] <= r["router_b"], (
                f"Link ({r['router_a']}, {r['router_b']}) not in alphabetical order"
            )

    def test_spf_results_table_exists(self):
        rows = self._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spf_results'"
        )
        assert len(rows) == 1, "spf_results table not found"

    def test_spf_results_data(self):
        rows = self._query("SELECT destination, distance, next_hop FROM spf_results")
        actual = defaultdict(lambda: {"distance": None, "next_hops": []})
        for r in rows:
            actual[r["destination"]]["distance"] = r["distance"]
            actual[r["destination"]]["next_hops"].append(r["next_hop"])

        for dest, exp in self.expected_spf.items():
            assert dest in actual, f"SPF dest {dest} not in database"
            assert actual[dest]["distance"] == exp["distance"], (
                f"SPF distance to {dest}: expected {exp['distance']}, got {actual[dest]['distance']}"
            )
            assert sorted(actual[dest]["next_hops"]) == sorted(exp["next_hops"]), (
                f"SPF next-hops for {dest} mismatch"
            )

    def test_lfa_results_table_exists(self):
        rows = self._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lfa_results'"
        )
        assert len(rows) == 1, "lfa_results table not found"

    def test_lfa_results_data(self):
        rows = self._query(
            "SELECT destination, next_hop, lfa_neighbor, protection_type FROM lfa_results"
        )
        actual = {}
        for r in rows:
            actual[(r["destination"], r["next_hop"])] = {
                "lfa": r["lfa_neighbor"],
                "type": r["protection_type"],
            }

        for dest, nhs in self.expected_lfa.items():
            for nh, exp_info in nhs.items():
                key = (dest, nh)
                assert key in actual, f"LFA result ({dest}, {nh}) not in database"
                assert actual[key]["type"] == exp_info["type"], (
                    f"LFA type for ({dest}, {nh}): expected '{exp_info['type']}', "
                    f"got '{actual[key]['type']}'"
                )
                assert actual[key]["lfa"] == exp_info["lfa"], (
                    f"LFA neighbor for ({dest}, {nh}): expected '{exp_info['lfa']}', "
                    f"got '{actual[key]['lfa']}'"
                )


# ── Sensitivity tests ───────────────────────────────────────────


class TestSensitivity:
    @pytest.fixture(autouse=True)
    def setup(self, expected_sensitivity):
        self.expected = expected_sensitivity
        self.actual = load_json(f"{RESULTS_DIR}/sensitivity.json")

    def test_all_links_present(self):
        assert set(self.actual.keys()) == set(self.expected.keys()), (
            f"Link key mismatch: missing={set(self.expected.keys()) - set(self.actual.keys())}, "
            f"extra={set(self.actual.keys()) - set(self.expected.keys())}"
        )

    def test_unreachable_destinations(self):
        for key, exp in self.expected.items():
            actual_entry = self.actual[key]
            assert sorted(actual_entry["unreachable"]) == sorted(exp["unreachable"]), (
                f"Link {key} unreachable: expected {exp['unreachable']}, "
                f"got {actual_entry['unreachable']}"
            )

    def test_post_failure_total_destinations(self):
        for key, exp in self.expected.items():
            actual_cov = self.actual[key]["coverage"]
            exp_cov = exp["coverage"]
            assert actual_cov["total_destinations"] == exp_cov["total_destinations"], (
                f"Link {key} total_destinations: expected {exp_cov['total_destinations']}, "
                f"got {actual_cov['total_destinations']}"
            )

    def test_post_failure_fully_protected(self):
        for key, exp in self.expected.items():
            actual_cov = self.actual[key]["coverage"]
            exp_cov = exp["coverage"]
            assert actual_cov["fully_protected"] == exp_cov["fully_protected"], (
                f"Link {key} fully_protected: expected {exp_cov['fully_protected']}, "
                f"got {actual_cov['fully_protected']}"
            )

    def test_post_failure_partially_protected(self):
        for key, exp in self.expected.items():
            actual_cov = self.actual[key]["coverage"]
            exp_cov = exp["coverage"]
            assert actual_cov["partially_protected"] == exp_cov["partially_protected"], (
                f"Link {key} partially_protected: expected {exp_cov['partially_protected']}, "
                f"got {actual_cov['partially_protected']}"
            )

    def test_post_failure_unprotected(self):
        for key, exp in self.expected.items():
            actual_cov = self.actual[key]["coverage"]
            exp_cov = exp["coverage"]
            assert actual_cov["unprotected"] == exp_cov["unprotected"], (
                f"Link {key} unprotected: expected {exp_cov['unprotected']}, "
                f"got {actual_cov['unprotected']}"
            )


# ── Topology diagram tests ─────────────────────────────────────


class TestTopologyDiagram:
    def test_svg_valid(self):
        with open(f"{RESULTS_DIR}/topology.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not contain valid SVG markup"

    def test_all_routers_present(self):
        with open(f"{RESULTS_DIR}/topology.svg") as f:
            content = f.read()
        for i in range(1, 15):
            assert f"R{i}" in content, f"Router R{i} not found in SVG"

    def test_svg_has_edges(self):
        with open(f"{RESULTS_DIR}/topology.svg") as f:
            content = f.read()
        # Graphviz SVG edges contain 'edge' in class or have path elements
        # Check for cost label text elements
        found_costs = 0
        for cost in ["10", "20", "25", "8", "12", "15"]:
            if f">{cost}<" in content:
                found_costs += 1
        assert found_costs >= 3, f"Expected at least 3 cost labels in SVG, found {found_costs}"

    def test_svg_has_distinct_r1_styling(self):
        with open(f"{RESULTS_DIR}/topology.svg") as f:
            content = f.read()
        fills = set(re.findall(r'fill="([^"]+)"', content))
        node_fills = {
            f for f in fills
            if f not in (
                "#ffffff", "white", "none", "#000000", "black",
                "transparent", "# ffffff", "rgb(0,0,0)",
            )
        }
        assert len(node_fills) >= 2, (
            "Expected at least 2 distinct non-trivial fill colors (R1 should be distinct)"
        )
