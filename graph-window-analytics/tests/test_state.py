
"""
Tests for the network analysis pipeline.
Verifies that /app/analyze.sql produces correct output tables
in /app/network.db after being run via /app/run.sh.
"""

import sqlite3
import subprocess
import os
import math
import pytest


DB_PATH = "/app/network.db"


@pytest.fixture(scope="module")
def db():
    """Connect to the database that was populated by test.sh."""
    assert os.path.exists(DB_PATH), f"Database {DB_PATH} does not exist"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# Reachability tests
# ============================================================

class TestReachability:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reachability'"
        )
        assert cur.fetchone() is not None, "reachability table does not exist"

    def test_row_count(self, db):
        """57 reachable (src, dst) pairs with src != dst in the network."""
        cur = db.execute("SELECT COUNT(*) as cnt FROM reachability")
        count = cur.fetchone()["cnt"]
        assert count == 57, f"Expected 57 rows, got {count}"

    def test_no_self_pairs(self, db):
        cur = db.execute(
            "SELECT COUNT(*) as cnt FROM reachability WHERE src_id = dst_id"
        )
        count = cur.fetchone()["cnt"]
        assert count == 0, f"Found {count} self-pairs in reachability"

    def test_direct_edge_hops(self, db):
        """Direct edges should have hops = 1."""
        cur = db.execute(
            "SELECT hops FROM reachability WHERE src_id = 1 AND dst_id = 2"
        )
        row = cur.fetchone()
        assert row is not None, "Missing reachability entry (1, 2)"
        assert row["hops"] == 1, f"Expected 1 hop for (1,2), got {row['hops']}"

    def test_multi_hop(self, db):
        """Node 1 to node 6 requires 3 hops minimum."""
        cur = db.execute(
            "SELECT hops FROM reachability WHERE src_id = 1 AND dst_id = 6"
        )
        row = cur.fetchone()
        assert row is not None, "Missing reachability entry (1, 6)"
        assert row["hops"] == 3, f"Expected 3 hops for (1,6), got {row['hops']}"

    def test_gamma_to_alpha_unreachable(self, db):
        """Gamma nodes (8,9,10) cannot reach alpha nodes (1-4)."""
        cur = db.execute(
            "SELECT COUNT(*) as cnt FROM reachability "
            "WHERE src_id IN (8,9,10) AND dst_id IN (1,2,3,4)"
        )
        count = cur.fetchone()["cnt"]
        assert count == 0, f"Gamma-to-alpha entries should not exist, found {count}"

    def test_gamma_to_beta_unreachable(self, db):
        """Gamma nodes cannot reach beta nodes."""
        cur = db.execute(
            "SELECT COUNT(*) as cnt FROM reachability "
            "WHERE src_id IN (8,9,10) AND dst_id IN (5,6,7)"
        )
        count = cur.fetchone()["cnt"]
        assert count == 0, f"Gamma-to-beta entries should not exist, found {count}"

    def test_beta_to_alpha_unreachable(self, db):
        """Beta nodes (5,6,7) cannot reach alpha nodes (1-4)."""
        cur = db.execute(
            "SELECT COUNT(*) as cnt FROM reachability "
            "WHERE src_id IN (5,6,7) AND dst_id IN (1,2,3,4)"
        )
        count = cur.fetchone()["cnt"]
        assert count == 0, f"Beta-to-alpha entries should not exist, found {count}"

    def test_alpha_reach_count(self, db):
        """Each alpha node should reach 9 other nodes."""
        for node_id in [1, 2, 3, 4]:
            cur = db.execute(
                "SELECT COUNT(*) as cnt FROM reachability WHERE src_id = ?",
                (node_id,),
            )
            count = cur.fetchone()["cnt"]
            assert count == 9, (
                f"Alpha node {node_id} should reach 9 nodes, got {count}"
            )

    def test_gamma_reach_count(self, db):
        """Each gamma node should reach 2 other nodes."""
        for node_id in [8, 9, 10]:
            cur = db.execute(
                "SELECT COUNT(*) as cnt FROM reachability WHERE src_id = ?",
                (node_id,),
            )
            count = cur.fetchone()["cnt"]
            assert count == 2, (
                f"Gamma node {node_id} should reach 2 nodes, got {count}"
            )


