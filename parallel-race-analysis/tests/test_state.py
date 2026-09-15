
import json
import os
import sqlite3
import pytest


@pytest.fixture
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def db():
    path = "/app/analysis.db"
    assert os.path.exists(path), "analysis.db not found at /app/analysis.db"
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


@pytest.fixture
def dot_content():
    path = "/app/graph.dot"
    assert os.path.exists(path), "graph.dot not found at /app/graph.dot"
    with open(path) as f:
        return f.read()


# --- Expected values computed from the computation graph ---

EXPECTED_HB_PAIRS = sorted([
    [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [0, 7],
    [0, 8], [0, 9], [0, 10], [0, 11], [0, 12], [0, 13], [0, 14],
    [1, 3], [1, 4], [1, 8], [1, 9], [1, 13], [1, 14],
    [2, 5], [2, 6], [2, 7], [2, 10], [2, 11], [2, 12], [2, 14],
    [3, 9], [3, 13], [3, 14],
    [4, 8], [4, 14],
    [5, 7], [5, 10], [5, 12], [5, 14],
    [6, 11], [6, 12], [6, 14],
    [7, 12], [7, 14],
    [8, 14],
    [9, 13], [9, 14],
    [10, 12], [10, 14],
    [11, 12], [11, 14],
    [12, 14],
    [13, 14],
])

EXPECTED_MHP_PAIRS = sorted([
    [1, 2], [1, 5], [1, 6], [1, 7], [1, 10], [1, 11], [1, 12],
    [2, 3], [2, 4], [2, 8], [2, 9], [2, 13],
    [3, 4], [3, 5], [3, 6], [3, 7], [3, 8], [3, 10], [3, 11], [3, 12],
    [4, 5], [4, 6], [4, 7], [4, 9], [4, 10], [4, 11], [4, 12], [4, 13],
    [5, 6], [5, 8], [5, 9], [5, 11], [5, 13],
    [6, 7], [6, 8], [6, 9], [6, 10], [6, 13],
    [7, 8], [7, 9], [7, 10], [7, 11], [7, 13],
    [8, 9], [8, 10], [8, 11], [8, 12], [8, 13],
    [9, 10], [9, 11], [9, 12],
    [10, 11], [10, 13],
    [11, 13],
    [12, 13],
])

EXPECTED_RACES = sorted([
    {"nodes": [1, 2], "variables": ["x"]},
    {"nodes": [1, 5], "variables": ["y"]},
    {"nodes": [1, 10], "variables": ["x", "y"]},
    {"nodes": [1, 12], "variables": ["y"]},
    {"nodes": [2, 3], "variables": ["z"]},
    {"nodes": [2, 4], "variables": ["x"]},
    {"nodes": [2, 9], "variables": ["x"]},
    {"nodes": [3, 5], "variables": ["y", "z"]},
    {"nodes": [3, 6], "variables": ["z"]},
    {"nodes": [3, 10], "variables": ["y"]},
    {"nodes": [3, 11], "variables": ["z"]},
    {"nodes": [3, 12], "variables": ["z"]},
    {"nodes": [4, 5], "variables": ["y"]},
    {"nodes": [4, 10], "variables": ["x", "y"]},
    {"nodes": [5, 6], "variables": ["z"]},
    {"nodes": [5, 8], "variables": ["y"]},
    {"nodes": [5, 9], "variables": ["z"]},
    {"nodes": [5, 11], "variables": ["z"]},
    {"nodes": [6, 7], "variables": ["w"]},
    {"nodes": [6, 8], "variables": ["w"]},
    {"nodes": [6, 13], "variables": ["w"]},
    {"nodes": [7, 8], "variables": ["w"]},
    {"nodes": [7, 10], "variables": ["x"]},
    {"nodes": [7, 11], "variables": ["w"]},
    {"nodes": [7, 13], "variables": ["w"]},
    {"nodes": [8, 10], "variables": ["y"]},
    {"nodes": [8, 13], "variables": ["w"]},
    {"nodes": [9, 10], "variables": ["x"]},
    {"nodes": [9, 11], "variables": ["z"]},
    {"nodes": [11, 13], "variables": ["w"]},
], key=lambda r: tuple(r["nodes"]))

EXPECTED_WORK = 44
EXPECTED_SPAN = 18
EXPECTED_IDEAL_PARALLELISM = 2.4444

# Expected edge counts in DOT file by color
EXPECTED_CONTINUE_EDGES = 8   # black
EXPECTED_SPAWN_EDGES = 4      # blue
EXPECTED_FUTURE_GET_EDGES = 1  # green
EXPECTED_FINISH_JOIN_EDGES = 12  # red (excluding overlaps with direct edges)
EXPECTED_RACE_EDGES = 30      # orange

# Expected data_races table rows (one per variable per race pair)
EXPECTED_RACE_ROWS = 33  # 27 single-var races + 3 two-var races (6 rows)


def _normalize_pair_list(pairs):
    return sorted([sorted(p) for p in pairs])


def _normalize_races(races):
    normalized = []
    for r in races:
        normalized.append({
            "nodes": sorted(r["nodes"]),
            "variables": sorted(r["variables"]),
        })
    return sorted(normalized, key=lambda r: tuple(r["nodes"]))


# ==================== JSON Report Tests ====================

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_valid_json(self, results):
        assert isinstance(results, dict), "results.json must be a JSON object"

    def test_required_keys(self, results):
        required = [
            "happens_before_pairs", "mhp_pairs", "data_races",
            "work", "span", "ideal_parallelism", "isolated_nodes"
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"


class TestHappensBefore:
    def test_hb_pair_count(self, results):
        hb = _normalize_pair_list(results["happens_before_pairs"])
        assert len(hb) == 50, f"Expected 50 HB pairs, got {len(hb)}"

    def test_hb_pairs_exact(self, results):
        hb = _normalize_pair_list(results["happens_before_pairs"])
        expected = _normalize_pair_list(EXPECTED_HB_PAIRS)
        assert hb == expected, (
            f"HB pairs mismatch.\n"
            f"Missing: {[p for p in expected if p not in hb]}\n"
            f"Extra: {[p for p in hb if p not in expected]}"
        )

    def test_hb_includes_transitive(self, results):
        hb = _normalize_pair_list(results["happens_before_pairs"])
        assert [0, 7] in hb, "Missing transitive HB: N0 -> N7"

    def test_hb_includes_finish_join(self, results):
        hb = _normalize_pair_list(results["happens_before_pairs"])
        assert [6, 12] in hb, "Missing finish-join HB: N6 -> N12"

    def test_hb_no_spurious_reverse(self, results):
        hb = _normalize_pair_list(results["happens_before_pairs"])
        assert [1, 2] not in hb, "Spurious HB: N1 -> N2 (should be MHP)"


class TestMHP:
    def test_mhp_pair_count(self, results):
        mhp = _normalize_pair_list(results["mhp_pairs"])
        assert len(mhp) == 55, f"Expected 55 MHP pairs, got {len(mhp)}"

    def test_mhp_pairs_exact(self, results):
        mhp = _normalize_pair_list(results["mhp_pairs"])
        expected = _normalize_pair_list(EXPECTED_MHP_PAIRS)
        assert mhp == expected, (
            f"MHP pairs mismatch.\n"
            f"Missing: {[p for p in expected if p not in mhp]}\n"
            f"Extra: {[p for p in mhp if p not in expected]}"
        )

    def test_mhp_contains_cross_scope(self, results):
        mhp = _normalize_pair_list(results["mhp_pairs"])
        assert [3, 5] in mhp, "Missing MHP: N3 and N5 (cross-scope parallel)"

    def test_mhp_excludes_ordered(self, results):
        mhp = _normalize_pair_list(results["mhp_pairs"])
        assert [5, 7] not in mhp, "Spurious MHP: N5 and N7 are ordered (spawn)"


class TestDataRaces:
    def test_race_count(self, results):
        races = _normalize_races(results["data_races"])
        assert len(races) == 30, f"Expected 30 data races, got {len(races)}"

    def test_races_exact(self, results):
        races = _normalize_races(results["data_races"])
        expected = _normalize_races(EXPECTED_RACES)
        assert races == expected, (
            f"Data race mismatch.\n"
            f"Missing: {[r for r in expected if r not in races]}\n"
            f"Extra: {[r for r in races if r not in expected]}"
        )

    def test_race_includes_multi_var(self, results):
        races = _normalize_races(results["data_races"])
        target = {"nodes": [1, 10], "variables": ["x", "y"]}
        assert target in races, "Missing multi-variable race: N1 vs N10 on {x, y}"

    def test_no_read_read_race(self, results):
        races = _normalize_races(results["data_races"])
        for r in races:
            assert r["nodes"] != [4, 9], "False race: N4 vs N9 (read-read only)"

    def test_no_race_on_non_mhp(self, results):
        races = _normalize_races(results["data_races"])
        for r in races:
            assert r["nodes"] != [0, 2], "False race: N0 vs N2 (not MHP)"


class TestWorkSpan:
    def test_work(self, results):
        assert results["work"] == EXPECTED_WORK, (
            f"Expected work={EXPECTED_WORK}, got {results['work']}"
        )

    def test_span(self, results):
        assert results["span"] == EXPECTED_SPAN, (
            f"Expected span={EXPECTED_SPAN}, got {results['span']}"
        )

    def test_ideal_parallelism(self, results):
        ip = results["ideal_parallelism"]
        assert abs(ip - EXPECTED_IDEAL_PARALLELISM) < 0.001, (
            f"Expected ideal_parallelism~={EXPECTED_IDEAL_PARALLELISM}, got {ip}"
        )


class TestIsolation:
    def test_isolation_set_size(self, results):
        iso = results["isolated_nodes"]
        assert len(iso) == 8, (
            f"Expected minimum isolation set of size 8, got {len(iso)}"
        )

    def test_isolation_covers_all_races(self, results):
        iso_set = set(results["isolated_nodes"])
        for race in EXPECTED_RACES:
            n1, n2 = race["nodes"]
            assert n1 in iso_set or n2 in iso_set, (
                f"Race ({n1}, {n2}) not covered by isolation set {iso_set}"
            )

    def test_isolation_is_minimal(self, results):
        iso = results["isolated_nodes"]
        iso_set = set(iso)
        race_edges = [(r["nodes"][0], r["nodes"][1]) for r in EXPECTED_RACES]
        for node in iso:
            reduced = iso_set - {node}
            all_covered = all(
                n1 in reduced or n2 in reduced
                for n1, n2 in race_edges
            )
            assert not all_covered, (
                f"Isolation set is not minimal: removing {node} still covers all races"
            )


# ==================== SQLite Database Tests ====================

class TestSQLiteDatabase:
    def test_db_exists(self):
        assert os.path.exists("/app/analysis.db"), "analysis.db not found"

    def test_all_tables_exist(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        expected = {"nodes", "happens_before", "mhp_pairs", "data_races",
                    "metrics", "isolated_nodes"}
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"

    def test_nodes_count(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM nodes")
        count = cursor.fetchone()[0]
        assert count == 15, f"Expected 15 nodes, got {count}"

    def test_nodes_weights(self, db):
        expected_weights = {
            0: 2, 1: 3, 2: 5, 3: 1, 4: 4, 5: 2, 6: 3, 7: 6,
            8: 2, 9: 1, 10: 4, 11: 3, 12: 2, 13: 5, 14: 1
        }
        cursor = db.cursor()
        cursor.execute("SELECT id, weight FROM nodes ORDER BY id")
        rows = cursor.fetchall()
        actual = {r[0]: r[1] for r in rows}
        assert actual == expected_weights, f"Node weights mismatch: {actual}"

    def test_hb_count(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM happens_before")
        count = cursor.fetchone()[0]
        assert count == 50, f"Expected 50 HB rows, got {count}"

    def test_hb_pairs_match(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT src, dst FROM happens_before ORDER BY src, dst")
        db_pairs = [[r[0], r[1]] for r in cursor.fetchall()]
        expected = _normalize_pair_list(EXPECTED_HB_PAIRS)
        actual = _normalize_pair_list(db_pairs)
        assert actual == expected, "HB pairs in database do not match expected"

    def test_mhp_count(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM mhp_pairs")
        count = cursor.fetchone()[0]
        assert count == 55, f"Expected 55 MHP rows, got {count}"

    def test_mhp_node1_less_than_node2(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT node1, node2 FROM mhp_pairs WHERE node1 >= node2")
        bad = cursor.fetchall()
        assert len(bad) == 0, f"MHP pairs with node1 >= node2: {bad}"

    def test_data_races_row_count(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM data_races")
        count = cursor.fetchone()[0]
        assert count == EXPECTED_RACE_ROWS, (
            f"Expected {EXPECTED_RACE_ROWS} data_races rows, got {count}"
        )

    def test_metrics_work(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT value FROM metrics WHERE key='work'")
        row = cursor.fetchone()
        assert row is not None, "Missing 'work' metric"
        assert int(row[0]) == EXPECTED_WORK, f"Expected work={EXPECTED_WORK}, got {row[0]}"

    def test_metrics_span(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT value FROM metrics WHERE key='span'")
        row = cursor.fetchone()
        assert row is not None, "Missing 'span' metric"
        assert int(row[0]) == EXPECTED_SPAN, f"Expected span={EXPECTED_SPAN}, got {row[0]}"

    def test_metrics_parallelism(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT value FROM metrics WHERE key='ideal_parallelism'")
        row = cursor.fetchone()
        assert row is not None, "Missing 'ideal_parallelism' metric"
        assert abs(row[0] - EXPECTED_IDEAL_PARALLELISM) < 0.001, (
            f"Expected ~{EXPECTED_IDEAL_PARALLELISM}, got {row[0]}"
        )

    def test_isolated_nodes_count(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM isolated_nodes")
        count = cursor.fetchone()[0]
        assert count == 8, f"Expected 8 isolated nodes, got {count}"

    def test_isolated_nodes_cover_all_races(self, db):
        cursor = db.cursor()
        cursor.execute("SELECT node_id FROM isolated_nodes")
        iso_set = {r[0] for r in cursor.fetchall()}
        for race in EXPECTED_RACES:
            n1, n2 = race["nodes"]
            assert n1 in iso_set or n2 in iso_set, (
                f"DB isolation set {iso_set} does not cover race ({n1}, {n2})"
            )


# ==================== DOT Visualization Tests ====================

class TestDotVisualization:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/graph.dot"), "graph.dot not found"

    def test_dot_is_digraph(self, dot_content):
        assert "digraph" in dot_content, "DOT file must contain 'digraph'"

    def test_dot_contains_all_nodes(self, dot_content):
        for i in range(15):
            assert f"N{i}" in dot_content, f"DOT file missing node N{i}"

    def test_dot_has_doublecircle_nodes(self, dot_content):
        dc_count = dot_content.count("doublecircle")
        assert dc_count == 8, (
            f"Expected 8 doublecircle nodes (isolation set), got {dc_count}"
        )

    def test_dot_has_circle_nodes(self, dot_content):
        lines = dot_content.split('\n')
        circle_count = 0
        for line in lines:
            stripped = line.strip()
            if 'shape=' in stripped and 'doublecircle' not in stripped and 'circle' in stripped:
                circle_count += 1
        assert circle_count == 7, (
            f"Expected 7 circle (non-isolated) nodes, got {circle_count}"
        )

    def test_dot_continue_edge_count(self, dot_content):
        lines = dot_content.split('\n')
        count = sum(1 for l in lines
                    if '->' in l and ('color=black' in l or 'color="black"' in l))
        assert count == EXPECTED_CONTINUE_EDGES, (
            f"Expected {EXPECTED_CONTINUE_EDGES} black (continue) edges, got {count}"
        )

    def test_dot_spawn_edge_count(self, dot_content):
        lines = dot_content.split('\n')
        count = sum(1 for l in lines
                    if '->' in l and ('color=blue' in l or 'color="blue"' in l))
        assert count == EXPECTED_SPAWN_EDGES, (
            f"Expected {EXPECTED_SPAWN_EDGES} blue (spawn) edges, got {count}"
        )

    def test_dot_future_get_edge_count(self, dot_content):
        lines = dot_content.split('\n')
        count = sum(1 for l in lines
                    if '->' in l and ('color=green' in l or 'color="green"' in l))
        assert count == EXPECTED_FUTURE_GET_EDGES, (
            f"Expected {EXPECTED_FUTURE_GET_EDGES} green (future_get) edges, got {count}"
        )

    def test_dot_finish_join_edge_count(self, dot_content):
        lines = dot_content.split('\n')
        count = sum(1 for l in lines
                    if '->' in l and ('color=red' in l or 'color="red"' in l))
        assert count == EXPECTED_FINISH_JOIN_EDGES, (
            f"Expected {EXPECTED_FINISH_JOIN_EDGES} red (finish-join) edges, got {count}"
        )

    def test_dot_race_edge_count(self, dot_content):
        lines = dot_content.split('\n')
        count = sum(1 for l in lines
                    if '->' in l and ('color=orange' in l or 'color="orange"' in l))
        assert count == EXPECTED_RACE_EDGES, (
            f"Expected {EXPECTED_RACE_EDGES} orange (race) edges, got {count}"
        )

    def test_dot_race_edges_dashed(self, dot_content):
        lines = dot_content.split('\n')
        orange_lines = [l for l in lines
                        if '->' in l and ('color=orange' in l or 'color="orange"' in l)]
        for line in orange_lines:
            assert 'dashed' in line, f"Race edge not dashed: {line.strip()}"

    def test_dot_race_edges_undirected(self, dot_content):
        lines = dot_content.split('\n')
        orange_lines = [l for l in lines
                        if '->' in l and ('color=orange' in l or 'color="orange"' in l)]
        for line in orange_lines:
            assert 'dir=none' in line or 'dir="none"' in line, (
                f"Race edge not undirected: {line.strip()}"
            )


# ==================== SVG Visualization Tests ====================

class TestSvgVisualization:
    def test_svg_file_exists(self):
        assert os.path.exists("/app/graph.svg"), "graph.svg not found"

    def test_svg_is_valid(self):
        with open("/app/graph.svg") as f:
            content = f.read()
        assert "<svg" in content, "graph.svg does not contain <svg tag"

    def test_svg_nontrivial_size(self):
        size = os.path.getsize("/app/graph.svg")
        assert size > 1000, f"graph.svg suspiciously small ({size} bytes)"

    def test_svg_contains_nodes(self):
        with open("/app/graph.svg") as f:
            content = f.read()
        for i in range(15):
            assert f"N{i}" in content, f"SVG missing node N{i}"


# ==================== Cross-Artifact Consistency Tests ====================

class TestArtifactConsistency:
    def test_json_sqlite_hb_match(self, results, db):
        json_hb = _normalize_pair_list(results["happens_before_pairs"])
        cursor = db.cursor()
        cursor.execute("SELECT src, dst FROM happens_before ORDER BY src, dst")
        db_hb = _normalize_pair_list([[r[0], r[1]] for r in cursor.fetchall()])
        assert json_hb == db_hb, "HB pairs differ between JSON and SQLite"

    def test_json_sqlite_mhp_match(self, results, db):
        json_mhp = _normalize_pair_list(results["mhp_pairs"])
        cursor = db.cursor()
        cursor.execute("SELECT node1, node2 FROM mhp_pairs ORDER BY node1, node2")
        db_mhp = _normalize_pair_list([[r[0], r[1]] for r in cursor.fetchall()])
        assert json_mhp == db_mhp, "MHP pairs differ between JSON and SQLite"

    def test_json_sqlite_isolation_match(self, results, db):
        json_iso = sorted(results["isolated_nodes"])
        cursor = db.cursor()
        cursor.execute("SELECT node_id FROM isolated_nodes ORDER BY node_id")
        db_iso = sorted([r[0] for r in cursor.fetchall()])
        assert json_iso == db_iso, (
            f"Isolation sets differ: JSON={json_iso} vs SQLite={db_iso}"
        )

    def test_json_sqlite_metrics_match(self, results, db):
        cursor = db.cursor()
        cursor.execute("SELECT key, value FROM metrics")
        db_metrics = {r[0]: r[1] for r in cursor.fetchall()}
        assert int(db_metrics["work"]) == results["work"], "Work mismatch"
        assert int(db_metrics["span"]) == results["span"], "Span mismatch"
        assert abs(db_metrics["ideal_parallelism"] - results["ideal_parallelism"]) < 0.001, (
            "Ideal parallelism mismatch"
        )
