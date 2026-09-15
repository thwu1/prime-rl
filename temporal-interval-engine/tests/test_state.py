"""
Temporal Interval Reconciliation Engine - Verification Tests
"""

import pytest
import psycopg2
from datetime import date
from decimal import Decimal


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(dbname="taskdb", user="postgres")
    conn.set_session(autocommit=True)
    yield conn
    conn.close()


# ============================================================
# v_merged_assignments tests
# ============================================================

class TestMergedAssignments:
    def test_total_row_count(self, db):
        """Exactly 10 merged intervals expected across all employees/projects"""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM v_merged_assignments")
        assert cur.fetchone()[0] == 10

    def test_frank_p101_four_intervals_merge_to_one(self, db):
        """Frank P101: 4 overlapping/adjacent/contained intervals -> 1 merged"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 6 AND project_id = 101
            ORDER BY start_date
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (date(2024, 1, 1), date(2024, 2, 10))

    def test_frank_p102_unchanged(self, db):
        """Frank P102: single interval, no merge needed"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 6 AND project_id = 102
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (date(2024, 1, 20), date(2024, 2, 5))

    def test_grace_p101_gap_preserved(self, db):
        """Grace P101: two intervals with a gap stay separate"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 7 AND project_id = 101
            ORDER BY start_date
        """)
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == (date(2024, 1, 5), date(2024, 1, 20))
        assert rows[1] == (date(2024, 2, 1), date(2024, 2, 15))

    def test_hank_p102_adjacent_merge(self, db):
        """Hank P102: two adjacent intervals (Jan31 -> Feb01) merge"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 8 AND project_id = 102
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (date(2024, 1, 1), date(2024, 2, 28))

    def test_hank_p103_separate(self, db):
        """Hank P103: separate from P102 (Feb 29 gap in leap year)"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 8 AND project_id = 103
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (date(2024, 3, 1), date(2024, 3, 15))

    def test_jack_p104_gap_preserved(self, db):
        """Jack P104: two intervals with a 4-day gap stay separate"""
        cur = db.cursor()
        cur.execute("""
            SELECT start_date, end_date FROM v_merged_assignments
            WHERE employee_id = 10 AND project_id = 104
            ORDER BY start_date
        """)
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == (date(2024, 1, 1), date(2024, 1, 15))
        assert rows[1] == (date(2024, 1, 20), date(2024, 1, 31))

    def test_all_results_comprehensive(self, db):
        """Full sorted result set check"""
        cur = db.cursor()
        cur.execute("""
            SELECT employee_id, project_id, start_date, end_date
            FROM v_merged_assignments
            ORDER BY employee_id, project_id, start_date
        """)
        rows = cur.fetchall()
        expected = [
            (6, 101, date(2024, 1, 1), date(2024, 2, 10)),
            (6, 102, date(2024, 1, 20), date(2024, 2, 5)),
            (7, 101, date(2024, 1, 5), date(2024, 1, 20)),
            (7, 101, date(2024, 2, 1), date(2024, 2, 15)),
            (7, 103, date(2024, 1, 15), date(2024, 1, 25)),
            (8, 102, date(2024, 1, 1), date(2024, 2, 28)),
            (8, 103, date(2024, 3, 1), date(2024, 3, 15)),
            (10, 104, date(2024, 1, 1), date(2024, 1, 15)),
            (10, 104, date(2024, 1, 20), date(2024, 1, 31)),
            (10, 105, date(2024, 2, 1), date(2024, 2, 15)),
        ]
        assert rows == expected


# ============================================================
# v_scheduling_conflicts tests
# ============================================================

class TestSchedulingConflicts:
    def test_conflict_count(self, db):
        """Exactly 2 scheduling conflicts exist"""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM v_scheduling_conflicts")
        assert cur.fetchone()[0] == 2

    def test_frank_conflict(self, db):
        """Frank: P101 and P102 overlap from Jan 20 to Feb 5"""
        cur = db.cursor()
        cur.execute("""
            SELECT project_a, project_b, conflict_start, conflict_end
            FROM v_scheduling_conflicts WHERE employee_id = 6
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (101, 102, date(2024, 1, 20), date(2024, 2, 5))

    def test_grace_conflict(self, db):
        """Grace: P101 (first interval) and P103 overlap from Jan 15 to Jan 20"""
        cur = db.cursor()
        cur.execute("""
            SELECT project_a, project_b, conflict_start, conflict_end
            FROM v_scheduling_conflicts WHERE employee_id = 7
        """)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0] == (101, 103, date(2024, 1, 15), date(2024, 1, 20))

    def test_no_false_conflicts(self, db):
        """Hank and Jack should have no scheduling conflicts"""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM v_scheduling_conflicts
            WHERE employee_id IN (8, 10)
        """)
        assert cur.fetchone()[0] == 0


