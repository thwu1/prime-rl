
import pytest
import psycopg2
from datetime import date
from decimal import Decimal


@pytest.fixture(scope="session")
def conn():
    c = psycopg2.connect(dbname="taskdb", user="postgres")
    c.autocommit = True
    yield c
    c.close()


@pytest.fixture
def cur(conn):
    c = conn.cursor()
    yield c
    c.close()


# ---------- Migration tests ----------

class TestMigration:
    def test_allocations_table_exists(self, cur):
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'allocations')"
        )
        assert cur.fetchone()[0], "allocations table must exist"

    def test_allocations_row_count(self, cur):
        cur.execute("SELECT count(*) FROM allocations")
        assert cur.fetchone()[0] == 37

    def test_exclusion_constraint_exists(self, cur):
        cur.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE contype = 'x' AND conrelid = 'allocations'::regclass"
        )
        assert cur.fetchone()[0] >= 1, "GiST exclusion constraint must exist"

    def test_daterange_column_type(self, cur):
        cur.execute(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'allocations' AND column_name = 'validity'"
        )
        row = cur.fetchone()
        assert row is not None, "validity column must exist"
        assert row[0] == "daterange", f"validity must be daterange, got {row[0]}"

    def test_srv001_allocations(self, cur):
        cur.execute(
            "SELECT lower(validity), upper(validity), project_id, daily_cost "
            "FROM allocations WHERE server_id = 'srv-001' "
            "ORDER BY lower(validity)"
        )
        rows = cur.fetchall()
        assert len(rows) == 4
        assert rows[0] == (date(2023, 1, 1), date(2023, 3, 15), 5, Decimal("10.00"))
        assert rows[1] == (date(2023, 3, 15), date(2023, 6, 1), 6, Decimal("8.00"))
        assert rows[2] == (date(2023, 6, 1), date(2023, 9, 1), 5, Decimal("12.00"))
        assert rows[3] == (date(2023, 9, 1), date(2024, 1, 1), 11, Decimal("15.00"))

    def test_last_allocation_upper_bound(self, cur):
        """Every server's last allocation must end on 2024-01-01."""
        cur.execute(
            "SELECT DISTINCT ON (server_id) server_id, upper(validity) "
            "FROM allocations ORDER BY server_id, upper(validity) DESC"
        )
        for server_id, upper_bound in cur.fetchall():
            assert upper_bound == date(2024, 1, 1), (
                f"{server_id} last allocation ends {upper_bound}, expected 2024-01-01"
            )

    def test_no_overlapping_ranges(self, cur):
        """Verify no server has overlapping validity ranges."""
        cur.execute(
            "SELECT a1.server_id, a1.validity, a2.validity "
            "FROM allocations a1 "
            "JOIN allocations a2 ON a1.server_id = a2.server_id "
            "  AND a1.ctid < a2.ctid AND a1.validity && a2.validity"
        )
        overlaps = cur.fetchall()
        assert len(overlaps) == 0, f"Found overlapping ranges: {overlaps}"

    def test_srv010_five_allocations(self, cur):
        cur.execute(
            "SELECT count(*) FROM allocations WHERE server_id = 'srv-010'"
        )
        assert cur.fetchone()[0] == 5


# ---------- Streaks tests ----------

