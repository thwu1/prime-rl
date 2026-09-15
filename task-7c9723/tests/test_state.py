#!/usr/bin/env python3
"""

Verification tests for Wormhole NoC DRAM Placement & Routing Analyzer.
Validates placement correctness, congestion freedom, optimality bounds,
link utilization analysis, SQLite database integrity, and Graphviz outputs.
"""

import json
import os
import sqlite3
import pytest

RESULTS_PATH = "/app/results.json"
CONFIG_PATH = "/app/chip_config.json"
DB_PATH = "/app/noc_analysis.db"
VIZ_DIR = "/app/viz"

# Verified optimal total hop counts for each scenario
EXPECTED_MAX_HOPS = {
    "no_harvest": 12,
    "single_harvest": 13,
    "double_harvest": 14,
    "triple_harvest": 15,
    "adjacent_harvest": 18,
    "heavy_harvest": 30,
}

SCENARIO_NAMES = list(EXPECTED_MAX_HOPS.keys())


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_return_path_links(bank_x, bank_y, reader_x, reader_y, noc):
    """Independently compute the set of directional links in a return path."""
    links = set()
    if noc == 0:
        for x in range(bank_x, reader_x):
            links.add(("E", x, bank_y, x + 1, bank_y))
        for y in range(bank_y, reader_y):
            links.add(("S", reader_x, y, reader_x, y + 1))
    elif noc == 1:
        for x in range(bank_x, reader_x, -1):
            links.add(("W", x, bank_y, x - 1, bank_y))
        for y in range(bank_y, reader_y, -1):
            links.add(("N", reader_x, y, reader_x, y - 1))
    return links


@pytest.fixture(scope="module")
def config():
    return load_json(CONFIG_PATH)


@pytest.fixture(scope="module")
def results():
    return load_json(RESULTS_PATH)


@pytest.fixture(scope="module")
def banks(config):
    return {b["id"]: b for b in config["grid"]["dram_banks"]}


@pytest.fixture(scope="module")
def grid(config):
    return config["grid"]


@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def get_scenario_cfg(config, name):
    for s in config["scenarios"]:
        if s["name"] == name:
            return s
    return None


# ============================================================
# Results JSON — File Integrity
# ============================================================

class TestResultsFileIntegrity:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"

    def test_results_valid_json(self, results):
        assert "scenarios" in results, "Missing 'scenarios' key in results"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_scenario_present(self, results, scenario_name):
        assert scenario_name in results["scenarios"], \
            f"Missing scenario: {scenario_name}"


# ============================================================
# Results JSON — Placement Validity
# ============================================================