# ============================================================
# v_effective_billing tests
# ============================================================

class TestEffectiveBilling:
    def test_billing_row_count(self, db):
        """Exactly 14 billing segments expected"""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM v_effective_billing")
        assert cur.fetchone()[0] == 14

    def test_frank_p101_split_at_rate_change(self, db):
        """Frank P101 (Jan 1 - Feb 10) splits at rate boundary Jan 31/Feb 1"""
        cur = db.cursor()
        cur.execute("""
            SELECT segment_start, segment_end, hourly_rate, segment_days, segment_cost
            FROM v_effective_billing
            WHERE employee_id = 6 AND project_id = 101
            ORDER BY segment_start
        """)
        rows = cur.fetchall()
        assert len(rows) == 2
        # Segment 1: Jan 1 - Jan 31 at $75
        assert rows[0][0] == date(2024, 1, 1)
        assert rows[0][1] == date(2024, 1, 31)
        assert float(rows[0][2]) == pytest.approx(75.0)
        assert int(rows[0][3]) == 31
        assert float(rows[0][4]) == pytest.approx(2325.0)
        # Segment 2: Feb 1 - Feb 10 at $85
        assert rows[1][0] == date(2024, 2, 1)
        assert rows[1][1] == date(2024, 2, 10)
        assert float(rows[1][2]) == pytest.approx(85.0)
        assert int(rows[1][3]) == 10
        assert float(rows[1][4]) == pytest.approx(850.0)

    def test_frank_p102_split(self, db):
        """Frank P102 (Jan 20 - Feb 5) also splits at rate boundary"""
        cur = db.cursor()
        cur.execute("""
            SELECT segment_start, segment_end, hourly_rate, segment_days, segment_cost
            FROM v_effective_billing
            WHERE employee_id = 6 AND project_id = 102
            ORDER BY segment_start
        """)
        rows = cur.fetchall()
        assert len(rows) == 2
        assert int(rows[0][3]) == 12  # Jan 20 - Jan 31
        assert float(rows[0][4]) == pytest.approx(900.0)
        assert int(rows[1][3]) == 5   # Feb 1 - Feb 5
        assert float(rows[1][4]) == pytest.approx(425.0)

    def test_grace_p101_three_segments(self, db):
        """Grace P101 has 3 segments: first interval splits, second is single rate"""
        cur = db.cursor()
        cur.execute("""
            SELECT segment_start, segment_end, hourly_rate, segment_days, segment_cost
            FROM v_effective_billing
            WHERE employee_id = 7 AND project_id = 101
            ORDER BY segment_start
        """)
        rows = cur.fetchall()
        assert len(rows) == 3
        # Jan 5 - Jan 14 at $80
        assert rows[0][0] == date(2024, 1, 5)
        assert rows[0][1] == date(2024, 1, 14)
        assert float(rows[0][2]) == pytest.approx(80.0)
        assert int(rows[0][3]) == 10
        assert float(rows[0][4]) == pytest.approx(800.0)
        # Jan 15 - Jan 20 at $90
        assert rows[1][0] == date(2024, 1, 15)
        assert rows[1][1] == date(2024, 1, 20)
        assert float(rows[1][2]) == pytest.approx(90.0)
        assert int(rows[1][3]) == 6
        assert float(rows[1][4]) == pytest.approx(540.0)
        # Feb 1 - Feb 15 at $90
        assert rows[2][0] == date(2024, 2, 1)
        assert rows[2][1] == date(2024, 2, 15)
        assert int(rows[2][3]) == 15
        assert float(rows[2][4]) == pytest.approx(1350.0)

    def test_hank_p102_split(self, db):
        """Hank P102 merged (Jan 1 - Feb 28) splits at Feb 14/15"""
        cur = db.cursor()
        cur.execute("""
            SELECT segment_days, segment_cost
            FROM v_effective_billing
            WHERE employee_id = 8 AND project_id = 102
            ORDER BY segment_start
        """)
        rows = cur.fetchall()
        assert len(rows) == 2
        assert int(rows[0][0]) == 45  # Jan 1 - Feb 14
        assert float(rows[0][1]) == pytest.approx(3150.0)
        assert int(rows[1][0]) == 14  # Feb 15 - Feb 28
        assert float(rows[1][1]) == pytest.approx(1050.0)

    def test_jack_single_rate(self, db):
        """Jack has a single rate ($60), no segments should split"""
        cur = db.cursor()
        cur.execute("""
            SELECT segment_days, hourly_rate, segment_cost
            FROM v_effective_billing
            WHERE employee_id = 10
            ORDER BY project_id, segment_start
        """)
        rows = cur.fetchall()
        assert len(rows) == 3
        for row in rows:
            assert float(row[1]) == pytest.approx(60.0)
        assert int(rows[0][0]) == 15  # P104: Jan 1-15
        assert float(rows[0][2]) == pytest.approx(900.0)
        assert int(rows[1][0]) == 12  # P104: Jan 20-31
        assert float(rows[1][2]) == pytest.approx(720.0)
        assert int(rows[2][0]) == 15  # P105: Feb 1-15
        assert float(rows[2][2]) == pytest.approx(900.0)


