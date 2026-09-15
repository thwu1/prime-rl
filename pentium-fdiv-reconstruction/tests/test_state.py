"""
Tests for the division unit reverse-engineering task.

"""

import json
import importlib.util
import math
import os
import struct
import sqlite3
import sys

import pytest


@pytest.fixture(scope="module")
def divunit():
    """Load the agent's divunit module."""
    spec = importlib.util.spec_from_file_location("divunit", "/app/divunit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def buggy_table(divunit):
    return divunit.load_buggy_table()


@pytest.fixture(scope="module")
def fixed_table(divunit):
    return divunit.load_fixed_table()


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---- SQLite database tests ----

class TestSQLiteDatabase:
    @pytest.fixture(scope="class")
    def db(self):
        conn = sqlite3.connect("/app/tables.db")
        yield conn
        conn.close()

    def test_db_exists(self):
        assert os.path.exists("/app/tables.db"), "tables.db not found"

    def test_buggy_schema(self, db):
        cols = {row[1] for row in db.execute("PRAGMA table_info(buggy)").fetchall()}
        assert {"d_idx", "p_idx", "q"} <= cols

    def test_fixed_schema(self, db):
        cols = {row[1] for row in db.execute("PRAGMA table_info(fixed)").fetchall()}
        assert {"d_idx", "p_idx", "q"} <= cols

    def test_diffs_schema(self, db):
        cols = {row[1] for row in db.execute("PRAGMA table_info(diffs)").fetchall()}
        assert {"d_idx", "p_idx", "buggy_q", "fixed_q"} <= cols

    def test_buggy_table_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM buggy").fetchone()[0]
        assert count == 2048

    def test_fixed_table_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM fixed").fetchone()[0]
        assert count == 2048

    def test_diffs_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM diffs").fetchone()[0]
        assert count == 32

    def test_d_idx_range_buggy(self, db):
        mn = db.execute("SELECT MIN(d_idx) FROM buggy").fetchone()[0]
        mx = db.execute("SELECT MAX(d_idx) FROM buggy").fetchone()[0]
        assert mn == 0 and mx == 15

    def test_p_idx_range_buggy(self, db):
        mn = db.execute("SELECT MIN(p_idx) FROM buggy").fetchone()[0]
        mx = db.execute("SELECT MAX(p_idx) FROM buggy").fetchone()[0]
        assert mn == -64 and mx == 63

    def test_spot_check_buggy_db(self, db):
        """Defective ROM should have q=0 at (0,21)."""
        q = db.execute("SELECT q FROM buggy WHERE d_idx=0 AND p_idx=21").fetchone()[0]
        assert q == 0

    def test_spot_check_fixed_db(self, db):
        """Corrected PLA should have q=2 at (0,21)."""
        q = db.execute("SELECT q FROM fixed WHERE d_idx=0 AND p_idx=21").fetchone()[0]
        assert q == 2

    def test_diffs_consistency_with_tables(self, db):
        """Every diff entry must correspond to an actual disagreement."""
        rows = db.execute("""
            SELECT d.d_idx, d.p_idx FROM diffs d
            JOIN buggy b ON d.d_idx=b.d_idx AND d.p_idx=b.p_idx
            JOIN fixed f ON d.d_idx=f.d_idx AND d.p_idx=f.p_idx
            WHERE b.q = f.q
        """).fetchall()
        assert len(rows) == 0, "Diffs table contains entries where tables actually agree"

    def test_diffs_complete(self, db):
        """All actual disagreements must appear in diffs."""
        actual = db.execute("""
            SELECT COUNT(*) FROM buggy b
            JOIN fixed f ON b.d_idx=f.d_idx AND b.p_idx=f.p_idx
            WHERE b.q != f.q
        """).fetchone()[0]
        recorded = db.execute("SELECT COUNT(*) FROM diffs").fetchone()[0]
        assert actual == recorded

    def test_diffs_buggy_q_matches(self, db):
        """buggy_q in diffs must match actual buggy table."""
        mismatches = db.execute("""
            SELECT COUNT(*) FROM diffs d
            JOIN buggy b ON d.d_idx=b.d_idx AND d.p_idx=b.p_idx
            WHERE d.buggy_q != b.q
        """).fetchone()[0]
        assert mismatches == 0

    def test_diffs_fixed_q_matches(self, db):
        """fixed_q in diffs must match actual fixed table."""
        mismatches = db.execute("""
            SELECT COUNT(*) FROM diffs d
            JOIN fixed f ON d.d_idx=f.d_idx AND d.p_idx=f.p_idx
            WHERE d.fixed_q != f.q
        """).fetchone()[0]
        assert mismatches == 0


# ---- Visualization tests ----

class TestVisualization:
    def test_png_exists(self):
        assert os.path.exists("/app/table_map.png"), "table_map.png not found"

    def test_png_valid_header(self):
        with open("/app/table_map.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "File is not a valid PNG"

    def test_png_dimensions(self):
        with open("/app/table_map.png", "rb") as f:
            data = f.read(24)
        width = struct.unpack(">I", data[16:20])[0]
        height = struct.unpack(">I", data[20:24])[0]
        assert width >= 800, f"PNG width {width} < 800"
        assert height >= 600, f"PNG height {height} < 600"

    def test_png_nontrivial(self):
        size = os.path.getsize("/app/table_map.png")
        assert size > 5000, f"PNG too small ({size} bytes), expected substantive image"


# ---- Table loading tests ----

class TestTableLoading:
    def test_buggy_table_size(self, buggy_table):
        """Buggy table must have exactly 2048 entries."""
        assert len(buggy_table) == 2048

    def test_fixed_table_size(self, fixed_table):
        """Fixed table must have exactly 2048 entries."""
        assert len(fixed_table) == 2048

    def test_table_index_range(self, buggy_table):
        """Table keys must span d_idx 0-15, p_idx -64 to 63."""
        d_indices = set()
        p_indices = set()
        for (d, p) in buggy_table.keys():
            d_indices.add(d)
            p_indices.add(p)
        assert d_indices == set(range(16))
        assert p_indices == set(range(-64, 64))

    def test_buggy_values_valid(self, buggy_table):
        for v in buggy_table.values():
            assert v in {-2, -1, 0, 1, 2}

    def test_fixed_values_valid(self, fixed_table):
        for v in fixed_table.values():
            assert v in {-2, -1, 0, 1, 2}


# ---- Spot-check specific table entries ----

class TestBuggyTableEntries:
    """Verify specific entries in the buggy table (parsed from binary ROM)."""

    @pytest.mark.parametrize("d_idx,p_idx,expected_q", [
        (0, 0, 0),
        (0, 3, 1),
        (0, 10, 1),
        (0, 21, 0),     # BUGGY: should be 2 but is 0
        (7, 4, 1),
        (7, 30, 0),     # BUGGY: should be 2 but is 0
        (8, 20, 2),
        (8, 32, 0),     # BUGGY: should be 2 but is 0
        (15, 41, 0),    # BUGGY: should be 2 but is 0
        (0, -5, -1),
        (0, -3, 0),
        (0, -21, 0),    # BUGGY: should be -2 but is 0
        (7, -30, 0),    # BUGGY: should be -2 but is 0
    ])
    def test_buggy_entry(self, buggy_table, d_idx, p_idx, expected_q):
        assert buggy_table[(d_idx, p_idx)] == expected_q


class TestFixedTableEntries:
    """Verify specific entries in the fixed table (reconstructed from PLA)."""

    @pytest.mark.parametrize("d_idx,p_idx,expected_q", [
        (0, 0, 0),
        (0, 3, 1),
        (0, 10, 1),
        (0, 21, 2),     # FIXED: correctly has 2
        (0, 22, 0),     # Above valid range
        (7, 2, 0),
        (7, 4, 1),
        (7, 16, 2),
        (7, 30, 2),     # FIXED
        (8, 0, 0),
        (8, 5, 1),
        (8, 20, 2),
        (8, 32, 2),     # FIXED
        (8, 33, 0),     # Above valid range
        (15, 41, 2),    # FIXED
        (15, 42, 0),    # Above valid range
        (0, -5, -1),
        (0, -3, 0),
        (0, -21, -2),   # FIXED
        (7, -5, -1),
        (7, -3, 0),
        (7, -30, -2),   # FIXED
    ])
    def test_fixed_entry(self, fixed_table, d_idx, p_idx, expected_q):
        assert fixed_table[(d_idx, p_idx)] == expected_q


# ---- Difference analysis tests ----

class TestDifferences:
    EXPECTED_POS_DIFFS = [
        (0, 21), (1, 22), (2, 24), (3, 25), (4, 26),
        (5, 28), (6, 29), (7, 30), (8, 32), (9, 33),
        (10, 34), (11, 36), (12, 37), (13, 38), (14, 40), (15, 41),
    ]

    def test_difference_count(self, divunit, buggy_table, fixed_table):
        """Must find exactly 32 differing entries."""
        diffs = divunit.find_differences(buggy_table, fixed_table)
        assert len(diffs) == 32

    def test_positive_differences(self, divunit, buggy_table, fixed_table):
        """The 16 positive-side differences must be at expected positions."""
        diffs = divunit.find_differences(buggy_table, fixed_table)
        pos_diffs = sorted([(d, p) for d, p in diffs if p > 0])
        assert pos_diffs == self.EXPECTED_POS_DIFFS

    def test_negative_symmetry(self, divunit, buggy_table, fixed_table):
        """The 16 negative-side differences must mirror the positive ones."""
        diffs = divunit.find_differences(buggy_table, fixed_table)
        neg_diffs = sorted([(d, p) for d, p in diffs if p < 0])
        neg_as_pos = sorted([(d, -p) for d, p in neg_diffs])
        assert neg_as_pos == self.EXPECTED_POS_DIFFS

    def test_buggy_has_zero_at_diffs(self, buggy_table):
        """In the buggy table, all positive diff positions have q=0."""
        for d_idx, p_idx in self.EXPECTED_POS_DIFFS:
            assert buggy_table[(d_idx, p_idx)] == 0

    def test_fixed_has_two_at_diffs(self, fixed_table):
        """In the fixed table, all positive diff positions have q=2."""
        for d_idx, p_idx in self.EXPECTED_POS_DIFFS:
            assert fixed_table[(d_idx, p_idx)] == 2


# ---- Division simulator tests ----

class TestDivision:
    @pytest.mark.parametrize("a,d,expected", [
        (1.5, 1.25, 1.2),
        (1.0, 1.0, 1.0),
        (1.8, 1.2, 1.5),
        (1.5, 1.0, 1.5),
        (1.75, 1.5, 7.0 / 6.0),
    ])
    def test_division_correctness(self, divunit, fixed_table, a, d, expected):
        """Division with fixed table must match expected result."""
        result = divunit.divide(a, d, fixed_table, num_steps=34)
        assert abs(result - expected) < 1e-10, (
            f"divide({a}, {d}) = {result}, expected {expected}"
        )

    def test_division_near_2(self, divunit, fixed_table):
        result = divunit.divide(1.999, 1.001, fixed_table, num_steps=34)
        expected = 1.999 / 1.001
        assert abs(result - expected) < 1e-10

    def test_division_less_than_1(self, divunit, fixed_table):
        result = divunit.divide(1.1, 1.9, fixed_table, num_steps=34)
        expected = 1.1 / 1.9
        assert abs(result - expected) < 1e-10

    def test_division_equal(self, divunit, fixed_table):
        result = divunit.divide(1.5, 1.5, fixed_table, num_steps=34)
        assert abs(result - 1.0) < 1e-10


# ---- Table consistency tests ----

class TestTableConsistency:
    def test_fixed_table_no_q2_above_bound(self, fixed_table):
        """No cell above 8d/3 should have q=2 in the fixed table."""
        from fractions import Fraction
        for d_idx in range(16):
            d = Fraction(1) + Fraction(d_idx, 16)
            upper = Fraction(8, 3) * d
            for p_idx in range(-64, 64):
                p = Fraction(p_idx, 8)
                if p > upper:
                    assert fixed_table[(d_idx, p_idx)] == 0, (
                        f"Cell ({d_idx},{p_idx}) above 8d/3 should be unused"
                    )

    def test_fixed_table_q2_coverage(self, fixed_table):
        """All cells at p >= (4/3)*d and p <= (8/3)*d must be q=+2."""
        from fractions import Fraction
        for d_idx in range(16):
            d = Fraction(1) + Fraction(d_idx, 16)
            lower = Fraction(4, 3) * d
            upper = Fraction(8, 3) * d
            for p_idx in range(0, 64):
                p = Fraction(p_idx, 8)
                if lower <= p <= upper:
                    assert fixed_table[(d_idx, p_idx)] == 2, (
                        f"Cell ({d_idx},{p_idx}) in q=2 range should be 2"
                    )

    def test_buggy_table_has_holes_in_q2(self, buggy_table):
        """The buggy table must have holes in the q=2 region."""
        from fractions import Fraction
        holes = 0
        for d_idx in range(16):
            d = Fraction(1) + Fraction(d_idx, 16)
            lower = Fraction(4, 3) * d
            upper = Fraction(8, 3) * d
            for p_idx in range(0, 64):
                p = Fraction(p_idx, 8)
                if lower <= p <= upper and buggy_table[(d_idx, p_idx)] == 0:
                    holes += 1
        assert holes == 16, f"Expected 16 holes in positive q=2 region, got {holes}"


# ---- Results file tests ----

class TestResultsFile:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json")

    def test_num_differences(self, results):
        assert results["num_differences"] == 32

    def test_differences_list_length(self, results):
        assert len(results["differences"]) == 32

    def test_differences_sorted(self, results):
        diffs = results["differences"]
        keys = [(d[0], d[1]) for d in diffs]
        assert keys == sorted(keys)

    def test_bug_demonstrations(self, results):
        """Must have at least 3 demonstrations."""
        demos = results["bug_demonstrations"]
        assert len(demos) >= 3
        for demo in demos:
            assert demo["buggy_q"] != demo["correct_q"], \
                "Bug demonstration must show different quotient digits"
            assert abs(demo["buggy_next_w"]) > abs(demo["correct_next_w"]), \
                "Buggy next partial remainder should be larger in magnitude"

    def test_division_validation(self, results):
        """Must have at least 5 validated divisions."""
        vals = results["division_validation"]
        assert len(vals) >= 5
        for v in vals:
            expected = v["a"] / v["d"]
            assert abs(v["quotient"] - expected) < 1e-8, (
                f"Division {v['a']}/{v['d']}: got {v['quotient']}, expected {expected}"
            )

    def test_table_stats(self, results):
        stats = results["table_stats"]
        assert stats["total"] == 2048
        total = (stats["q_plus2"] + stats["q_plus1"] + stats["q_zero"]
                 + stats["q_minus1"] + stats["q_minus2"])
        assert total == 2048

    def test_table_stats_symmetry(self, results):
        stats = results["table_stats"]
        assert stats["q_plus1"] == stats["q_minus1"]

    def test_bug_pattern_substantive(self, results):
        """Bug pattern description must be substantive."""
        bp = results["bug_pattern"]
        assert isinstance(bp, str)
        assert len(bp) > 50, "Bug pattern description should be substantive"