class TestPlacementValidity:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_all_12_banks_placed(self, results, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        placed_ids = sorted(int(k) for k in placements.keys())
        assert placed_ids == list(range(12)), \
            f"Expected bank IDs 0-11, got {placed_ids}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_readers_on_valid_worker_tiles(self, results, config, grid, scenario_name):
        scenario_cfg = get_scenario_cfg(config, scenario_name)
        harvested = set(scenario_cfg["harvested_rows"])
        placements = results["scenarios"][scenario_name]["placements"]
        wx_lo, wx_hi = grid["worker_x_range"]
        wy_lo, wy_hi = grid["worker_y_range"]

        for bid_str, p in placements.items():
            assert wx_lo <= p["x"] <= wx_hi, \
                f"Bank {bid_str}: x={p['x']} outside worker columns [{wx_lo},{wx_hi}]"
            assert wy_lo <= p["y"] <= wy_hi, \
                f"Bank {bid_str}: y={p['y']} outside worker rows [{wy_lo},{wy_hi}]"
            assert p["y"] not in harvested, \
                f"Bank {bid_str}: reader placed on harvested row {p['y']}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_no_duplicate_positions(self, results, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        positions = [(p["x"], p["y"]) for p in placements.values()]
        assert len(positions) == len(set(positions)), \
            "Duplicate reader positions detected"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_correct_noc_assignment(self, results, banks, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        for bid_str, p in placements.items():
            bid = int(bid_str)
            bank = banks[bid]
            expected_noc = 0 if bank["x"] == 0 else 1
            assert p["noc"] == expected_noc, \
                f"Bank {bid} at x={bank['x']} should use NoC {expected_noc}, got {p['noc']}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_routing_direction_valid(self, results, banks, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        for bid_str, p in placements.items():
            bid = int(bid_str)
            bank = banks[bid]
            if p["noc"] == 0:
                assert p["y"] >= bank["y"], \
                    f"Bank {bid}: NoC 0 requires reader_y({p['y']}) >= bank_y({bank['y']})"
            else:
                assert p["y"] <= bank["y"], \
                    f"Bank {bid}: NoC 1 requires reader_y({p['y']}) <= bank_y({bank['y']})"


# ============================================================
# Results JSON — Hop Counts
# ============================================================

class TestHopCounts:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_individual_hop_counts(self, results, banks, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        for bid_str, p in placements.items():
            bid = int(bid_str)
            bank = banks[bid]
            expected = abs(p["x"] - bank["x"]) + abs(p["y"] - bank["y"])
            assert p["hops"] == expected, \
                f"Bank {bid}: hops={p['hops']} but Manhattan distance is {expected}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_total_hops_consistent(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        computed = sum(p["hops"] for p in result["placements"].values())
        assert result["total_hops"] == computed, \
            f"total_hops={result['total_hops']} != sum of individual hops={computed}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_total_hops_within_optimal(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        expected_max = EXPECTED_MAX_HOPS[scenario_name]
        assert result["total_hops"] <= expected_max, \
            f"total_hops={result['total_hops']} exceeds optimal bound {expected_max}"


# ============================================================
# Results JSON — Congestion Freedom
# ============================================================

class TestCongestionFreedom:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_no_return_path_link_conflicts(self, results, banks, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        noc0_links = set()
        noc1_links = set()

        for bid in range(12):
            bid_str = str(bid)
            p = placements[bid_str]
            bank = banks[bid]
            links = compute_return_path_links(
                bank["x"], bank["y"], p["x"], p["y"], p["noc"]
            )
            if p["noc"] == 0:
                overlap = links & noc0_links
                assert not overlap, \
                    f"NoC 0 link conflict involving bank {bid}: shared links {overlap}"
                noc0_links |= links
            else:
                overlap = links & noc1_links
                assert not overlap, \
                    f"NoC 1 link conflict involving bank {bid}: shared links {overlap}"
                noc1_links |= links

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_congestion_free_flag_true(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        assert result["congestion_free"] is True, \
            "congestion_free must be True for a valid solution"


# ============================================================
# Results JSON — Bandwidth Estimation
# ============================================================

class TestBandwidthEstimation:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_theoretical_bandwidth(self, results, grid, scenario_name):
        bw = results["scenarios"][scenario_name]["bandwidth"]
        expected = 12 * grid["dram_bank_bandwidth_gbps"]
        assert abs(bw["theoretical_gbps"] - expected) < 0.01, \
            f"theoretical_gbps={bw['theoretical_gbps']} expected {expected}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_utilization_factor(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        bw = result["bandwidth"]
        total_extra = sum(
            max(0, p["hops"] - 1) for p in result["placements"].values()
        )
        expected_util = 1.0 - 0.005 * total_extra
        assert abs(bw["utilization_factor"] - expected_util) < 0.001, \
            f"utilization_factor={bw['utilization_factor']} expected {expected_util}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_estimated_bandwidth(self, results, scenario_name):
        bw = results["scenarios"][scenario_name]["bandwidth"]
        expected = round(bw["theoretical_gbps"] * bw["utilization_factor"], 2)
        assert abs(bw["estimated_gbps"] - expected) < 0.1, \
            f"estimated_gbps={bw['estimated_gbps']} expected {expected}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_bandwidth_sane_range(self, results, scenario_name):
        bw = results["scenarios"][scenario_name]["bandwidth"]
        assert bw["estimated_gbps"] > 200, "Bandwidth unreasonably low"
        assert bw["utilization_factor"] > 0.5, "Utilization unreasonably low"
        assert bw["utilization_factor"] <= 1.0, "Utilization exceeds 1.0"


# ============================================================
# Results JSON — Link Analysis
# ============================================================

class TestLinkAnalysis:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_link_analysis_present(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        assert "link_analysis" in result, "Missing link_analysis in results"
        la = result["link_analysis"]
        for key in ["total_links_used", "max_link_load", "noc0_links_used", "noc1_links_used"]:
            assert key in la, f"Missing {key} in link_analysis"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_max_link_load_is_one(self, results, scenario_name):
        la = results["scenarios"][scenario_name]["link_analysis"]
        assert la["max_link_load"] == 1, \
            f"max_link_load={la['max_link_load']}, expected 1 for congestion-free"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_total_links_equals_hops(self, results, scenario_name):
        result = results["scenarios"][scenario_name]
        assert result["link_analysis"]["total_links_used"] == result["total_hops"], \
            "For congestion-free placement, total_links_used must equal total_hops"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_noc_link_split_sums(self, results, scenario_name):
        la = results["scenarios"][scenario_name]["link_analysis"]
        assert la["noc0_links_used"] + la["noc1_links_used"] == la["total_links_used"], \
            "NoC 0 + NoC 1 link counts must equal total"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_link_counts_match_independent_computation(self, results, banks, scenario_name):
        placements = results["scenarios"][scenario_name]["placements"]
        noc0_set = set()
        noc1_set = set()
        for bid in range(12):
            p = placements[str(bid)]
            bank = banks[bid]
            links = compute_return_path_links(
                bank["x"], bank["y"], p["x"], p["y"], p["noc"]
            )
            if p["noc"] == 0:
                noc0_set |= links
            else:
                noc1_set |= links
        la = results["scenarios"][scenario_name]["link_analysis"]
        assert la["noc0_links_used"] == len(noc0_set), \
            f"NoC 0 links: reported {la['noc0_links_used']} vs computed {len(noc0_set)}"
        assert la["noc1_links_used"] == len(noc1_set), \
            f"NoC 1 links: reported {la['noc1_links_used']} vs computed {len(noc1_set)}"


# ============================================================
# SQLite Database — Existence and Schema
# ============================================================

class TestDatabaseExists:
    def test_db_file_exists(self):
        assert os.path.exists(DB_PATH), f"{DB_PATH} not found"

    def test_db_is_sqlite(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()


class TestDatabaseSchema:
    def test_placements_table_rows(self, db):
        cur = db.execute("SELECT count(*) FROM placements")
        count = cur.fetchone()[0]
        expected = 12 * len(SCENARIO_NAMES)
        assert count == expected, \
            f"placements table has {count} rows, expected {expected}"

    def test_scenario_summary_rows(self, db):
        cur = db.execute("SELECT count(*) FROM scenario_summary")
        count = cur.fetchone()[0]
        assert count == len(SCENARIO_NAMES), \
            f"scenario_summary has {count} rows, expected {len(SCENARIO_NAMES)}"

    def test_link_utilization_populated(self, db):
        cur = db.execute("SELECT count(*) FROM link_utilization")
        count = cur.fetchone()[0]
        assert count > 0, "link_utilization table is empty"

    def test_return_path_links_populated(self, db):
        cur = db.execute("SELECT count(*) FROM return_path_links")
        count = cur.fetchone()[0]
        assert count > 0, "return_path_links table is empty"


# ============================================================
# SQLite Database — Data Integrity
# ============================================================

class TestDatabaseContent:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_db_max_link_load_is_one(self, db, scenario_name):
        cur = db.execute(
            "SELECT max(path_count) FROM link_utilization WHERE scenario=?",
            (scenario_name,)
        )
        row = cur.fetchone()
        assert row is not None and row[0] == 1, \
            f"max link load in DB for {scenario_name} is {row[0] if row else 'NULL'}, expected 1"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_db_summary_matches_json(self, db, results, scenario_name):
        cur = db.execute(
            "SELECT total_hops, congestion_free, total_links_used FROM scenario_summary WHERE scenario=?",
            (scenario_name,)
        )
        row = cur.fetchone()
        assert row is not None, f"No summary row for {scenario_name}"
        json_result = results["scenarios"][scenario_name]
        assert row[0] == json_result["total_hops"], \
            f"DB total_hops={row[0]} != JSON total_hops={json_result['total_hops']}"
        assert row[1] == 1, f"DB congestion_free={row[1]}, expected 1"
        assert row[2] == json_result["link_analysis"]["total_links_used"], \
            f"DB total_links_used={row[2]} != JSON {json_result['link_analysis']['total_links_used']}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_db_placements_match_json(self, db, results, scenario_name):
        cur = db.execute(
            "SELECT bank_id, reader_x, reader_y, noc, hops FROM placements WHERE scenario=? ORDER BY bank_id",
            (scenario_name,)
        )
        rows = cur.fetchall()
        json_placements = results["scenarios"][scenario_name]["placements"]
        assert len(rows) == 12, f"Expected 12 placement rows, got {len(rows)}"
        for row in rows:
            bid_str = str(row[0])
            jp = json_placements[bid_str]
            assert row[1] == jp["x"] and row[2] == jp["y"], \
                f"Bank {bid_str} position mismatch: DB=({row[1]},{row[2]}) JSON=({jp['x']},{jp['y']})"
            assert row[3] == jp["noc"], f"Bank {bid_str} NoC mismatch"
            assert row[4] == jp["hops"], f"Bank {bid_str} hops mismatch"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_db_link_count_per_bank(self, db, banks, scenario_name):
        """Each bank's return path link count in DB should equal its hop count."""
        cur = db.execute(
            "SELECT bank_id, count(*) FROM return_path_links WHERE scenario=? GROUP BY bank_id",
            (scenario_name,)
        )
        link_counts = {row[0]: row[1] for row in cur.fetchall()}
        cur2 = db.execute(
            "SELECT bank_id, hops FROM placements WHERE scenario=?",
            (scenario_name,)
        )
        for row in cur2.fetchall():
            bid, hops = row[0], row[1]
            assert bid in link_counts, f"Bank {bid} has no return_path_links entries"
            assert link_counts[bid] == hops, \
                f"Bank {bid}: {link_counts[bid]} links in DB but {hops} hops"


# ============================================================
# Graphviz Visualization — DOT and SVG Files
# ============================================================

class TestVisualizationFiles:
    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_dot_file_exists(self, scenario_name):
        dot_path = os.path.join(VIZ_DIR, f"{scenario_name}.dot")
        assert os.path.exists(dot_path), f"Missing {dot_path}"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_svg_file_exists(self, scenario_name):
        svg_path = os.path.join(VIZ_DIR, f"{scenario_name}.svg")
        assert os.path.exists(svg_path), f"Missing {svg_path}"
        assert os.path.getsize(svg_path) > 100, "SVG file too small"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_dot_has_digraph(self, scenario_name):
        dot_path = os.path.join(VIZ_DIR, f"{scenario_name}.dot")
        with open(dot_path) as f:
            content = f.read()
        assert "digraph" in content, "DOT file missing 'digraph' declaration"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_dot_has_positioned_nodes(self, scenario_name):
        dot_path = os.path.join(VIZ_DIR, f"{scenario_name}.dot")
        with open(dot_path) as f:
            content = f.read()
        pos_count = content.count("pos=")
        assert pos_count >= 100, \
            f"DOT file has only {pos_count} positioned nodes, expected >=100 (10x12 grid)"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_dot_has_edges(self, scenario_name):
        dot_path = os.path.join(VIZ_DIR, f"{scenario_name}.dot")
        with open(dot_path) as f:
            content = f.read()
        assert "->" in content, "DOT file has no directed edges"

    @pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
    def test_svg_valid_content(self, scenario_name):
        svg_path = os.path.join(VIZ_DIR, f"{scenario_name}.svg")
        with open(svg_path) as f:
            content = f.read()
        assert "<svg" in content, "SVG file missing <svg> tag"


# ============================================================
# Specific Scenario Structural Tests
# ============================================================

class TestNoHarvestBaseline:
    """With no harvesting, every reader should be at the ideal 1-hop position."""

    def test_all_ideal_positions(self, results, banks):
        placements = results["scenarios"]["no_harvest"]["placements"]
        for bid in range(12):
            p = placements[str(bid)]
            bank = banks[bid]
            assert p["hops"] == 1, \
                f"Bank {bid}: expected 1 hop in no_harvest, got {p['hops']}"
            if bank["x"] == 0:
                assert p["x"] == 1 and p["y"] == bank["y"], \
                    f"Bank {bid}: expected ideal (1, {bank['y']})"
            else:
                assert p["x"] == 8 and p["y"] == bank["y"], \
                    f"Bank {bid}: expected ideal (8, {bank['y']})"

    def test_full_bandwidth(self, results):
        bw = results["scenarios"]["no_harvest"]["bandwidth"]
        assert abs(bw["utilization_factor"] - 1.0) < 0.001
        assert abs(bw["estimated_gbps"] - 288.0) < 0.01

    def test_link_counts_minimal(self, results):
        la = results["scenarios"]["no_harvest"]["link_analysis"]
        assert la["total_links_used"] == 12
        assert la["noc0_links_used"] == 6
        assert la["noc1_links_used"] == 6


class TestHeavyHarvestStructure:
    """With 5 harvested rows [0,2,3,4,5], right banks 6,7,8 must all go to row 1."""

    def test_right_displaced_banks_on_row_1(self, results):
        placements = results["scenarios"]["heavy_harvest"]["placements"]
        for bid in [7, 8]:
            p = placements[str(bid)]
            assert p["y"] == 1, \
                f"Bank {bid} in heavy_harvest must use row 1 (only non-harvested row <= bank_y), got row {p['y']}"

    def test_heavy_harvest_bandwidth_degraded(self, results):
        bw = results["scenarios"]["heavy_harvest"]["bandwidth"]
        assert bw["utilization_factor"] < 0.96, \
            "heavy_harvest should have significant bandwidth degradation"
        assert bw["estimated_gbps"] < 280, \
            "heavy_harvest bandwidth should be noticeably below theoretical max"