# ============================================================
# Shortest path tests
# ============================================================

class TestShortestPath:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shortest_path'"
        )
        assert cur.fetchone() is not None, "shortest_path table does not exist"

    def test_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) as cnt FROM shortest_path")
        count = cur.fetchone()["cnt"]
        assert count == 57, f"Expected 57 rows, got {count}"

    def test_no_self_pairs(self, db):
        cur = db.execute(
            "SELECT COUNT(*) as cnt FROM shortest_path WHERE src_id = dst_id"
        )
        count = cur.fetchone()["cnt"]
        assert count == 0, f"Found {count} self-pairs in shortest_path"

    def test_direct_edge_distance(self, db):
        """1→2 direct edge weight is 2.0, which is the shortest."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 1 AND dst_id = 2"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 2.0) < 0.001

    def test_shortcut_path(self, db):
        """1→3: direct edge = 4.0, via 1→2→3 = 5.0. Shortest is 4.0."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 1 AND dst_id = 3"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 4.0) < 0.001

    def test_multi_hop_distance(self, db):
        """1→6: via 1→3→4→6 = 4+1+3 = 8.0."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 1 AND dst_id = 6"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 8.0) < 0.001

    def test_cross_region_distance(self, db):
        """1→9: via 1→3→4→6→7→9 = 4+1+3+4+2 = 14.0."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 1 AND dst_id = 9"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 14.0) < 0.001

    def test_beta_internal(self, db):
        """5→7: via 5→6→7 = 2+4 = 6.0 (shorter than direct 7.0)."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 5 AND dst_id = 7"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 6.0) < 0.001

    def test_gamma_internal(self, db):
        """8→10: via 8→9→10 = 1+3 = 4.0 (shorter than direct 6.0)."""
        cur = db.execute(
            "SELECT distance FROM shortest_path WHERE src_id = 8 AND dst_id = 10"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["distance"] - 4.0) < 0.001

    def test_triangle_inequality(self, db):
        """For any reachable triple (a,b), (b,c), (a,c): dist(a,c) <= dist(a,b)+dist(b,c)."""
        cur = db.execute("""
            SELECT sp1.src_id as a, sp1.dst_id as b, sp2.dst_id as c,
                   sp1.distance as ab, sp2.distance as bc, sp3.distance as ac
            FROM shortest_path sp1
            JOIN shortest_path sp2 ON sp1.dst_id = sp2.src_id
            JOIN shortest_path sp3 ON sp1.src_id = sp3.src_id AND sp2.dst_id = sp3.dst_id
            WHERE sp3.distance > sp1.distance + sp2.distance + 0.001
        """)
        violations = cur.fetchall()
        assert len(violations) == 0, (
            f"Triangle inequality violated for {len(violations)} triples"
        )


# ============================================================
# Path detail tests
# ============================================================

class TestPathDetail:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='path_detail'"
        )
        assert cur.fetchone() is not None, "path_detail table does not exist"

    def test_row_count(self, db):
        """Same number of pairs as shortest_path: 57."""
        cur = db.execute("SELECT COUNT(*) as cnt FROM path_detail")
        count = cur.fetchone()["cnt"]
        assert count == 57, f"Expected 57 rows in path_detail, got {count}"

    def test_weight_consistency(self, db):
        """total_weight must match shortest_path.distance for every pair."""
        cur = db.execute("""
            SELECT pd.src_id, pd.dst_id, pd.total_weight, sp.distance
            FROM path_detail pd
            JOIN shortest_path sp ON pd.src_id = sp.src_id AND pd.dst_id = sp.dst_id
            WHERE ABS(pd.total_weight - sp.distance) > 0.001
        """)
        mismatches = cur.fetchall()
        assert len(mismatches) == 0, (
            f"path_detail.total_weight mismatches shortest_path.distance "
            f"for {len(mismatches)} pairs"
        )

    def test_all_pairs_covered(self, db):
        """Every shortest_path pair must have a path_detail entry."""
        cur = db.execute("""
            SELECT sp.src_id, sp.dst_id
            FROM shortest_path sp
            LEFT JOIN path_detail pd ON sp.src_id = pd.src_id AND sp.dst_id = pd.dst_id
            WHERE pd.src_id IS NULL
        """)
        missing = cur.fetchall()
        assert len(missing) == 0, (
            f"{len(missing)} shortest_path pairs have no path_detail entry"
        )

    def test_direct_edge_path(self, db):
        """1→2 is a direct edge, path should be '1,2'."""
        cur = db.execute(
            "SELECT path_nodes FROM path_detail WHERE src_id = 1 AND dst_id = 2"
        )
        row = cur.fetchone()
        assert row is not None, "Missing path_detail entry (1, 2)"
        assert row["path_nodes"] == "1,2", (
            f"Expected '1,2', got '{row['path_nodes']}'"
        )

    def test_multi_hop_path(self, db):
        """1→4 shortest is via node 3 (weight 5.0). Path: '1,3,4'."""
        cur = db.execute(
            "SELECT path_nodes, total_weight FROM path_detail "
            "WHERE src_id = 1 AND dst_id = 4"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["path_nodes"] == "1,3,4", (
            f"Expected '1,3,4', got '{row['path_nodes']}'"
        )
        assert abs(row["total_weight"] - 5.0) < 0.001

    def test_cross_region_path(self, db):
        """1→9 shortest via 1→3→4→6→7→9 (14.0)."""
        cur = db.execute(
            "SELECT path_nodes, total_weight FROM path_detail "
            "WHERE src_id = 1 AND dst_id = 9"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["path_nodes"] == "1,3,4,6,7,9", (
            f"Expected '1,3,4,6,7,9', got '{row['path_nodes']}'"
        )
        assert abs(row["total_weight"] - 14.0) < 0.001

    def test_shorter_indirect_path(self, db):
        """2→4: direct edge = 5.0, via 3 = 4.0. Must take '2,3,4'."""
        cur = db.execute(
            "SELECT path_nodes FROM path_detail WHERE src_id = 2 AND dst_id = 4"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["path_nodes"] == "2,3,4", (
            f"Expected '2,3,4', got '{row['path_nodes']}'"
        )

    def test_gamma_internal_path(self, db):
        """8→10: direct = 6.0, via 9 = 4.0. Path: '8,9,10'."""
        cur = db.execute(
            "SELECT path_nodes, total_weight FROM path_detail "
            "WHERE src_id = 8 AND dst_id = 10"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["path_nodes"] == "8,9,10", (
            f"Expected '8,9,10', got '{row['path_nodes']}'"
        )
        assert abs(row["total_weight"] - 4.0) < 0.001

    def test_path_endpoints(self, db):
        """Every path must start with src_id and end with dst_id."""
        cur = db.execute("SELECT src_id, dst_id, path_nodes FROM path_detail")
        for row in cur.fetchall():
            nodes = row["path_nodes"].split(",")
            assert int(nodes[0]) == row["src_id"], (
                f"Path {row['path_nodes']} doesn't start with src_id {row['src_id']}"
            )
            assert int(nodes[-1]) == row["dst_id"], (
                f"Path {row['path_nodes']} doesn't end with dst_id {row['dst_id']}"
            )

    def test_no_repeated_nodes(self, db):
        """No path should visit the same node twice."""
        cur = db.execute("SELECT src_id, dst_id, path_nodes FROM path_detail")
        for row in cur.fetchall():
            nodes = row["path_nodes"].split(",")
            assert len(nodes) == len(set(nodes)), (
                f"Path ({row['src_id']},{row['dst_id']}): "
                f"repeated nodes in {row['path_nodes']}"
            )

    def test_path_edges_valid(self, db):
        """Every consecutive pair in the path must be a real edge."""
        edges = set()
        edge_cur = db.execute("SELECT src, dst FROM edge")
        for e in edge_cur.fetchall():
            edges.add((e["src"], e["dst"]))

        cur = db.execute("SELECT src_id, dst_id, path_nodes FROM path_detail")
        for row in cur.fetchall():
            nodes = [int(n) for n in row["path_nodes"].split(",")]
            for i in range(len(nodes) - 1):
                assert (nodes[i], nodes[i + 1]) in edges, (
                    f"Path ({row['src_id']},{row['dst_id']}): "
                    f"edge ({nodes[i]},{nodes[i+1]}) does not exist"
                )

    def test_long_path(self, db):
        """1→10 requires traversing multiple regions: weight 17.0."""
        cur = db.execute(
            "SELECT path_nodes, total_weight FROM path_detail "
            "WHERE src_id = 1 AND dst_id = 10"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["total_weight"] - 17.0) < 0.001
        nodes = row["path_nodes"].split(",")
        assert int(nodes[0]) == 1
        assert int(nodes[-1]) == 10
        assert len(nodes) >= 5, (
            f"1→10 path should be at least 5 nodes long, got {len(nodes)}"
        )


# ============================================================
# Node centrality tests
# ============================================================

class TestNodeCentrality:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_centrality'"
        )
        assert cur.fetchone() is not None

    def test_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) as cnt FROM node_centrality")
        assert cur.fetchone()["cnt"] == 10

    def test_reach_counts(self, db):
        """Alpha=9, Beta=5, Gamma=2."""
        expected = {1: 9, 2: 9, 3: 9, 4: 9, 5: 5, 6: 5, 7: 5, 8: 2, 9: 2, 10: 2}
        for nid, exp_rc in expected.items():
            cur = db.execute(
                "SELECT reach_count FROM node_centrality WHERE node_id = ?", (nid,)
            )
            row = cur.fetchone()
            assert row is not None, f"Missing node_centrality for node {nid}"
            assert row["reach_count"] == exp_rc, (
                f"Node {nid}: expected reach_count={exp_rc}, got {row['reach_count']}"
            )

    def test_centrality_rank_descending(self, db):
        """Rank 1 = highest reach_count (9), rank 2 = 5, rank 3 = 2."""
        cur = db.execute(
            "SELECT centrality_rank FROM node_centrality WHERE node_id = 1"
        )
        assert cur.fetchone()["centrality_rank"] == 1, "Alpha nodes should be rank 1"

        cur = db.execute(
            "SELECT centrality_rank FROM node_centrality WHERE node_id = 5"
        )
        assert cur.fetchone()["centrality_rank"] == 2, "Beta nodes should be rank 2"

        cur = db.execute(
            "SELECT centrality_rank FROM node_centrality WHERE node_id = 8"
        )
        assert cur.fetchone()["centrality_rank"] == 3, "Gamma nodes should be rank 3"

    def test_region_rank_partitioned(self, db):
        """Node 5 (out_degree=3) should be rank 1 in beta.
        Node 6 (out_degree=1) should be rank 3 in beta."""
        cur = db.execute(
            "SELECT region_rank FROM node_centrality WHERE node_id = 5"
        )
        assert cur.fetchone()["region_rank"] == 1, (
            "Node 5 should be region_rank 1 in beta (highest out_degree=3)"
        )

        cur = db.execute(
            "SELECT region_rank FROM node_centrality WHERE node_id = 6"
        )
        assert cur.fetchone()["region_rank"] == 3, (
            "Node 6 should be region_rank 3 in beta (lowest out_degree=1)"
        )

    def test_region_rank_alpha_tied(self, db):
        """All alpha nodes have out_degree=2, so all should be rank 1."""
        for nid in [1, 2, 3, 4]:
            cur = db.execute(
                "SELECT region_rank FROM node_centrality WHERE node_id = ?", (nid,)
            )
            row = cur.fetchone()
            assert row["region_rank"] == 1, (
                f"Alpha node {nid} should be region_rank 1 (all tied out_degree=2)"
            )

    def test_capacity_percentile_uses_percent_rank(self, db):
        """Node 4 has lowest capacity (60) → percent_rank = 0.0.
        Node 8 has highest capacity (150) → percent_rank = 1.0.
        cume_dist would give 0.1 and 1.0 respectively."""
        cur = db.execute(
            "SELECT capacity_percentile FROM node_centrality WHERE node_id = 4"
        )
        pct = cur.fetchone()["capacity_percentile"]
        assert abs(pct - 0.0) < 0.001, (
            f"Node 4 (lowest capacity) should have capacity_percentile=0.0, got {pct}"
        )

        cur = db.execute(
            "SELECT capacity_percentile FROM node_centrality WHERE node_id = 8"
        )
        pct = cur.fetchone()["capacity_percentile"]
        assert abs(pct - 1.0) < 0.001, (
            f"Node 8 (highest capacity) should have capacity_percentile=1.0, got {pct}"
        )

    def test_capacity_percentile_intermediate(self, db):
        """Node 2 (capacity=75) is 2nd lowest. percent_rank = 1/9 ≈ 0.1111.
        cume_dist would give 2/10 = 0.2."""
        cur = db.execute(
            "SELECT capacity_percentile FROM node_centrality WHERE node_id = 2"
        )
        pct = cur.fetchone()["capacity_percentile"]
        expected = 1.0 / 9.0  # percent_rank
        assert abs(pct - expected) < 0.001, (
            f"Node 2 percent_rank should be ~{expected:.4f}, got {pct}"
        )


# ============================================================
# Traffic summary tests
# ============================================================

class TestTrafficSummary:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='traffic_summary'"
        )
        assert cur.fetchone() is not None

    def test_row_count(self, db):
        """18 edges total."""
        cur = db.execute("SELECT COUNT(*) as cnt FROM traffic_summary")
        assert cur.fetchone()["cnt"] == 18

    def test_running_avg_uses_groups(self, db):
        """For alpha region, edges with weight=3.0 form a peer group.
        GROUPS: frame = {2.0, 3.0, 3.0, 4.0} → avg = 3.0
        ROWS would give different values (2.667 and 3.333) for the two rows."""
        cur = db.execute(
            "SELECT running_avg FROM traffic_summary "
            "WHERE region = 'alpha' AND weight = 3.0"
        )
        rows = cur.fetchall()
        assert len(rows) == 2, f"Expected 2 alpha rows with weight=3.0, got {len(rows)}"
        for row in rows:
            assert abs(row["running_avg"] - 3.0) < 0.001, (
                f"Alpha weight=3.0 running_avg should be 3.0, got {row['running_avg']}"
            )

    def test_running_avg_boundary(self, db):
        """Alpha weight=1.0 (first group): frame = {1.0, 2.0} → avg = 1.5."""
        cur = db.execute(
            "SELECT running_avg FROM traffic_summary "
            "WHERE region = 'alpha' AND weight = 1.0"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["running_avg"] - 1.5) < 0.001

    def test_running_avg_groups_vs_rows(self, db):
        """Alpha weight=2.0: GROUPS frame = {1.0, 2.0, 3.0, 3.0} → avg = 2.25.
        ROWS would give {1.0, 2.0, 3.0} → avg = 2.0."""
        cur = db.execute(
            "SELECT running_avg FROM traffic_summary "
            "WHERE region = 'alpha' AND weight = 2.0"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["running_avg"] - 2.25) < 0.001, (
            f"Alpha weight=2.0 running_avg should be 2.25, got {row['running_avg']}"
        )

    def test_primary_count_filter(self, db):
        """Alpha region, secondary edge at weight=3.0 (edge 4→6):
        With FILTER: primary_count_so_far = 3 (edges 3→4, 1→2, 2→3 are primary before it).
        Without FILTER: it would be 4 (counting all rows)."""
        cur = db.execute(
            "SELECT primary_count_so_far FROM traffic_summary "
            "WHERE region = 'alpha' AND edge_type = 'secondary' AND weight = 3.0"
        )
        row = cur.fetchone()
        assert row is not None, "Missing alpha secondary edge at weight=3.0"
        assert row["primary_count_so_far"] == 3, (
            f"Expected primary_count_so_far=3, got {row['primary_count_so_far']}"
        )

    def test_primary_count_at_end(self, db):
        """Alpha region, last edge (weight=6.0, primary 3→5):
        primary_count_so_far = 4 (4 primary edges total in alpha)."""
        cur = db.execute(
            "SELECT primary_count_so_far FROM traffic_summary "
            "WHERE region = 'alpha' AND weight = 6.0"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["primary_count_so_far"] == 4

    def test_primary_count_beta_filter(self, db):
        """Beta region at weight=3.0 (backup edge 7→5):
        Only 1 primary edge so far (5→6 at weight=2.0). So count = 1."""
        cur = db.execute(
            "SELECT primary_count_so_far FROM traffic_summary "
            "WHERE region = 'beta' AND weight = 3.0 AND edge_type = 'backup'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["primary_count_so_far"] == 1, (
            f"Beta backup weight=3.0: expected primary_count_so_far=1, "
            f"got {row['primary_count_so_far']}"
        )


# ============================================================
# Network KPIs tests
# ============================================================

class TestNetworkKPIs:
    def test_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_kpis'"
        )
        assert cur.fetchone() is not None

    def test_total_nodes(self, db):
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'total_nodes'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["metric_value"] == 10

    def test_total_edges(self, db):
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'total_edges'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["metric_value"] == 18

    def test_avg_shortest_path_nonzero(self, db):
        """If UPSERT is broken, avg_shortest_path stays at 0."""
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'avg_shortest_path'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["metric_value"] > 1.0, (
            f"avg_shortest_path should be > 1.0, got {row['metric_value']}"
        )

    def test_avg_shortest_path_value(self, db):
        """Sum of all 57 shortest paths = 430.0. Avg = 430/57 ≈ 7.5439."""
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'avg_shortest_path'"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["metric_value"] - 7.5439) < 0.01, (
            f"avg_shortest_path should be ~7.5439, got {row['metric_value']}"
        )

    def test_max_hops(self, db):
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'max_hops'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["metric_value"] == 4, (
            f"max_hops should be 4, got {row['metric_value']}"
        )

    def test_network_diameter(self, db):
        """Longest shortest path: 1→10 = 17.0."""
        cur = db.execute(
            "SELECT metric_value FROM network_kpis WHERE metric_name = 'network_diameter'"
        )
        row = cur.fetchone()
        assert row is not None
        assert abs(row["metric_value"] - 17.0) < 0.001, (
            f"network_diameter should be 17.0, got {row['metric_value']}"
        )


# ============================================================
# Index tests
# ============================================================

class TestIndexes:
    def test_edge_dst_index_exists(self, db):
        """An index on edge(dst) must exist for efficient in-degree lookups."""
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='edge'"
        )
        indexes = [row["name"] for row in cur.fetchall()]
        # Check that EXPLAIN QUERY PLAN for dst lookup uses SEARCH not SCAN
        cur = db.execute("EXPLAIN QUERY PLAN SELECT * FROM edge WHERE dst = 5")
        plan = " ".join(row["detail"] for row in cur.fetchall())
        assert "SCAN" not in plan, (
            f"Query plan for edge dst lookup uses SCAN (no index on dst): {plan}"
        )