# ============================================================
# fn_team_utilization tests
# ============================================================

class TestTeamUtilization:
    def test_bob_team_q1(self, db):
        """Bob's team (Dave, Eve, Frank, Grace, Hank) utilization for Q1 2024"""
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM fn_team_utilization(2, '2024-01-01', '2024-03-31')"
        )
        rows = cur.fetchall()
        assert len(rows) == 5
        results = {row[0]: row for row in rows}

        # All should have 91 period_days (Jan31 + Feb29 + Mar31)
        for row in rows:
            assert int(row[3]) == 91

        # Dave (4): no assignments
        assert int(results[4][2]) == 0
        assert float(results[4][4]) == pytest.approx(0.0)

        # Eve (5): no assignments
        assert int(results[5][2]) == 0
        assert float(results[5][4]) == pytest.approx(0.0)

        # Frank (6): P101 (Jan1-Feb10) fully covers P102 (Jan20-Feb5)
        assert int(results[6][2]) == 41
        assert float(results[6][4]) == pytest.approx(45.05)

        # Grace (7): P101 first + P103 merge to (Jan5-Jan25)=21d, P101 second (Feb1-Feb15)=15d
        assert int(results[7][2]) == 36
        assert float(results[7][4]) == pytest.approx(39.56)

        # Hank (8): P102 (Jan1-Feb28)=59d + P103 (Mar1-Mar15)=15d, gap on Feb 29
        assert int(results[8][2]) == 74
        assert float(results[8][4]) == pytest.approx(81.32)

    def test_dave_team_jan_feb(self, db):
        """Dave manages Frank and Grace; test for Jan-Feb 2024"""
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM fn_team_utilization(4, '2024-01-01', '2024-02-29')"
        )
        rows = cur.fetchall()
        assert len(rows) == 2
        results = {row[0]: row for row in rows}

        # Period: 60 days (Jan31 + Feb29)
        for row in rows:
            assert int(row[3]) == 60

        # Frank: 41 assigned days
        assert int(results[6][2]) == 41
        assert float(results[6][4]) == pytest.approx(68.33)

        # Grace: 36 assigned days
        assert int(results[7][2]) == 36
        assert float(results[7][4]) == pytest.approx(60.0)

    def test_carol_team(self, db):
        """Carol's team: Ivy (no assignments) and Jack"""
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM fn_team_utilization(3, '2024-01-01', '2024-03-31')"
        )
        rows = cur.fetchall()
        assert len(rows) == 2
        results = {row[0]: row for row in rows}

        # Ivy (9): no assignments
        assert int(results[9][2]) == 0
        assert float(results[9][4]) == pytest.approx(0.0)

        # Jack (10): P104(15+12)=27d + P105(15d)=42d total (adjacent merge across projects)
        assert int(results[10][2]) == 42
        assert float(results[10][4]) == pytest.approx(46.15)

    def test_leaf_node_empty(self, db):
        """An IC with no reports should return empty result set"""
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM fn_team_utilization(6, '2024-01-01', '2024-03-31')"
        )
        rows = cur.fetchall()
        assert len(rows) == 0

    def test_results_ordered_by_employee_id(self, db):
        """Results must be ordered by employee_id"""
        cur = db.cursor()
        cur.execute(
            "SELECT employee_id FROM fn_team_utilization(1, '2024-01-01', '2024-03-31')"
        )
        ids = [row[0] for row in cur.fetchall()]
        assert ids == sorted(ids)
        assert len(ids) == 9  # Everyone except Alice herself