class TestStreaks:
    def test_streak_row_count(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"

    def test_streak_top_result(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        # Row 0: srv-005 with streak of 4 (all non-decreasing: 20->22->25->28)
        assert rows[0][0] == "srv-005"
        assert int(rows[0][1]) == 4
        assert rows[0][2] == date(2023, 1, 1)
        assert rows[0][3] == date(2023, 10, 1)

    def test_streak_second_result(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        # Row 1: srv-001 with streak of 3 (8->12->15 after initial drop)
        assert rows[1][0] == "srv-001"
        assert int(rows[1][1]) == 3
        assert rows[1][2] == date(2023, 3, 15)
        assert rows[1][3] == date(2023, 9, 1)

    def test_streak_third_result(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        # Row 2: srv-003 with streak of 3 (7->10->13 in middle)
        assert rows[2][0] == "srv-003"
        assert int(rows[2][1]) == 3
        assert rows[2][2] == date(2023, 5, 1)
        assert rows[2][3] == date(2023, 10, 1)

    def test_streak_fourth_result(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        # Row 3: srv-009 with streak of 3 (14->18->20)
        assert rows[3][0] == "srv-009"
        assert int(rows[3][1]) == 3
        assert rows[3][2] == date(2023, 6, 1)
        assert rows[3][3] == date(2023, 12, 1)

    def test_streak_fifth_result(self, cur):
        sql = open("/app/queries/streaks.sql").read()
        cur.execute(sql)
        rows = cur.fetchall()
        # Row 4: srv-002 with streak of 2 (8->11, wins tiebreak over others at 2)
        assert rows[4][0] == "srv-002"
        assert int(rows[4][1]) == 2
        assert rows[4][2] == date(2023, 1, 15)
        assert rows[4][3] == date(2023, 7, 1)


# ---------- Project rollup tests ----------

class TestProjectRollup:
    def _get_rows(self, cur):
        sql = open("/app/queries/project_rollup.sql").read()
        cur.execute(sql)
        return cur.fetchall()

    def test_rollup_row_count(self, cur):
        rows = self._get_rows(cur)
        assert len(rows) == 12, f"Expected 12 rows (one per project), got {len(rows)}"

    def test_rollup_total_server_days(self, cur):
        rows = self._get_rows(cur)
        results = {row[0]: row for row in rows}

        expected_totals = {
            "Infrastructure": 1947,
            "Compute": 1036,
            "ML Training": 621,
            "Batch Jobs": 415,
            "Storage": 911,
            "Backups": 668,
            "Archives": 243,
            "Applications": 1509,
            "Web Frontend": 532,
            "API Backend": 977,
            "Auth Service": 534,
            "Data Pipeline": 443,
        }

        for name, expected in expected_totals.items():
            assert name in results, f"Missing project: {name}"
            actual = int(results[name][4])
            assert actual == expected, (
                f"{name}: expected total_server_days={expected}, got {actual}"
            )

    def test_rollup_own_days_internal_nodes(self, cur):
        rows = self._get_rows(cur)
        results = {row[0]: row for row in rows}

        for name in ["Infrastructure", "Compute", "Storage", "Applications", "API Backend"]:
            actual = int(results[name][3])
            assert actual == 0, f"{name} should have 0 own_server_days, got {actual}"

    def test_rollup_own_days_leaf_nodes(self, cur):
        rows = self._get_rows(cur)
        results = {row[0]: row for row in rows}

        expected_own = {
            "ML Training": 621,
            "Batch Jobs": 415,
            "Backups": 668,
            "Archives": 243,
            "Web Frontend": 532,
            "Auth Service": 534,
            "Data Pipeline": 443,
        }
        for name, expected in expected_own.items():
            actual = int(results[name][3])
            assert actual == expected, (
                f"{name}: expected own_server_days={expected}, got {actual}"
            )

    def test_rollup_depths(self, cur):
        rows = self._get_rows(cur)
        results = {row[0]: row for row in rows}

        assert int(results["Infrastructure"][1]) == 0
        assert int(results["Applications"][1]) == 0
        assert int(results["Compute"][1]) == 1
        assert int(results["Storage"][1]) == 1
        assert int(results["Web Frontend"][1]) == 1
        assert int(results["API Backend"][1]) == 1
        assert int(results["ML Training"][1]) == 2
        assert int(results["Auth Service"][1]) == 2

    def test_rollup_paths(self, cur):
        rows = self._get_rows(cur)
        results = {row[0]: row for row in rows}

        assert results["Infrastructure"][2] == "Infrastructure"
        assert results["Compute"][2] == "Infrastructure > Compute"
        assert results["ML Training"][2] == "Infrastructure > Compute > ML Training"
        assert results["Auth Service"][2] == "Applications > API Backend > Auth Service"
        assert results["Web Frontend"][2] == "Applications > Web Frontend"

    def test_rollup_ordering(self, cur):
        rows = self._get_rows(cur)
        paths = [row[2] for row in rows]
        assert paths == sorted(paths), "Results must be ordered by path"


# ---------- Utilization report tests ----------

class TestUtilizationReport:
    def _get_rows(self, cur):
        sql = open("/app/queries/utilization_report.sql").read()
        cur.execute(sql)
        return cur.fetchall()

    def test_utilization_row_count(self, cur):
        rows = self._get_rows(cur)
        # 2 DCs x 4 quarters = 8, + 2 DC subtotals + 4 quarter subtotals + 1 grand = 15
        assert len(rows) == 15, f"Expected 15 rows, got {len(rows)}"

    def test_grouping_sets_dimensions(self, cur):
        rows = self._get_rows(cur)
        combos = set()
        for r in rows:
            combos.add((r[0] is None, r[1] is None))
        expected = {
            (False, False),  # (datacenter, quarter)
            (False, True),   # (datacenter)
            (True, False),   # (quarter)
            (True, True),    # grand total
        }
        assert combos == expected, f"Missing grouping set dimensions: {expected - combos}"

    def test_grand_total_matches_independent_calculation(self, cur):
        rows = self._get_rows(cur)
        grand = [r for r in rows if r[0] is None and r[1] is None]
        assert len(grand) == 1, "Exactly one grand total row"

        # Cross-check: compute grand total independently from allocations
        cur.execute(
            "SELECT SUM((upper(validity) - lower(validity)) * daily_cost)::numeric "
            "FROM allocations"
        )
        expected = cur.fetchone()[0]
        actual = float(grand[0][2])
        assert abs(actual - float(expected)) < 0.01, (
            f"Grand total: expected {expected}, got {actual}"
        )

    def test_datacenter_subtotals_sum_to_grand(self, cur):
        rows = self._get_rows(cur)
        dc_subtotals = [float(r[2]) for r in rows if r[0] is not None and r[1] is None]
        grand = [float(r[2]) for r in rows if r[0] is None and r[1] is None]
        assert len(dc_subtotals) == 2
        assert abs(sum(dc_subtotals) - grand[0]) < 0.01

    def test_quarter_subtotals_sum_to_grand(self, cur):
        rows = self._get_rows(cur)
        q_subtotals = [float(r[2]) for r in rows if r[0] is None and r[1] is not None]
        grand = [float(r[2]) for r in rows if r[0] is None and r[1] is None]
        assert len(q_subtotals) == 4
        assert abs(sum(q_subtotals) - grand[0]) < 0.01

    def test_dc_quarter_cells_sum_to_dc_subtotal(self, cur):
        rows = self._get_rows(cur)
        for dc in ["US-EAST", "EU-WEST"]:
            cells = [float(r[2]) for r in rows if r[0] == dc and r[1] is not None]
            subtotal = [float(r[2]) for r in rows if r[0] == dc and r[1] is None]
            assert len(cells) == 4, f"{dc} should have 4 quarter cells"
            assert len(subtotal) == 1, f"{dc} should have 1 subtotal"
            assert abs(sum(cells) - subtotal[0]) < 0.01, (
                f"{dc} quarter cells sum {sum(cells)} != subtotal {subtotal[0]}"
            )

    def test_specific_cell_cross_check(self, cur):
        """Cross-check one cell against independent SQL computation."""
        rows = self._get_rows(cur)
        cell = [r for r in rows if r[0] == "US-EAST" and r[1] == "Q1 2023"]
        assert len(cell) == 1

        cur.execute(
            "SELECT SUM("
            "  (upper(validity * '[2023-01-01,2023-04-01)'::daterange) "
            "   - lower(validity * '[2023-01-01,2023-04-01)'::daterange))"
            "  * daily_cost"
            ")::numeric "
            "FROM allocations "
            "WHERE datacenter = 'US-EAST' "
            "AND validity && '[2023-01-01,2023-04-01)'::daterange"
        )
        expected = float(cur.fetchone()[0])
        actual = float(cell[0][2])
        assert abs(actual - expected) < 0.01, (
            f"US-EAST Q1 2023: expected {expected}, got {actual}"
        )

    def test_ordering(self, cur):
        rows = self._get_rows(cur)
        # Non-null datacenters should come before null datacenters
        dc_values = [r[0] for r in rows]
        last_non_null = max(
            (i for i, v in enumerate(dc_values) if v is not None), default=-1
        )
        first_null = min(
            (i for i, v in enumerate(dc_values) if v is None), default=len(rows)
        )
        assert last_non_null < first_null, "NULLS LAST for datacenter not respected"

    def test_all_quarters_present(self, cur):
        rows = self._get_rows(cur)
        quarters = {r[1] for r in rows if r[1] is not None}
        expected = {"Q1 2023", "Q2 2023", "Q3 2023", "Q4 2023"}
        assert quarters == expected
