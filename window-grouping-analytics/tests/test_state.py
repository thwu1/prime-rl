"""Tests for the six SQL analytics queries and the two utility functions."""

import datetime
import psycopg2
import pytest

DB_NAME = "analytics_db"


@pytest.fixture(scope="session")
def db_conn():
    conn = psycopg2.connect(dbname=DB_NAME, user="postgres")
    conn.set_session(autocommit=True)
    yield conn
    conn.close()


def run_query_file(conn, filepath):
    with open(filepath) as f:
        sql = f.read()
    cur = conn.cursor()
    cur.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    cur.close()
    return columns, [dict(zip(columns, row)) for row in rows]


# -- sorted_unique_array function ---------------------------------------------


class TestFunction:
    def test_deduplicates(self, db_conn):
        """Function must return unique elements only."""
        cur = db_conn.cursor()
        cur.execute("SELECT sorted_unique_array(ARRAY['c','a','b','a','c','b'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == ["a", "b", "c"], (
            f"sorted_unique_array must deduplicate: expected ['a','b','c'], got {result}"
        )

    def test_all_same(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT sorted_unique_array(ARRAY['x','x','x'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == ["x"]

    def test_sorts(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT sorted_unique_array(ARRAY['z','a','m'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == ["a", "m", "z"]


# -- array_intersect function -------------------------------------------------


class TestArrayIntersect:
    def test_overlap(self, db_conn):
        """Must return only elements present in both arrays."""
        cur = db_conn.cursor()
        cur.execute("SELECT array_intersect(ARRAY['a','b','c'], ARRAY['b','c','d'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == ["b", "c"], (
            f"array_intersect must return intersection: expected ['b','c'], got {result}"
        )

    def test_no_overlap(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT array_intersect(ARRAY['a','b'], ARRAY['c','d'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == [], (
            f"array_intersect with no overlap must return empty array, got {result}"
        )

    def test_null_input(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT array_intersect(NULL::TEXT[], ARRAY['a','b'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result is None

    def test_empty_input(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT array_intersect('{}'::TEXT[], ARRAY['a','b'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == []

    def test_identical(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("SELECT array_intersect(ARRAY['x','y','z'], ARRAY['x','y','z'])")
        result = cur.fetchone()[0]
        cur.close()
        assert result == ["x", "y", "z"]


# -- Q1: Hierarchy CUBE Report ------------------------------------------------


class TestQ1HierarchyCube:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q1_hierarchy_cube.sql")
        return results

    def test_row_count(self, db_conn):
        results = self._results(db_conn)
        assert len(results) == 13, (
            f"Expected 13 rows (5 detail + 4 region + 3 dept + 1 grand), got {len(results)}"
        )

    def test_report_level_counts(self, db_conn):
        results = self._results(db_conn)
        levels = [r["report_level"] for r in results]
        assert levels.count("detail") == 5
        assert levels.count("region_total") == 4
        assert levels.count("dept_total") == 3
        assert levels.count("grand_total") == 1

    def test_data_null_region_is_detail(self, db_conn):
        """Employee 105 has NULL region. Her transactions must be classified as
        'detail' with region_display='Unknown', not misidentified as subtotals."""
        results = self._results(db_conn)
        unknown_details = [
            r for r in results
            if r["report_level"] == "detail" and r["region_display"] == "Unknown"
        ]
        assert len(unknown_details) == 1, (
            f"Expected 1 detail row with region_display='Unknown' (NULL region, Marketing), "
            f"got {len(unknown_details)}"
        )
        assert float(unknown_details[0]["total_amount"]) == pytest.approx(2950.0)
        assert unknown_details[0]["txn_count"] == 3

    def test_uses_root_department(self, db_conn):
        """Must use root-level department names (Engineering, Sales, Marketing),
        not sub-departments (Backend, Frontend, Enterprise, SMB, Digital, Events)."""
        results = self._results(db_conn)
        all_depts = {r["department_display"] for r in results}
        sub_depts = {"Backend", "Frontend", "Enterprise", "SMB", "Digital", "Events"}
        found_sub = all_depts & sub_depts
        assert not found_sub, (
            f"Found sub-department names {found_sub}. Must resolve to root-level departments."
        )

    def test_dept_totals_show_all_regions(self, db_conn):
        results = self._results(db_conn)
        dept_totals = [r for r in results if r["report_level"] == "dept_total"]
        assert len(dept_totals) == 3
        for r in dept_totals:
            assert r["region_display"] == "All Regions"

    def test_region_totals_show_all_departments(self, db_conn):
        results = self._results(db_conn)
        region_totals = [r for r in results if r["report_level"] == "region_total"]
        assert len(region_totals) == 4
        for r in region_totals:
            assert r["department_display"] == "All Departments"

    def test_grand_total_values(self, db_conn):
        results = self._results(db_conn)
        grand = [r for r in results if r["report_level"] == "grand_total"]
        assert len(grand) == 1
        g = grand[0]
        assert float(g["total_amount"]) == pytest.approx(56250.0)
        assert g["txn_count"] == 25
        assert g["region_display"] == "All Regions"
        assert g["department_display"] == "All Departments"

    def test_unknown_region_total(self, db_conn):
        """Region subtotal for data-NULL region must exist with 'Unknown' label."""
        results = self._results(db_conn)
        unknown_rt = [
            r for r in results
            if r["report_level"] == "region_total" and r["region_display"] == "Unknown"
        ]
        assert len(unknown_rt) == 1
        assert float(unknown_rt[0]["total_amount"]) == pytest.approx(2950.0)
        assert unknown_rt[0]["txn_count"] == 3

    def test_detail_amounts(self, db_conn):
        """Verify specific detail row amounts with root-level departments."""
        results = self._results(db_conn)
        details = {
            (r["region_display"], r["department_display"]): (
                float(r["total_amount"]),
                r["txn_count"],
            )
            for r in results
            if r["report_level"] == "detail"
        }
        assert details[("North", "Engineering")] == pytest.approx((15800.0, 7), abs=0.01)
        assert details[("South", "Engineering")] == pytest.approx((8500.0, 4), abs=0.01)
        assert details[("South", "Sales")] == pytest.approx((21700.0, 8), abs=0.01)
        assert details[("West", "Marketing")] == pytest.approx((7300.0, 3), abs=0.01)
        assert details[("Unknown", "Marketing")] == pytest.approx((2950.0, 3), abs=0.01)

    def test_dept_total_amounts(self, db_conn):
        results = self._results(db_conn)
        dept_totals = {
            r["department_display"]: float(r["total_amount"])
            for r in results
            if r["report_level"] == "dept_total"
        }
        assert dept_totals["Engineering"] == pytest.approx(24300.0)
        assert dept_totals["Sales"] == pytest.approx(21700.0)
        assert dept_totals["Marketing"] == pytest.approx(10250.0)

    def test_region_total_amounts(self, db_conn):
        results = self._results(db_conn)
        region_totals = {
            r["region_display"]: float(r["total_amount"])
            for r in results
            if r["report_level"] == "region_total"
        }
        assert region_totals["North"] == pytest.approx(15800.0)
        assert region_totals["South"] == pytest.approx(30200.0)
        assert region_totals["West"] == pytest.approx(7300.0)
        assert region_totals["Unknown"] == pytest.approx(2950.0)


# -- Q2: Window Analytics -----------------------------------------------------


class TestQ2WindowAnalytics:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q2_window_analytics.sql")
        return results

    def _emp(self, db_conn, eid):
        return [r for r in self._results(db_conn) if r["employee_id"] == eid]

    def test_row_count(self, db_conn):
        assert len(self._results(db_conn)) == 25

    def test_top_department_is_root_level(self, db_conn):
        """top_department must be the root-level name, not the sub-department."""
        emp101 = self._emp(db_conn, 101)
        assert emp101[0]["top_department"] == "Engineering", (
            f"Expected 'Engineering' (root), got '{emp101[0]['top_department']}' (likely sub-dept 'Backend')"
        )
        emp103 = self._emp(db_conn, 103)
        assert emp103[0]["top_department"] == "Sales"
        emp105 = self._emp(db_conn, 105)
        assert emp105[0]["top_department"] == "Marketing"

    def test_emp101_running_total_rows_not_range(self, db_conn):
        """Employee 101 has two transactions on 2024-01-05. With correct
        implementation, first row's running_total = 2500."""
        emp = self._emp(db_conn, 101)
        assert len(emp) == 5
        assert float(emp[0]["running_total"]) == pytest.approx(2500.0), (
            f"First row running_total must be 2500.00, got {emp[0]['running_total']}"
        )
        assert float(emp[1]["running_total"]) == pytest.approx(4300.0)

    def test_emp101_prev_amount(self, db_conn):
        emp = self._emp(db_conn, 101)
        assert emp[0]["prev_amount"] is None
        assert float(emp[1]["prev_amount"]) == pytest.approx(2500.0)

    def test_emp101_moving_avg_3row(self, db_conn):
        """moving_avg_3 must be a 3-transaction moving average."""
        emp = self._emp(db_conn, 101)
        # Row 4 (amount=2100): avg(1800,3200,2100) = 2366.67
        assert float(emp[3]["moving_avg_3"]) == pytest.approx(2366.67, abs=0.01), (
            f"Expected 3-row moving avg 2366.67, got {emp[3]['moving_avg_3']}"
        )
        # Row 5 (amount=1500): avg(3200,2100,1500) = 2266.67
        assert float(emp[4]["moving_avg_3"]) == pytest.approx(2266.67, abs=0.01)

    def test_emp103_moving_avg_3row(self, db_conn):
        """Employee 103 has 5 transactions. Later rows must reflect
        a 3-row window, not a cumulative average."""
        emp = self._emp(db_conn, 103)
        assert len(emp) == 5
        # Row 4 (amount=4500): avg(3100,1900,4500) = 3166.67
        assert float(emp[3]["moving_avg_3"]) == pytest.approx(3166.67, abs=0.01), (
            f"Expected 3-row moving avg 3166.67, got {emp[3]['moving_avg_3']}"
        )
        # Row 5 (amount=2800): avg(1900,4500,2800) = 3066.67
        assert float(emp[4]["moving_avg_3"]) == pytest.approx(3066.67, abs=0.01)

    def test_emp103_running_totals(self, db_conn):
        emp = self._emp(db_conn, 103)
        expected = [5200.0, 8300.0, 10200.0, 14700.0, 17500.0]
        actual = [float(r["running_total"]) for r in emp]
        for a, e in zip(actual, expected):
            assert a == pytest.approx(e)

    def test_dept_amount_rank_by_root_department(self, db_conn):
        """dept_amount_rank must partition by root-level department, not employee_id."""
        emp101 = self._emp(db_conn, 101)
        assert emp101[0]["dept_amount_rank"] == 4, (
            f"emp 101 txn 1 (2500 in Engineering) should be rank 4, got {emp101[0]['dept_amount_rank']}"
        )
        assert emp101[1]["dept_amount_rank"] == 8  # 1800 in Engineering

    def test_dept_amount_rank_emp104(self, db_conn):
        """Employee 104 (SMB -> Sales). Amount 800: rank 8 in Sales."""
        emp = self._emp(db_conn, 104)
        assert emp[0]["dept_amount_rank"] == 8, (
            f"emp 104 txn 13 (800 in Sales) should be rank 8, got {emp[0]['dept_amount_rank']}"
        )
        assert emp[1]["dept_amount_rank"] == 7  # 1200 in Sales

    def test_dept_amount_rank_emp106(self, db_conn):
        """Employee 106 (Events -> Marketing). Amount 3500: rank 1 in Marketing."""
        emp = self._emp(db_conn, 106)
        assert emp[0]["dept_amount_rank"] == 1  # 3500 in Marketing
        assert emp[1]["dept_amount_rank"] == 4  # 1100 in Marketing
        assert emp[2]["dept_amount_rank"] == 2  # 2700 in Marketing

    def test_emp107_running_totals(self, db_conn):
        emp = self._emp(db_conn, 107)
        assert len(emp) == 4
        expected = [2900.0, 4600.0, 6900.0, 8500.0]
        actual = [float(r["running_total"]) for r in emp]
        for a, e in zip(actual, expected):
            assert a == pytest.approx(e)

    def test_emp107_moving_avg(self, db_conn):
        emp = self._emp(db_conn, 107)
        # Row 4 (amount=1600): 3-row = avg(1700,2300,1600) = 1866.67
        assert float(emp[3]["moving_avg_3"]) == pytest.approx(1866.67, abs=0.01)


# -- Q3: Tag Revenue Analysis -------------------------------------------------


class TestQ3TagRevenue:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q3_tag_revenue.sql")
        return results

    def _tag(self, db_conn, name):
        return [r for r in self._results(db_conn) if r["tag_name"] == name]

    def test_row_count(self, db_conn):
        results = self._results(db_conn)
        assert len(results) == 13, (
            f"Expected 13 tag rows (12 distinct tags + untagged), got {len(results)}"
        )

    def test_untagged_exists(self, db_conn):
        """Transactions with NULL or empty tags must appear as 'untagged'."""
        untagged = self._tag(db_conn, "untagged")
        assert len(untagged) == 1, "Must have exactly one 'untagged' row"
        assert untagged[0]["txn_count"] == 3
        assert float(untagged[0]["total_revenue"]) == pytest.approx(3700.0)

    def test_untagged_departments(self, db_conn):
        """Untagged: txn 5 (emp101->Engineering), txn 18 (emp105->Marketing),
        txn 25 (emp107->Engineering) -> [Engineering, Marketing]."""
        untagged = self._tag(db_conn, "untagged")
        depts = list(untagged[0]["departments"])
        assert depts == ["Engineering", "Marketing"]

    def test_enterprise_values(self, db_conn):
        e = self._tag(db_conn, "enterprise")
        assert len(e) == 1
        assert e[0]["txn_count"] == 4
        assert float(e[0]["total_revenue"]) == pytest.approx(15600.0)
        assert list(e[0]["departments"]) == ["Sales"]

    def test_urgent_spans_departments(self, db_conn):
        """'urgent' appears across Engineering, Marketing, and Sales."""
        u = self._tag(db_conn, "urgent")
        assert len(u) == 1
        assert u[0]["txn_count"] == 6
        assert float(u[0]["total_revenue"]) == pytest.approx(13000.0)
        depts = list(u[0]["departments"])
        assert depts == ["Engineering", "Marketing", "Sales"]

    def test_backend_values(self, db_conn):
        b = self._tag(db_conn, "backend")
        assert len(b) == 1
        assert b[0]["txn_count"] == 5
        assert float(b[0]["total_revenue"]) == pytest.approx(12700.0)
        assert list(b[0]["departments"]) == ["Engineering"]

    def test_consulting_values(self, db_conn):
        c = self._tag(db_conn, "consulting")
        assert len(c) == 1
        assert c[0]["txn_count"] == 4
        assert float(c[0]["total_revenue"]) == pytest.approx(11400.0)
        assert list(c[0]["departments"]) == ["Sales"]

    def test_premium_departments(self, db_conn):
        """'premium': emp104->Sales, emp106->Marketing -> [Marketing, Sales]."""
        p = self._tag(db_conn, "premium")
        assert len(p) == 1
        assert p[0]["txn_count"] == 3
        assert float(p[0]["total_revenue"]) == pytest.approx(8400.0)
        assert list(p[0]["departments"]) == ["Marketing", "Sales"]

    def test_uses_root_department_names(self, db_conn):
        """departments arrays must use root-level names, not sub-departments."""
        results = self._results(db_conn)
        sub_depts = {"Backend", "Frontend", "Enterprise", "SMB", "Digital", "Events"}
        for r in results:
            for d in r["departments"]:
                assert d not in sub_depts, (
                    f"Tag '{r['tag_name']}' has sub-department '{d}'. Must use root-level names."
                )

    def test_ordered_by_revenue_desc(self, db_conn):
        results = self._results(db_conn)
        revenues = [float(r["total_revenue"]) for r in results]
        assert revenues == sorted(revenues, reverse=True)

    def test_all_tags_present(self, db_conn):
        results = self._results(db_conn)
        tag_names = {r["tag_name"] for r in results}
        expected = {
            "enterprise", "urgent", "backend", "consulting", "infrastructure",
            "premium", "events", "frontend", "smb", "untagged", "mobile",
            "digital", "social",
        }
        assert tag_names == expected


# -- Q4: Streak Analysis ------------------------------------------------------


class TestQ4StreakAnalysis:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q4_streak_analysis.sql")
        return results

    def _emp_streaks(self, db_conn, eid):
        return [r for r in self._results(db_conn) if r["employee_id"] == eid]

    def test_row_count(self, db_conn):
        results = self._results(db_conn)
        assert len(results) == 14, f"Expected 14 streaks, got {len(results)}"

    def test_top_streak_emp103(self, db_conn):
        """Employee 103 has transactions on 5 consecutive days (Jan 4-8)."""
        streaks = self._emp_streaks(db_conn, 103)
        assert len(streaks) == 1
        s = streaks[0]
        assert s["streak_days"] == 5
        assert float(s["streak_revenue"]) == pytest.approx(17500.0)
        assert s["streak_rank"] == 1
        assert s["streak_start"] == datetime.date(2024, 1, 4)
        assert s["streak_end"] == datetime.date(2024, 1, 8)

    def test_second_streak_emp107(self, db_conn):
        """Employee 107 has 4 consecutive days (Jan 6-9)."""
        streaks = self._emp_streaks(db_conn, 107)
        assert len(streaks) == 1
        s = streaks[0]
        assert s["streak_days"] == 4
        assert float(s["streak_revenue"]) == pytest.approx(8500.0)
        assert s["streak_rank"] == 2

    def test_emp101_two_streaks(self, db_conn):
        """Employee 101: Jan 5 (1 day, 4300) and Jan 8-10 (3 days, 6800)."""
        streaks = self._emp_streaks(db_conn, 101)
        assert len(streaks) == 2
        by_days = sorted(streaks, key=lambda s: s["streak_days"])
        # 1-day streak
        assert by_days[0]["streak_days"] == 1
        assert float(by_days[0]["streak_revenue"]) == pytest.approx(4300.0)
        # 3-day streak
        assert by_days[1]["streak_days"] == 3
        assert float(by_days[1]["streak_revenue"]) == pytest.approx(6800.0)
        assert by_days[1]["streak_rank"] == 3

    def test_emp101_same_day_handled(self, db_conn):
        """Employee 101 has 2 transactions on Jan 5. This must count as
        1 streak day, not 2. Revenue must include both transactions."""
        streaks = self._emp_streaks(db_conn, 101)
        one_day = [s for s in streaks if s["streak_days"] == 1]
        assert len(one_day) == 1
        # Two txns on Jan 5: 2500 + 1800 = 4300
        assert float(one_day[0]["streak_revenue"]) == pytest.approx(4300.0)
        assert one_day[0]["streak_start"] == datetime.date(2024, 1, 5)
        assert one_day[0]["streak_end"] == datetime.date(2024, 1, 5)

    def test_emp104_two_day_streak(self, db_conn):
        """Employee 104: Jan 7-8 (2 days, 2000) and Jan 10 (1 day, 2200)."""
        streaks = self._emp_streaks(db_conn, 104)
        assert len(streaks) == 2
        two_day = [s for s in streaks if s["streak_days"] == 2]
        assert len(two_day) == 1
        assert float(two_day[0]["streak_revenue"]) == pytest.approx(2000.0)
        assert two_day[0]["streak_rank"] == 4

    def test_emp105_three_single_day_streaks(self, db_conn):
        """Employee 105 has non-consecutive dates (Jan 5, 7, 9): 3 single-day streaks."""
        streaks = self._emp_streaks(db_conn, 105)
        assert len(streaks) == 3
        for s in streaks:
            assert s["streak_days"] == 1

    def test_emp106_three_single_day_streaks(self, db_conn):
        """Employee 106 has non-consecutive dates (Jan 4, 6, 8): 3 single-day streaks."""
        streaks = self._emp_streaks(db_conn, 106)
        assert len(streaks) == 3
        for s in streaks:
            assert s["streak_days"] == 1

    def test_uses_dense_rank(self, db_conn):
        """Must use DENSE_RANK, not RANK (no gaps in ranking sequence)."""
        results = self._results(db_conn)
        ranks = sorted(set(r["streak_rank"] for r in results))
        expected = list(range(1, 15))
        assert ranks == expected, (
            f"Expected consecutive DENSE_RANK values 1-14, got {ranks}"
        )

    def test_ordering(self, db_conn):
        """Results must be ordered by streak_rank, then employee_id."""
        results = self._results(db_conn)
        keys = [(r["streak_rank"], r["employee_id"]) for r in results]
        assert keys == sorted(keys)


# -- Q5: Peer Comparison Analysis ---------------------------------------------


class TestQ5PeerComparison:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q5_peer_comparison.sql")
        return results

    def _txn(self, db_conn, tid):
        return [r for r in self._results(db_conn) if r["txn_id"] == tid]

    def test_row_count(self, db_conn):
        results = self._results(db_conn)
        assert len(results) == 25, f"Expected 25 rows, got {len(results)}"

    def test_uses_root_department_names(self, db_conn):
        """department must use root-level names, not sub-departments."""
        results = self._results(db_conn)
        sub_depts = {"Backend", "Frontend", "Enterprise", "SMB", "Digital", "Events"}
        depts = {r["department"] for r in results}
        found_sub = depts & sub_depts
        assert not found_sub, (
            f"Found sub-department names {found_sub}. Must resolve to root-level departments."
        )

    def test_exactly_three_departments(self, db_conn):
        results = self._results(db_conn)
        depts = {r["department"] for r in results}
        assert depts == {"Engineering", "Sales", "Marketing"}, (
            f"Expected exactly 3 root departments, got {depts}"
        )

    def test_company_avg_all_rows(self, db_conn):
        """company_avg must be the same for every row: 56250/25 = 2250.00."""
        results = self._results(db_conn)
        for r in results:
            assert float(r["company_avg"]) == pytest.approx(2250.00), (
                f"company_avg should be 2250.00 for all rows, got {r['company_avg']} for txn {r['txn_id']}"
            )

    def test_engineering_dept_avg(self, db_conn):
        """Engineering: 11 txns, total 24300, avg 2209.09."""
        txn = self._txn(db_conn, 1)  # emp 101 -> Backend -> Engineering
        assert len(txn) == 1
        assert txn[0]["department"] == "Engineering"
        assert float(txn[0]["dept_avg"]) == pytest.approx(2209.09, abs=0.01)

    def test_sales_dept_avg(self, db_conn):
        """Sales: 8 txns, total 21700, avg 2712.50."""
        txn = self._txn(db_conn, 8)  # emp 103 -> Enterprise -> Sales
        assert len(txn) == 1
        assert txn[0]["department"] == "Sales"
        assert float(txn[0]["dept_avg"]) == pytest.approx(2712.50, abs=0.01)

    def test_marketing_dept_avg(self, db_conn):
        """Marketing: 6 txns, total 10250, avg 1708.33."""
        txn = self._txn(db_conn, 19)  # emp 106 -> Events -> Marketing
        assert len(txn) == 1
        assert txn[0]["department"] == "Marketing"
        assert float(txn[0]["dept_avg"]) == pytest.approx(1708.33, abs=0.01)

    def test_txn8_deviation(self, db_conn):
        """Txn 8 (5200, Sales): (5200-2712.50)/2712.50*100 = 91.71."""
        txn = self._txn(db_conn, 8)
        assert float(txn[0]["dept_deviation_pct"]) == pytest.approx(91.71, abs=0.01)

    def test_txn18_deviation(self, db_conn):
        """Txn 18 (600, Marketing): (600-1708.33)/1708.33*100 = -64.88."""
        txn = self._txn(db_conn, 18)
        assert float(txn[0]["dept_deviation_pct"]) == pytest.approx(-64.88, abs=0.01)

    def test_txn19_deviation(self, db_conn):
        """Txn 19 (3500, Marketing): (3500-1708.33)/1708.33*100 = 104.88."""
        txn = self._txn(db_conn, 19)
        assert float(txn[0]["dept_deviation_pct"]) == pytest.approx(104.88, abs=0.01)

    def test_txn13_deviation(self, db_conn):
        """Txn 13 (800, Sales): (800-2712.50)/2712.50*100 = -70.51."""
        txn = self._txn(db_conn, 13)
        assert float(txn[0]["dept_deviation_pct"]) == pytest.approx(-70.51, abs=0.01)

    def test_txn8_rank_pct_max(self, db_conn):
        """Txn 8 (5200, highest amount): PERCENT_RANK = 1.0000."""
        txn = self._txn(db_conn, 8)
        assert float(txn[0]["company_rank_pct"]) == pytest.approx(1.0, abs=0.0001)

    def test_txn18_rank_pct_min(self, db_conn):
        """Txn 18 (600, lowest amount): PERCENT_RANK = 0.0000."""
        txn = self._txn(db_conn, 18)
        assert float(txn[0]["company_rank_pct"]) == pytest.approx(0.0, abs=0.0001)

    def test_txn13_rank_pct(self, db_conn):
        """Txn 13 (800, 2nd lowest): PERCENT_RANK = 1/24 = 0.0417."""
        txn = self._txn(db_conn, 13)
        assert float(txn[0]["company_rank_pct"]) == pytest.approx(0.0417, abs=0.0001)

    def test_ties_have_same_rank_pct(self, db_conn):
        """Txns 6 and 10 both have amount 1900 -> same PERCENT_RANK = 10/24 = 0.4167."""
        txn6 = self._txn(db_conn, 6)
        txn10 = self._txn(db_conn, 10)
        assert float(txn6[0]["company_rank_pct"]) == pytest.approx(
            float(txn10[0]["company_rank_pct"]), abs=0.0001
        )
        assert float(txn6[0]["company_rank_pct"]) == pytest.approx(0.4167, abs=0.0001)

    def test_ordering_desc_by_rank_pct(self, db_conn):
        """Results must be ordered by company_rank_pct DESC, then txn_id."""
        results = self._results(db_conn)
        rank_pcts = [float(r["company_rank_pct"]) for r in results]
        for i in range(len(rank_pcts) - 1):
            if rank_pcts[i] == pytest.approx(rank_pcts[i + 1], abs=0.0001):
                assert results[i]["txn_id"] < results[i + 1]["txn_id"], (
                    f"Tied rank_pct rows should be ordered by txn_id ASC"
                )
            else:
                assert rank_pcts[i] > rank_pcts[i + 1], (
                    f"Row {i} rank_pct {rank_pcts[i]} should be > row {i+1} rank_pct {rank_pcts[i+1]}"
                )

    def test_first_row_is_txn8(self, db_conn):
        """First row (highest company_rank_pct) should be txn 8."""
        results = self._results(db_conn)
        assert results[0]["txn_id"] == 8

    def test_last_row_is_txn18(self, db_conn):
        """Last row (lowest company_rank_pct) should be txn 18."""
        results = self._results(db_conn)
        assert results[-1]["txn_id"] == 18

    def test_txn3_values(self, db_conn):
        """Txn 3 (3200, Engineering): rank_pct = 21/24 = 0.8750."""
        txn = self._txn(db_conn, 3)
        assert txn[0]["department"] == "Engineering"
        assert float(txn[0]["company_rank_pct"]) == pytest.approx(0.8750, abs=0.0001)
        # deviation = (3200-2209.09)/2209.09*100 = 44.86
        assert float(txn[0]["dept_deviation_pct"]) == pytest.approx(44.86, abs=0.01)


# -- Q6: Priority-Weighted Department Trend Analysis --------------------------


class TestQ6PriorityForecast:
    def _results(self, db_conn):
        _, results = run_query_file(db_conn, "/app/queries/q6_priority_forecast.sql")
        return results

    def _dept_date(self, db_conn, dept, date_str):
        d = datetime.date.fromisoformat(date_str)
        return [r for r in self._results(db_conn)
                if r["department"] == dept and r["txn_date"] == d]

    def test_row_count(self, db_conn):
        """18 rows: 6 dates each for Engineering, Marketing, Sales."""
        results = self._results(db_conn)
        assert len(results) == 18, f"Expected 18 rows, got {len(results)}"

    def test_uses_root_departments(self, db_conn):
        """Must use root-level department names only."""
        depts = {r["department"] for r in self._results(db_conn)}
        assert depts == {"Engineering", "Sales", "Marketing"}, (
            f"Expected root departments, got {depts}"
        )

    def test_daily_revenue_no_double_count(self, db_conn):
        """Revenue must not double-count from tag unnesting.
        Engineering 01-05: txn1(2500)+txn2(1800)=4300, not 8600."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-05")
        assert len(rows) == 1
        assert float(rows[0]["daily_revenue"]) == pytest.approx(4300.0), (
            f"Engineering 01-05 daily_revenue should be 4300 (no double-count), "
            f"got {rows[0]['daily_revenue']}"
        )

    def test_daily_revenue_engineering_0108(self, db_conn):
        """Engineering 01-08: txn3(3200)+txn24(2300)=5500."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-08")
        assert float(rows[0]["daily_revenue"]) == pytest.approx(5500.0)

    def test_weighted_revenue_engineering_0108(self, db_conn):
        """(3200*4 + 2300*5) / (4+5) = 24300/9 = 2700.00."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-08")
        assert float(rows[0]["weighted_revenue"]) == pytest.approx(2700.0, abs=0.01)

    def test_weighted_revenue_sales_0107(self, db_conn):
        """(4500*4 + 800*1) / (4+1) = 18800/5 = 3760.00."""
        rows = self._dept_date(db_conn, "Sales", "2024-01-07")
        assert float(rows[0]["weighted_revenue"]) == pytest.approx(3760.0, abs=0.01)

    def test_weighted_revenue_engineering_0109(self, db_conn):
        """(2100*5 + 2800*4 + 1600*2) / (5+4+2) = 24900/11 = 2263.64.
        Txn 25 has NULL tags but must still contribute to revenue."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-09")
        assert float(rows[0]["weighted_revenue"]) == pytest.approx(2263.64, abs=0.01)

    def test_rolling_weighted_engineering_0107(self, db_conn):
        """3-row rolling avg: avg(2220.00, 2471.43, 1700.00) = 2130.48."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-07")
        assert float(rows[0]["rolling_weighted_3d"]) == pytest.approx(2130.48, abs=0.02)

    def test_rolling_weighted_not_cumulative(self, db_conn):
        """Engineering row 6 (01-10) rolling must be 3-row, not cumulative.
        avg(2700.00, 2263.64, 1500.00) = 2154.55, NOT overall avg."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-10")
        assert float(rows[0]["rolling_weighted_3d"]) == pytest.approx(2154.55, abs=0.02)

    def test_cumulative_revenue_last_rows(self, db_conn):
        """Last row per department should equal total department revenue."""
        eng = self._dept_date(db_conn, "Engineering", "2024-01-10")
        assert float(eng[0]["cumulative_revenue"]) == pytest.approx(24300.0)
        sales = self._dept_date(db_conn, "Sales", "2024-01-10")
        assert float(sales[0]["cumulative_revenue"]) == pytest.approx(21700.0)
        mkt = self._dept_date(db_conn, "Marketing", "2024-01-09")
        assert float(mkt[0]["cumulative_revenue"]) == pytest.approx(10250.0)

    def test_cumulative_revenue_mid(self, db_conn):
        """Engineering 01-08: 4300+4800+1700+5500 = 16300."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-08")
        assert float(rows[0]["cumulative_revenue"]) == pytest.approx(16300.0)

    def test_daily_tags_with_dedup(self, db_conn):
        """Engineering 01-05 has 'backend' from both txns. Must deduplicate."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-05")
        tags = list(rows[0]["daily_tags"])
        assert tags == ["backend", "infrastructure", "urgent"]

    def test_daily_tags_multi_subdept(self, db_conn):
        """Engineering 01-06: Backend tags + Frontend tags merged."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-06")
        tags = list(rows[0]["daily_tags"])
        assert tags == ["backend", "frontend", "infrastructure", "urgent"]

    def test_daily_tags_dedup_0108(self, db_conn):
        """Engineering 01-08: txn3{backend} + txn24{backend,urgent} -> {backend,urgent}."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-08")
        tags = list(rows[0]["daily_tags"])
        assert tags == ["backend", "urgent"]

    def test_daily_tags_empty_null_tags(self, db_conn):
        """Engineering 01-10 only has txn5 with NULL tags -> empty array."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-10")
        tags = list(rows[0]["daily_tags"])
        assert tags == [], f"Expected empty array for NULL-only tags, got {tags}"

    def test_daily_tags_empty_empty_array(self, db_conn):
        """Marketing 01-09 only has txn18 with empty '{}' tags -> empty array."""
        rows = self._dept_date(db_conn, "Marketing", "2024-01-09")
        tags = list(rows[0]["daily_tags"])
        assert tags == [], f"Expected empty array for empty-array tags, got {tags}"

    def test_tag_carryover_first_day_null(self, db_conn):
        """First day per department has no previous -> tag_carryover is NULL."""
        eng = self._dept_date(db_conn, "Engineering", "2024-01-05")
        assert eng[0]["tag_carryover"] is None
        mkt = self._dept_date(db_conn, "Marketing", "2024-01-04")
        assert mkt[0]["tag_carryover"] is None
        sales = self._dept_date(db_conn, "Sales", "2024-01-04")
        assert sales[0]["tag_carryover"] is None

    def test_tag_carryover_full_overlap(self, db_conn):
        """Sales 01-05 tags={consulting,enterprise}, prev 01-04={consulting,enterprise}.
        Intersection = {consulting,enterprise}."""
        rows = self._dept_date(db_conn, "Sales", "2024-01-05")
        carryover = list(rows[0]["tag_carryover"])
        assert carryover == ["consulting", "enterprise"]

    def test_tag_carryover_partial_overlap(self, db_conn):
        """Engineering 01-06 tags={backend,frontend,infrastructure,urgent},
        prev 01-05={backend,infrastructure,urgent}.
        Intersection = {backend,infrastructure,urgent}."""
        rows = self._dept_date(db_conn, "Engineering", "2024-01-06")
        carryover = list(rows[0]["tag_carryover"])
        assert carryover == ["backend", "infrastructure", "urgent"]

    def test_tag_carryover_no_overlap(self, db_conn):
        """Marketing 01-05 tags={digital,social}, prev 01-04={events,premium}.
        No overlap -> empty array."""
        rows = self._dept_date(db_conn, "Marketing", "2024-01-05")
        carryover = list(rows[0]["tag_carryover"])
        assert carryover == []

    def test_trend_rank_highest_per_dept(self, db_conn):
        """Highest rolling_weighted_3d per department gets trend_rank=1."""
        # Engineering 01-06 has highest rolling (2345.72)
        eng = self._dept_date(db_conn, "Engineering", "2024-01-06")
        assert eng[0]["trend_rank"] == 1
        # Sales 01-04 has highest rolling (5200.00)
        sales = self._dept_date(db_conn, "Sales", "2024-01-04")
        assert sales[0]["trend_rank"] == 1
        # Marketing 01-04 has highest rolling (3500.00)
        mkt = self._dept_date(db_conn, "Marketing", "2024-01-04")
        assert mkt[0]["trend_rank"] == 1

    def test_ordering(self, db_conn):
        """Results ordered by department ASC, txn_date ASC."""
        results = self._results(db_conn)
        keys = [(r["department"], r["txn_date"]) for r in results]
        assert keys == sorted(keys)

    def test_total_revenue_all_departments(self, db_conn):
        """Sum of all daily_revenue must equal grand total 56250."""
        results = self._results(db_conn)
        total = sum(float(r["daily_revenue"]) for r in results)
        assert total == pytest.approx(56250.0)
