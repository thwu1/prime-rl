import pytest
import subprocess



def get_connection():
    """Get a psycopg2 connection to the exercises database."""
    import psycopg2
    return psycopg2.connect(dbname="exercises", user="postgres", host="127.0.0.1")


@pytest.fixture(scope="session")
def db():
    """Database connection fixture."""
    conn = get_connection()
    conn.set_session(autocommit=True)
    yield conn
    conn.close()


# ================================================================
# Tests for cd.daily_facility_revenue
# ================================================================

class TestDailyFacilityRevenue:

    def test_view_exists_with_correct_columns(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'cd' AND table_name = 'daily_facility_revenue'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'facility_name' in columns
        assert 'facid' in columns
        assert 'date' in columns
        assert 'revenue' in columns

    def test_row_count(self, db):
        """9 facilities * 215 days (2012-07-01 to 2013-01-31) = 1935 rows."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.daily_facility_revenue")
        assert cur.fetchone()[0] == 1935

    def test_zero_revenue_days_exist(self, db):
        """Days with no bookings must appear with revenue = 0."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.daily_facility_revenue WHERE revenue = 0")
        zero_count = cur.fetchone()[0]
        assert zero_count > 100, "Many zero-revenue days should exist (Oct-Dec have no bookings)"

    def test_no_null_revenue(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.daily_facility_revenue WHERE revenue IS NULL")
        assert cur.fetchone()[0] == 0, "Revenue must never be NULL, use 0 for no-booking days"

    def test_date_range(self, db):
        cur = db.cursor()
        cur.execute("SELECT MIN(date), MAX(date) FROM cd.daily_facility_revenue")
        min_date, max_date = cur.fetchone()
        assert str(min_date) == '2012-07-01'
        assert str(max_date) == '2013-01-31'

    def test_all_facilities_present(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(DISTINCT facid) FROM cd.daily_facility_revenue")
        assert cur.fetchone()[0] == 9

    def test_specific_revenue_tennis_court_1_jul4(self, db):
        """Tennis Court 1 (facid=0) on 2012-07-04: two member bookings of 3 slots each at membercost=5."""
        cur = db.cursor()
        cur.execute("""
            SELECT revenue FROM cd.daily_facility_revenue
            WHERE facid = 0 AND date = '2012-07-04'
        """)
        revenue = float(cur.fetchone()[0])
        assert revenue == 30.0

    def test_zero_revenue_on_no_booking_day(self, db):
        """Tennis Court 1 (facid=0) on 2012-07-01 had no bookings (first booking is Jul 4)."""
        cur = db.cursor()
        cur.execute("""
            SELECT revenue FROM cd.daily_facility_revenue
            WHERE facid = 0 AND date = '2012-07-01'
        """)
        revenue = float(cur.fetchone()[0])
        assert revenue == 0.0


# ================================================================
# Tests for cd.revenue_rolling_stats
# ================================================================

class TestRevenueRollingStats:

    def test_view_exists_with_correct_columns(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'cd' AND table_name = 'revenue_rolling_stats'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'facility_name' in columns
        assert 'facid' in columns
        assert 'date' in columns
        assert 'revenue' in columns
        assert 'rolling_avg' in columns
        assert 'rolling_stddev' in columns
        assert 'zscore' in columns

    def test_row_count(self, db):
        """9 facilities * 61 days (Aug 1 - Sep 30) = 549 rows."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.revenue_rolling_stats")
        assert cur.fetchone()[0] == 549

    def test_date_range(self, db):
        cur = db.cursor()
        cur.execute("SELECT MIN(date), MAX(date) FROM cd.revenue_rolling_stats")
        min_date, max_date = cur.fetchone()
        assert str(min_date) == '2012-08-01'
        assert str(max_date) == '2012-09-30'

    def test_rolling_avg_aug1_cross_check(self, db):
        """Sum of per-facility 15-day rolling averages on Aug 1 must match
        the known total rolling average of ~1126.83 from the source exercises."""
        cur = db.cursor()
        cur.execute("""
            SELECT ROUND(SUM(rolling_avg)::numeric, 2)
            FROM cd.revenue_rolling_stats
            WHERE date = '2012-08-01'
        """)
        total = float(cur.fetchone()[0])
        assert abs(total - 1126.83) < 0.1, \
            f"Sum of facility rolling avgs on Aug 1 should be ~1126.83, got {total}"

    def test_rolling_avg_aug31_cross_check(self, db):
        """Sum of per-facility 15-day rolling averages on Aug 31 must match
        the known total rolling average of ~1703.40."""
        cur = db.cursor()
        cur.execute("""
            SELECT ROUND(SUM(rolling_avg)::numeric, 2)
            FROM cd.revenue_rolling_stats
            WHERE date = '2012-08-31'
        """)
        total = float(cur.fetchone()[0])
        assert abs(total - 1703.40) < 0.1, \
            f"Sum of facility rolling avgs on Aug 31 should be ~1703.40, got {total}"

    def test_uses_population_stddev(self, db):
        """Must use STDDEV_POP, not STDDEV_SAMP. Verify by independent computation."""
        cur = db.cursor()
        cur.execute("""
            WITH window_data AS (
                SELECT revenue
                FROM cd.daily_facility_revenue
                WHERE facid = 0
                AND date BETWEEN '2012-08-01'::date - INTERVAL '14 days' AND '2012-08-01'
                ORDER BY date
            )
            SELECT STDDEV_POP(revenue)::float FROM window_data
        """)
        expected = cur.fetchone()[0]
        cur.execute("""
            SELECT rolling_stddev::float FROM cd.revenue_rolling_stats
            WHERE facid = 0 AND date = '2012-08-01'
        """)
        actual = cur.fetchone()[0]
        if expected is not None and actual is not None:
            assert abs(actual - expected) < 0.01, \
                f"Expected STDDEV_POP={expected}, got {actual}. Use STDDEV_POP, not STDDEV."

    def test_july_lookback_used(self, db):
        """On Aug 1, the rolling average must use July data (not just Aug 1 alone)."""
        cur = db.cursor()
        cur.execute("""
            SELECT rolling_avg::float, revenue::float
            FROM cd.revenue_rolling_stats
            WHERE facid = 0 AND date = '2012-08-01'
        """)
        row = cur.fetchone()
        rolling_avg, revenue = row[0], row[1]
        cur.execute("""
            SELECT AVG(revenue)::float
            FROM cd.daily_facility_revenue
            WHERE facid = 0 AND date BETWEEN '2012-07-18' AND '2012-08-01'
        """)
        expected_avg = cur.fetchone()[0]
        assert abs(rolling_avg - expected_avg) < 0.01, \
            "Rolling avg on Aug 1 must use July lookback data"


# ================================================================
# Tests for cd.member_network_stats
# ================================================================

class TestMemberNetworkStats:

    def test_view_exists_with_correct_columns(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'cd' AND table_name = 'member_network_stats'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'memid' in columns
        assert 'firstname' in columns
        assert 'surname' in columns
        assert 'direct_referrals' in columns
        assert 'total_network_size' in columns
        assert 'max_depth' in columns
        assert 'network_revenue' in columns

    def test_row_count(self, db):
        """One row per member = 31."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.member_network_stats")
        assert cur.fetchone()[0] == 31

    def test_member1_total_network_size(self, db):
        """Member 1 (Darren Smith) has 10 total descendants."""
        cur = db.cursor()
        cur.execute("SELECT total_network_size FROM cd.member_network_stats WHERE memid = 1")
        assert int(cur.fetchone()[0]) == 10

    def test_member1_direct_referrals(self, db):
        """Member 1 directly recommended 5 members."""
        cur = db.cursor()
        cur.execute("SELECT direct_referrals FROM cd.member_network_stats WHERE memid = 1")
        assert int(cur.fetchone()[0]) == 5

    def test_member1_max_depth(self, db):
        """Member 1's longest chain has depth 3."""
        cur = db.cursor()
        cur.execute("SELECT max_depth FROM cd.member_network_stats WHERE memid = 1")
        assert int(cur.fetchone()[0]) == 3

    def test_member2_network(self, db):
        """Member 2: direct=3, total=4, depth=2."""
        cur = db.cursor()
        cur.execute("""
            SELECT direct_referrals, total_network_size, max_depth
            FROM cd.member_network_stats WHERE memid = 2
        """)
        row = cur.fetchone()
        assert int(row[0]) == 3, "Member 2 direct_referrals should be 3"
        assert int(row[1]) == 4, "Member 2 total_network_size should be 4"
        assert int(row[2]) == 2, "Member 2 max_depth should be 2"

    def test_member6_network(self, db):
        """Member 6: direct=1, total=4, depth=3."""
        cur = db.cursor()
        cur.execute("""
            SELECT direct_referrals, total_network_size, max_depth
            FROM cd.member_network_stats WHERE memid = 6
        """)
        row = cur.fetchone()
        assert int(row[0]) == 1, "Member 6 direct_referrals should be 1"
        assert int(row[1]) == 4, "Member 6 total_network_size should be 4"
        assert int(row[2]) == 3, "Member 6 max_depth should be 3"

    def test_guest_has_no_network(self, db):
        """Guest (memid=0) recommended nobody."""
        cur = db.cursor()
        cur.execute("""
            SELECT direct_referrals, total_network_size, max_depth
            FROM cd.member_network_stats WHERE memid = 0
        """)
        row = cur.fetchone()
        assert int(row[0]) == 0
        assert int(row[1]) == 0
        assert int(row[2]) == 0

    def test_network_revenue_member1_positive(self, db):
        """Member 1 has descendants who made bookings, so network_revenue > 0."""
        cur = db.cursor()
        cur.execute("SELECT network_revenue FROM cd.member_network_stats WHERE memid = 1")
        assert float(cur.fetchone()[0]) > 0

    def test_network_revenue_guest_zero(self, db):
        """Guest has no network, so network_revenue = 0."""
        cur = db.cursor()
        cur.execute("SELECT network_revenue FROM cd.member_network_stats WHERE memid = 0")
        assert float(cur.fetchone()[0]) == 0

    def test_direct_le_total(self, db):
        """Direct referrals must be <= total network size for all members."""
        cur = db.cursor()
        cur.execute("""
            SELECT memid, direct_referrals, total_network_size
            FROM cd.member_network_stats
        """)
        for row in cur.fetchall():
            memid, direct, total = int(row[0]), int(row[1]), int(row[2])
            assert direct <= total, \
                f"Member {memid}: direct ({direct}) > total ({total})"

    def test_network_revenue_consistency(self, db):
        """Member 1's network_revenue should be >= member 5's network_revenue
        since member 5's network is a subset of member 1's network."""
        cur = db.cursor()
        cur.execute("""
            SELECT memid, network_revenue::float
            FROM cd.member_network_stats
            WHERE memid IN (1, 5)
            ORDER BY memid
        """)
        rows = cur.fetchall()
        rev1 = rows[0][1]
        rev5 = rows[1][1]
        assert rev1 >= rev5, \
            f"Member 1's network_revenue ({rev1}) should be >= member 5's ({rev5})"

    def test_network_revenue_matches_independent_calc(self, db):
        """Cross-check member 1's network_revenue against independent SQL calculation."""
        cur = db.cursor()
        # Independently compute network revenue for member 1 using the known descendants
        cur.execute("""
            WITH RECURSIVE tree AS (
                SELECT memid AS descendant FROM cd.members WHERE recommendedby = 1
                UNION ALL
                SELECT m.memid FROM cd.members m JOIN tree t ON m.recommendedby = t.descendant
            )
            SELECT COALESCE(SUM(
                CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                     ELSE b.slots * f.membercost END
            ), 0)::float
            FROM tree t
            JOIN cd.bookings b ON b.memid = t.descendant
            JOIN cd.facilities f ON f.facid = b.facid
        """)
        expected = cur.fetchone()[0]
        cur.execute("SELECT network_revenue::float FROM cd.member_network_stats WHERE memid = 1")
        actual = cur.fetchone()[0]
        assert abs(actual - expected) < 0.01, \
            f"Member 1 network_revenue: expected {expected}, got {actual}"


# ================================================================
# Tests for cd.facility_monthly_analysis
# ================================================================

class TestFacilityMonthlyAnalysis:

    def test_view_exists_with_correct_columns(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'cd' AND table_name = 'facility_monthly_analysis'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'facility_name' in columns
        assert 'month' in columns
        assert 'total_revenue' in columns
        assert 'utilization_pct' in columns
        assert 'revenue_rank' in columns
        assert 'prev_month_revenue' in columns
        assert 'growth_pct' in columns
        assert 'category' in columns

    def test_row_count(self, db):
        """9 facilities * 3 months + 1 (Pool Table in Jan 2013) = 28 rows."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.facility_monthly_analysis")
        assert cur.fetchone()[0] == 28

    def test_utilization_badminton_july(self, db):
        """Badminton Court July 2012 utilization = 23.2%."""
        cur = db.cursor()
        cur.execute("""
            SELECT utilization_pct FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Badminton Court' AND month = '2012-07-01'
        """)
        assert float(cur.fetchone()[0]) == 23.2

    def test_utilization_massage1_august(self, db):
        """Massage Room 1 August 2012 utilization = 63.5%."""
        cur = db.cursor()
        cur.execute("""
            SELECT utilization_pct FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Massage Room 1' AND month = '2012-08-01'
        """)
        assert float(cur.fetchone()[0]) == 63.5

    def test_utilization_squash_september(self, db):
        """Squash Court September 2012 utilization = 72.0%."""
        cur = db.cursor()
        cur.execute("""
            SELECT utilization_pct FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Squash Court' AND month = '2012-09-01'
        """)
        assert float(cur.fetchone()[0]) == 72.0

    def test_utilization_tennis1_july(self, db):
        """Tennis Court 1 July 2012 utilization = 34.8%."""
        cur = db.cursor()
        cur.execute("""
            SELECT utilization_pct FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Tennis Court 1' AND month = '2012-07-01'
        """)
        assert float(cur.fetchone()[0]) == 34.8

    def test_utilization_pool_january(self, db):
        """Pool Table January 2013 utilization = 0.1%."""
        cur = db.cursor()
        cur.execute("""
            SELECT utilization_pct FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Pool Table' AND month = '2013-01-01'
        """)
        assert float(cur.fetchone()[0]) == 0.1

    def test_prev_month_revenue_populated(self, db):
        """August and September rows should have prev_month_revenue filled in."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.facility_monthly_analysis
            WHERE month >= '2012-08-01' AND month <= '2012-09-01'
            AND prev_month_revenue IS NOT NULL
        """)
        assert cur.fetchone()[0] == 18

    def test_growth_pct_computed(self, db):
        """growth_pct must be non-null when prev_month_revenue exists and > 0."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.facility_monthly_analysis
            WHERE prev_month_revenue IS NOT NULL AND prev_month_revenue > 0
            AND growth_pct IS NOT NULL
        """)
        assert cur.fetchone()[0] >= 18

    def test_july_has_no_prev(self, db):
        """July rows should have NULL prev_month_revenue (no prior data)."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.facility_monthly_analysis
            WHERE month = '2012-07-01' AND prev_month_revenue IS NULL
        """)
        assert cur.fetchone()[0] == 9

    def test_category_values(self, db):
        """Must have all three category values."""
        cur = db.cursor()
        cur.execute("SELECT DISTINCT category FROM cd.facility_monthly_analysis")
        categories = {row[0] for row in cur.fetchall()}
        assert categories == {'high', 'medium', 'low'}

    def test_category_distribution_per_month(self, db):
        """In months with 9 facilities, each NTILE(3) group should have 3 members."""
        cur = db.cursor()
        cur.execute("""
            SELECT month, category, COUNT(*)
            FROM cd.facility_monthly_analysis
            GROUP BY month, category
            ORDER BY month, category
        """)
        for row in cur.fetchall():
            month, category, count = row
            if str(month).startswith('2012'):
                assert int(count) == 3, \
                    f"Month {month}, category '{category}' should have 3 facilities, got {count}"

    def test_revenue_rank_starts_at_1(self, db):
        """Each month should have at least one facility ranked 1."""
        cur = db.cursor()
        cur.execute("""
            SELECT month, MIN(revenue_rank)
            FROM cd.facility_monthly_analysis
            GROUP BY month
        """)
        for row in cur.fetchall():
            assert int(row[1]) == 1, f"Month {row[0]} should have rank 1"

    def test_growth_pct_value_spot_check(self, db):
        """Verify growth_pct calculation for a specific facility independently."""
        cur = db.cursor()
        cur.execute("""
            SELECT total_revenue::float FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Badminton Court' AND month = '2012-07-01'
        """)
        jul_rev = cur.fetchone()[0]
        cur.execute("""
            SELECT total_revenue::float, prev_month_revenue::float, growth_pct::float
            FROM cd.facility_monthly_analysis
            WHERE facility_name = 'Badminton Court' AND month = '2012-08-01'
        """)
        row = cur.fetchone()
        aug_rev, prev_rev, growth = row[0], row[1], row[2]
        assert abs(prev_rev - jul_rev) < 0.01, \
            f"prev_month_revenue for Aug should equal Jul revenue: expected {jul_rev}, got {prev_rev}"
        expected_growth = round(((aug_rev - jul_rev) / jul_rev) * 100, 1)
        assert abs(growth - expected_growth) < 0.1, \
            f"growth_pct: expected {expected_growth}, got {growth}"


# ================================================================
# Tests for cd.booking_anomaly_report
# ================================================================

class TestBookingAnomalyReport:

    def test_view_exists_with_correct_columns(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'cd' AND table_name = 'booking_anomaly_report'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'facility_name' in columns
        assert 'facid' in columns
        assert 'date' in columns
        assert 'revenue' in columns
        assert 'zscore' in columns
        assert 'anomaly_type' in columns
        assert 'dominant_booker' in columns
        assert 'dominant_pct' in columns

    def test_not_empty(self, db):
        """The view should have rows — anomalies exist in the data."""
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM cd.booking_anomaly_report")
        count = cur.fetchone()[0]
        assert count > 0, "View should not be empty — anomalies exist in Aug-Sep 2012"

    def test_all_rows_have_high_zscore(self, db):
        """Every row must have |zscore| > 1.5."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report
            WHERE ABS(zscore) <= 1.5
        """)
        assert cur.fetchone()[0] == 0, "All rows must have |zscore| > 1.5"

    def test_anomaly_type_consistency(self, db):
        """spike when zscore > 0, dip when zscore < 0."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report
            WHERE (zscore > 0 AND anomaly_type != 'spike')
               OR (zscore < 0 AND anomaly_type != 'dip')
        """)
        assert cur.fetchone()[0] == 0, "anomaly_type must match zscore sign"

    def test_has_both_spikes_and_dips(self, db):
        """Data should contain both spike and dip anomalies."""
        cur = db.cursor()
        cur.execute("SELECT DISTINCT anomaly_type FROM cd.booking_anomaly_report ORDER BY anomaly_type")
        types = [row[0] for row in cur.fetchall()]
        assert 'spike' in types, "Should have spike anomalies"
        assert 'dip' in types, "Should have dip anomalies"

    def test_dominant_pct_range(self, db):
        """dominant_pct should be between 0 and 100 when not NULL."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report
            WHERE dominant_pct IS NOT NULL AND (dominant_pct < 0 OR dominant_pct > 100)
        """)
        assert cur.fetchone()[0] == 0

    def test_date_range(self, db):
        """All dates should be in Aug-Sep 2012."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report
            WHERE date < '2012-08-01' OR date >= '2012-10-01'
        """)
        assert cur.fetchone()[0] == 0

    def test_dominant_booker_not_null(self, db):
        """dominant_booker should not be null for rows with revenue > 0."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report
            WHERE revenue > 0 AND dominant_booker IS NULL
        """)
        assert cur.fetchone()[0] == 0

    def test_revenue_matches_rolling_stats(self, db):
        """Revenue in anomaly report should match revenue_rolling_stats."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.booking_anomaly_report a
            JOIN cd.revenue_rolling_stats r ON r.facid = a.facid AND r.date = a.date
            WHERE ABS(a.revenue - r.revenue) > 0.01
        """)
        assert cur.fetchone()[0] == 0, "Revenue must match revenue_rolling_stats"

    def test_row_count_matches_filtered_rolling_stats(self, db):
        """Row count must equal number of rows in revenue_rolling_stats with |zscore| > 1.5."""
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM cd.revenue_rolling_stats WHERE ABS(zscore) > 1.5
        """)
        expected = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM cd.booking_anomaly_report")
        actual = cur.fetchone()[0]
        assert actual == expected, f"Expected {expected} anomaly rows, got {actual}"

    def test_dominant_is_highest_revenue_contributor(self, db):
        """The dominant booker must be the member with highest revenue for that (facility, date)."""
        cur = db.cursor()
        cur.execute("""
            WITH booking_rev AS (
                SELECT
                    b.facid, CAST(b.starttime AS date) AS bdate, b.memid,
                    SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                             ELSE b.slots * f.membercost END) AS member_revenue
                FROM cd.bookings b
                JOIN cd.facilities f ON f.facid = b.facid
                WHERE CAST(b.starttime AS date) >= '2012-08-01'
                  AND CAST(b.starttime AS date) < '2012-10-01'
                GROUP BY b.facid, CAST(b.starttime AS date), b.memid
            ),
            ranked AS (
                SELECT facid, bdate, memid, member_revenue,
                    ROW_NUMBER() OVER (
                        PARTITION BY facid, bdate
                        ORDER BY member_revenue DESC, memid
                    ) AS rn
                FROM booking_rev
            ),
            expected AS (
                SELECT r.facid, r.bdate,
                    CASE WHEN r.memid = 0 THEN 'GUEST'
                         ELSE m.firstname || ' ' || m.surname END AS expected_booker
                FROM ranked r
                LEFT JOIN cd.members m ON m.memid = r.memid
                WHERE r.rn = 1
            )
            SELECT COUNT(*)
            FROM cd.booking_anomaly_report a
            JOIN expected e ON e.facid = a.facid AND e.bdate = a.date
            WHERE a.dominant_booker != e.expected_booker
        """)
        mismatches = cur.fetchone()[0]
        assert mismatches == 0, f"{mismatches} rows have wrong dominant_booker"

    def test_dominant_pct_computation(self, db):
        """Verify dominant_pct is correctly computed as percentage of daily revenue."""
        cur = db.cursor()
        cur.execute("""
            WITH booking_rev AS (
                SELECT
                    b.facid, CAST(b.starttime AS date) AS bdate, b.memid,
                    SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                             ELSE b.slots * f.membercost END) AS member_revenue
                FROM cd.bookings b
                JOIN cd.facilities f ON f.facid = b.facid
                WHERE CAST(b.starttime AS date) >= '2012-08-01'
                  AND CAST(b.starttime AS date) < '2012-10-01'
                GROUP BY b.facid, CAST(b.starttime AS date), b.memid
            ),
            ranked AS (
                SELECT facid, bdate, memid, member_revenue,
                    ROW_NUMBER() OVER (
                        PARTITION BY facid, bdate
                        ORDER BY member_revenue DESC, memid
                    ) AS rn
                FROM booking_rev
            )
            SELECT COUNT(*)
            FROM cd.booking_anomaly_report a
            JOIN ranked r ON r.facid = a.facid AND r.bdate = a.date AND r.rn = 1
            WHERE a.revenue > 0
              AND ABS(a.dominant_pct - ROUND(100.0 * r.member_revenue / a.revenue, 1)) > 0.1
        """)
        mismatches = cur.fetchone()[0]
        assert mismatches == 0, f"{mismatches} rows have incorrect dominant_pct"


# ================================================================
# Tests for cd.member_value_score function
# ================================================================

class TestMemberValueScore:

    def test_function_exists(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.routines
            WHERE routine_schema = 'cd' AND routine_name = 'member_value_score'
        """)
        assert cur.fetchone()[0] == 1, "Function cd.member_value_score must exist"

    def test_returns_numeric(self, db):
        cur = db.cursor()
        cur.execute("SELECT cd.member_value_score(1)")
        result = cur.fetchone()[0]
        assert result is not None, "Function should return a value for member 1"
        float(result)  # Should not raise

    def test_no_crash_all_members(self, db):
        """Function should not crash for any member (GREATEST prevents division by zero)."""
        cur = db.cursor()
        cur.execute("SELECT memid FROM cd.members")
        for row in cur.fetchall():
            memid = row[0]
            cur.execute(f"SELECT cd.member_value_score({memid})")
            result = cur.fetchone()[0]
            assert result is not None, f"member_value_score({memid}) returned NULL"

    def test_uses_membercost_for_members(self, db):
        """A regular member's direct_revenue must use membercost, not guestcost."""
        cur = db.cursor()
        # Compute expected value for member 1 using membercost
        cur.execute("""
            WITH vals AS (
                SELECT
                    COALESCE((SELECT SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                                              ELSE b.slots * f.membercost END)
                              FROM cd.bookings b JOIN cd.facilities f ON f.facid = b.facid
                              WHERE b.memid = 1), 0) AS direct,
                    COALESCE((SELECT network_revenue FROM cd.member_network_stats WHERE memid = 1), 0) AS net_rev,
                    GREATEST((SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
                                     EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
                              FROM cd.members WHERE memid = 1), 1) AS tenure
            )
            SELECT ROUND((direct + 0.5 * net_rev) / tenure, 2) FROM vals
        """)
        expected = float(cur.fetchone()[0])

        # Compute what the wrong answer would be using guestcost for all
        cur.execute("""
            WITH vals AS (
                SELECT
                    COALESCE((SELECT SUM(b.slots * f.guestcost)
                              FROM cd.bookings b JOIN cd.facilities f ON f.facid = b.facid
                              WHERE b.memid = 1), 0) AS direct_wrong,
                    COALESCE((SELECT network_revenue FROM cd.member_network_stats WHERE memid = 1), 0) AS net_rev,
                    GREATEST((SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
                                     EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
                              FROM cd.members WHERE memid = 1), 1) AS tenure
            )
            SELECT ROUND((direct_wrong + 0.5 * net_rev) / tenure, 2) FROM vals
        """)
        wrong_val = float(cur.fetchone()[0])

        cur.execute("SELECT cd.member_value_score(1)")
        actual = float(cur.fetchone()[0])

        assert actual == expected, \
            f"Member 1: expected {expected} (using membercost), got {actual}." + \
            (f" Value {wrong_val} suggests guestcost is being used instead." if abs(actual - wrong_val) < 0.01 else "")

    def test_network_revenue_half_weight(self, db):
        """Network revenue should be weighted at 0.5, not 1.0."""
        cur = db.cursor()
        cur.execute("""
            WITH vals AS (
                SELECT
                    COALESCE((SELECT SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                                              ELSE b.slots * f.membercost END)
                              FROM cd.bookings b JOIN cd.facilities f ON f.facid = b.facid
                              WHERE b.memid = 1), 0) AS direct,
                    COALESCE((SELECT network_revenue FROM cd.member_network_stats WHERE memid = 1), 0) AS net_rev,
                    GREATEST((SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
                                     EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
                              FROM cd.members WHERE memid = 1), 1) AS tenure
            )
            SELECT
                ROUND((direct + 0.5 * net_rev) / tenure, 2) AS expected_half,
                ROUND((direct + 1.0 * net_rev) / tenure, 2) AS expected_full
            FROM vals
        """)
        row = cur.fetchone()
        expected_half = float(row[0])
        expected_full = float(row[1])
        cur.execute("SELECT cd.member_value_score(1)")
        actual = float(cur.fetchone()[0])
        assert actual == expected_half, \
            f"Expected {expected_half} (0.5x network weight), got {actual}. " + \
            (f"Value matches 1.0x weight ({expected_full}) — use 0.5 factor." if abs(actual - expected_full) < 0.01 else "")

    def test_tenure_uses_fixed_date(self, db):
        """Tenure must be calculated relative to 2013-02-01, not CURRENT_DATE."""
        cur = db.cursor()
        cur.execute("""
            SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
                   EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
            FROM cd.members WHERE memid = 1
        """)
        fixed_tenure = int(cur.fetchone()[0])

        cur.execute("""
            SELECT EXTRACT(YEAR FROM AGE(CURRENT_DATE, joindate)) * 12 +
                   EXTRACT(MONTH FROM AGE(CURRENT_DATE, joindate))
            FROM cd.members WHERE memid = 1
        """)
        current_tenure = int(cur.fetchone()[0])

        # These must be very different (data is from 2012)
        assert current_tenure > fixed_tenure + 100, \
            "Sanity: CURRENT_DATE tenure should be >> 2013-02-01 tenure"

        # Compute expected with fixed date
        cur.execute("""
            WITH vals AS (
                SELECT
                    COALESCE((SELECT SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                                              ELSE b.slots * f.membercost END)
                              FROM cd.bookings b JOIN cd.facilities f ON f.facid = b.facid
                              WHERE b.memid = 1), 0) AS direct,
                    COALESCE((SELECT network_revenue FROM cd.member_network_stats WHERE memid = 1), 0) AS net_rev
            )
            SELECT
                ROUND((direct + 0.5 * net_rev) / GREATEST(%s, 1), 2),
                ROUND((direct + 0.5 * net_rev) / GREATEST(%s, 1), 2)
            FROM vals
        """, (fixed_tenure, current_tenure))
        row = cur.fetchone()
        expected_fixed = float(row[0])
        expected_current = float(row[1])

        cur.execute("SELECT cd.member_value_score(1)")
        actual = float(cur.fetchone()[0])
        assert actual == expected_fixed, \
            f"Expected {expected_fixed} (tenure to 2013-02-01), got {actual}. " + \
            (f"Value {expected_current} suggests CURRENT_DATE is being used." if abs(actual - expected_current) < 0.01 else "")

    def test_guest_value_score(self, db):
        """Guest (memid=0) should have valid score using guestcost and zero network_revenue."""
        cur = db.cursor()
        cur.execute("""
            WITH vals AS (
                SELECT
                    COALESCE((SELECT SUM(b.slots * f.guestcost)
                              FROM cd.bookings b JOIN cd.facilities f ON f.facid = b.facid
                              WHERE b.memid = 0), 0) AS direct,
                    GREATEST((SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
                                     EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
                              FROM cd.members WHERE memid = 0), 1) AS tenure
            )
            SELECT ROUND(direct / tenure, 2) FROM vals
        """)
        expected = float(cur.fetchone()[0])
        cur.execute("SELECT cd.member_value_score(0)")
        actual = float(cur.fetchone()[0])
        assert actual == expected, f"Guest value: expected {expected}, got {actual}"
