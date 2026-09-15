
import subprocess
import pytest


def run_sql(sql):
    """Execute SQL via psql and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        [
            "psql",
            "-U", "postgres",
            "-d", "transit_db",
            "-t", "-A", "-F", "\t",
            "-c", sql,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout, result.stderr, result.returncode


def query(sql):
    """Execute SQL and return list of row tuples (strings)."""
    stdout, stderr, rc = run_sql(sql)
    if rc != 0:
        raise RuntimeError(f"Query failed (rc={rc}): {stderr.strip()}")
    lines = [line for line in stdout.strip().split("\n") if line.strip()]
    if not lines:
        return []
    return [tuple(col for col in line.split("\t")) for line in lines]


# ---------------------------------------------------------------------------
# v_reachable: recursive CTE finding reachable stations from station 1
# ---------------------------------------------------------------------------
class TestVReachable:
    def test_view_queryable(self):
        rows = query("SELECT count(*) FROM v_reachable")
        assert len(rows) == 1

    def test_all_six_stations_reachable(self):
        """All 6 stations must be reachable from station 1."""
        rows = query("SELECT station_id FROM v_reachable ORDER BY station_id")
        ids = [int(r[0]) for r in rows]
        assert ids == [1, 2, 3, 4, 5, 6], f"Expected [1..6], got {ids}"

    def test_source_station_zero_hops(self):
        rows = query(
            "SELECT hops, total_distance FROM v_reachable WHERE station_id = 1"
        )
        assert len(rows) == 1
        hops = int(float(rows[0][0]))
        dist = float(rows[0][1])
        assert hops == 0
        assert dist == 0.0

    def test_direct_neighbor_station2(self):
        rows = query(
            "SELECT hops, total_distance FROM v_reachable WHERE station_id = 2"
        )
        assert len(rows) == 1
        hops = int(float(rows[0][0]))
        dist = float(rows[0][1])
        assert hops == 1, f"Station 2 hops should be 1, got {hops}"
        assert abs(dist - 5.0) < 0.01, f"Station 2 dist should be 5.0, got {dist}"

    def test_direct_neighbor_station3(self):
        rows = query(
            "SELECT hops, total_distance FROM v_reachable WHERE station_id = 3"
        )
        assert len(rows) == 1
        hops = int(float(rows[0][0]))
        assert hops == 1
        assert abs(float(rows[0][1]) - 3.0) < 0.01

    def test_multi_hop_station4(self):
        """Station 4 is reachable via 1->3->5->4 (3 hops, dist 12.5)."""
        rows = query(
            "SELECT hops, total_distance FROM v_reachable WHERE station_id = 4"
        )
        assert len(rows) == 1
        hops = int(float(rows[0][0]))
        dist = float(rows[0][1])
        assert hops == 3, f"Station 4 hops should be 3, got {hops}"
        assert abs(dist - 12.5) < 0.01, f"Station 4 dist should be 12.5, got {dist}"

    def test_station6_reachable_via_station2(self):
        """Station 6 is only reachable via 1->2->6 (2 hops, dist 11.0)."""
        rows = query(
            "SELECT hops, total_distance FROM v_reachable WHERE station_id = 6"
        )
        assert len(rows) == 1
        hops = int(float(rows[0][0]))
        dist = float(rows[0][1])
        assert hops == 2, f"Station 6 hops should be 2, got {hops}"
        assert abs(dist - 11.0) < 0.01

    def test_hops_are_integers(self):
        rows = query("SELECT hops FROM v_reachable")
        for r in rows:
            val = float(r[0])
            assert val == int(val), f"Hops must be integer, got {val}"


# ---------------------------------------------------------------------------
# v_all_paths: all simple paths from station 1
# ---------------------------------------------------------------------------
class TestVAllPaths:
    def test_view_queryable(self):
        rows = query("SELECT count(*) FROM v_all_paths")
        assert len(rows) == 1

    def test_exactly_five_paths(self):
        """There are exactly 5 simple paths from station 1 within 4 hops."""
        count = int(query("SELECT count(*) FROM v_all_paths")[0][0])
        assert count == 5, f"Expected 5 paths, got {count}"

    def test_no_duplicate_stations_in_path(self):
        rows = query(
            """
            SELECT path FROM v_all_paths
            WHERE array_length(path, 1) <>
                  (SELECT count(DISTINCT x) FROM unnest(path) x)
            """
        )
        assert len(rows) == 0, f"Paths with duplicate stations: {rows}"

    def test_paths_start_with_source(self):
        rows = query("SELECT path FROM v_all_paths")
        for r in rows:
            path = [int(x) for x in r[0].strip("{}").split(",")]
            assert path[0] == 1, f"Path should start with 1, got {path}"

    def test_path_ends_with_dst(self):
        rows = query("SELECT dst, path FROM v_all_paths")
        for r in rows:
            dst = int(r[0])
            path = [int(x) for x in r[1].strip("{}").split(",")]
            assert path[-1] == dst, f"Path should end with dst={dst}, got {path}"

    def test_path_length_equals_hops_plus_one(self):
        rows = query("SELECT hops, array_length(path, 1) FROM v_all_paths")
        for r in rows:
            hops = int(r[0])
            plen = int(r[1])
            assert plen == hops + 1, (
                f"Path length should be hops+1={hops + 1}, got {plen}"
            )

    def test_longest_path(self):
        rows = query(
            "SELECT total_dist FROM v_all_paths WHERE path = ARRAY[1,3,5,4]"
        )
        assert len(rows) == 1, "Path [1,3,5,4] should exist"
        assert abs(float(rows[0][0]) - 12.5) < 0.01


# ---------------------------------------------------------------------------
# v_capacity_forecast: Fibonacci-like sequence
# ---------------------------------------------------------------------------
class TestVCapacityForecast:
    def test_ten_rows(self):
        assert int(query("SELECT count(*) FROM v_capacity_forecast")[0][0]) == 10

    def test_step1(self):
        rows = query(
            "SELECT capacity FROM v_capacity_forecast WHERE step = 1"
        )
        assert int(rows[0][0]) == 100

    def test_step2(self):
        """Step 2: 100 + 0 = 100."""
        rows = query(
            "SELECT capacity FROM v_capacity_forecast WHERE step = 2"
        )
        assert int(rows[0][0]) == 100

    def test_step10(self):
        """Step 10 of Fibonacci(100,0): 5500."""
        rows = query(
            "SELECT capacity FROM v_capacity_forecast WHERE step = 10"
        )
        assert int(rows[0][0]) == 5500, (
            f"Step 10 should be 5500, got {rows[0][0]}"
        )

    def test_fibonacci_property(self):
        """Each capacity = sum of previous two capacities (for step >= 3)."""
        rows = query(
            "SELECT step, capacity FROM v_capacity_forecast ORDER BY step"
        )
        caps = [int(r[1]) for r in rows]
        for i in range(2, len(caps)):
            expected = caps[i - 1] + caps[i - 2]
            assert caps[i] == expected, (
                f"Step {i + 1}: expected {expected}, got {caps[i]}"
            )


# ---------------------------------------------------------------------------
# v_cumulative_stats: window functions (cumulative, moving avg, percentile)
# ---------------------------------------------------------------------------
class TestVCumulativeStats:
    def test_view_queryable(self):
        rows = query("SELECT count(*) FROM v_cumulative_stats")
        assert len(rows) == 1

    def test_cumulative_nondecreasing(self):
        rows = query(
            """
            SELECT cumulative_passengers
            FROM v_cumulative_stats
            WHERE station_id = 1
            ORDER BY ride_date, hour
            """
        )
        vals = [int(r[0]) for r in rows]
        for i in range(1, len(vals)):
            assert vals[i] >= vals[i - 1], "Cumulative sum must not decrease"

    def test_moving_avg_is_three_row_window(self):
        """
        Station 1 last record: revenues are 7500, 9000, 7800, 8700, 7650, 9300.
        3-row moving avg at last record = avg(8700, 7650, 9300) = 8550.
        Running avg of all 6 = avg(49950/6) = 8325.
        """
        rows = query(
            """
            SELECT moving_avg_revenue
            FROM v_cumulative_stats
            WHERE station_id = 1
            ORDER BY ride_date DESC, hour DESC
            LIMIT 1
            """
        )
        val = float(rows[0][0])
        expected_3row = (8700 + 7650 + 9300) / 3  # 8550
        assert abs(val - expected_3row) < 1.0, (
            f"Moving avg should be ~{expected_3row:.0f} (3-row), got {val:.2f}"
        )

    def test_moving_avg_first_record(self):
        """First record window has only 1 row: avg = the row's own revenue."""
        rows = query(
            """
            SELECT moving_avg_revenue
            FROM v_cumulative_stats
            WHERE station_id = 1
            ORDER BY ride_date, hour
            LIMIT 1
            """
        )
        assert abs(float(rows[0][0]) - 7500.0) < 1.0

    def test_moving_avg_second_record(self):
        """Second record window: avg of first 2 revenues = (7500+9000)/2."""
        rows = query(
            """
            SELECT moving_avg_revenue
            FROM v_cumulative_stats
            WHERE station_id = 1
            ORDER BY ride_date, hour
            OFFSET 1 LIMIT 1
            """
        )
        assert abs(float(rows[0][0]) - 8250.0) < 1.0

    def test_percentile_range(self):
        """All revenue_percentile values must be between 0.0 and 1.0."""
        rows = query("SELECT revenue_percentile FROM v_cumulative_stats")
        for r in rows:
            val = float(r[0])
            assert 0.0 <= val <= 1.0, (
                f"Percentile must be in [0, 1], got {val}"
            )

    def test_percentile_min_station1(self):
        """Station 1 lowest revenue (7500) should have percentile = 0.0."""
        rows = query(
            """
            SELECT revenue_percentile FROM v_cumulative_stats
            WHERE station_id = 1 AND fare_revenue = 7500.00
            """
        )
        assert len(rows) >= 1
        assert abs(float(rows[0][0]) - 0.0) < 0.01

    def test_percentile_max_station1(self):
        """Station 1 highest revenue (9300) should have percentile = 1.0."""
        rows = query(
            """
            SELECT revenue_percentile FROM v_cumulative_stats
            WHERE station_id = 1 AND fare_revenue = 9300.00
            """
        )
        assert len(rows) >= 1
        assert abs(float(rows[0][0]) - 1.0) < 0.01

    def test_percentile_mid_station1(self):
        """Station 1 revenue=8700: PERCENT_RANK = 3/5 = 0.6."""
        rows = query(
            """
            SELECT revenue_percentile FROM v_cumulative_stats
            WHERE station_id = 1 AND fare_revenue = 8700.00
            """
        )
        assert len(rows) >= 1
        assert abs(float(rows[0][0]) - 0.6) < 0.05


# ---------------------------------------------------------------------------
# v_pct_change: day-over-day percentage change
# ---------------------------------------------------------------------------
class TestVPctChange:
    def test_view_queryable(self):
        rows = query("SELECT count(*) FROM v_pct_change")
        assert len(rows) == 1

    def test_first_day_is_null(self):
        rows = query(
            """
            SELECT CASE WHEN pct_change IS NULL THEN 'NULL' ELSE 'NOTNULL' END
            FROM v_pct_change
            WHERE station_id = 1
            ORDER BY ride_date
            LIMIT 1
            """
        )
        assert rows[0][0] == "NULL", "First day pct_change must be NULL"

    def test_station1_day2_zero_change(self):
        """Station 1: day1=1100, day2=1100 -> 0.0%."""
        rows = query(
            """
            SELECT pct_change FROM v_pct_change
            WHERE station_id = 1 AND ride_date = '2024-01-02'
            """
        )
        assert len(rows) == 1
        val = float(rows[0][0])
        assert abs(val - 0.0) < 0.2, (
            f"Station 1 day 2: expected 0.0%, got {val}%"
        )

    def test_station1_day3(self):
        """Station 1: day2=1100, day3=1130 -> 2.7%."""
        rows = query(
            """
            SELECT pct_change FROM v_pct_change
            WHERE station_id = 1 AND ride_date = '2024-01-03'
            """
        )
        assert len(rows) == 1
        val = float(rows[0][0])
        assert abs(val - 2.7) < 0.2, (
            f"Station 1 day 3: expected ~2.7%, got {val}%"
        )

    def test_station5_day2_per_station(self):
        """Station 5: day1=150, day2=160 -> 6.7%. Verifies per-station isolation."""
        rows = query(
            """
            SELECT pct_change FROM v_pct_change
            WHERE station_id = 5 AND ride_date = '2024-01-02'
            """
        )
        assert len(rows) == 1
        val = float(rows[0][0])
        assert abs(val - 6.7) < 0.2, (
            f"Station 5 day 2: expected ~6.7%, got {val}%"
        )

    def test_station2_day3(self):
        """Station 2: day2=650, day3=320 -> pct_change = -50.8%."""
        rows = query(
            """
            SELECT pct_change FROM v_pct_change
            WHERE station_id = 2 AND ride_date = '2024-01-03'
            """
        )
        assert len(rows) == 1
        val = float(rows[0][0])
        assert abs(val - (-50.8)) < 0.2, (
            f"Station 2 day 3: expected ~-50.8%, got {val}%"
        )


# ---------------------------------------------------------------------------
# v_zone_crossflow: inter-zone flow via connections with CUBE aggregation
# ---------------------------------------------------------------------------
class TestVZoneCrossflow:
    def test_view_queryable(self):
        try:
            rows = query("SELECT count(*) FROM v_zone_crossflow")
        except RuntimeError as e:
            pytest.fail(f"v_zone_crossflow is not queryable: {e}")
        assert len(rows) == 1

    def test_cube_row_count(self):
        """CUBE(origin_zone, dest_zone) with 6 zone pairs = 13 rows total."""
        count = int(query("SELECT count(*) FROM v_zone_crossflow")[0][0])
        assert count == 13, f"Expected 13 CUBE rows, got {count}"

    def test_grand_total_flow(self):
        rows = query(
            """
            SELECT total_flow FROM v_zone_crossflow
            WHERE origin_is_agg = 1 AND dest_is_agg = 1
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 14590, (
            f"Grand total flow should be 14590, got {rows[0][0]}"
        )

    def test_grand_total_connections(self):
        rows = query(
            """
            SELECT connection_count FROM v_zone_crossflow
            WHERE origin_is_agg = 1 AND dest_is_agg = 1
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 10, (
            f"Grand total connections should be 10, got {rows[0][0]}"
        )

    def test_downtown_downtown_flow(self):
        """downtown->downtown: 4 connections, flow=5120."""
        rows = query(
            """
            SELECT total_flow, connection_count FROM v_zone_crossflow
            WHERE origin_zone = 'downtown' AND dest_zone = 'downtown'
              AND origin_is_agg = 0 AND dest_is_agg = 0
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 5120, (
            f"downtown->downtown flow should be 5120, got {rows[0][0]}"
        )
        assert int(rows[0][1]) == 4

    def test_uptown_uptown_flow(self):
        """uptown->uptown: 2 connections (2->6, 6->2), flow=2460."""
        rows = query(
            """
            SELECT total_flow, connection_count FROM v_zone_crossflow
            WHERE origin_zone = 'uptown' AND dest_zone = 'uptown'
              AND origin_is_agg = 0 AND dest_is_agg = 0
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 2460
        assert int(rows[0][1]) == 2

    def test_downtown_origin_subtotal(self):
        """Downtown as origin: 6 connections, flow=8900."""
        rows = query(
            """
            SELECT total_flow, connection_count FROM v_zone_crossflow
            WHERE origin_zone = 'downtown' AND origin_is_agg = 0 AND dest_is_agg = 1
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 8900, (
            f"Downtown origin subtotal should be 8900, got {rows[0][0]}"
        )

    def test_downtown_dest_subtotal(self):
        """Downtown as destination: 6 connections, flow=8350."""
        rows = query(
            """
            SELECT total_flow FROM v_zone_crossflow
            WHERE dest_zone = 'downtown' AND origin_is_agg = 1 AND dest_is_agg = 0
            """
        )
        assert len(rows) == 1
        assert int(rows[0][0]) == 8350, (
            f"Downtown dest subtotal should be 8350, got {rows[0][0]}"
        )

    def test_detail_row_count(self):
        """6 distinct zone pairs exist in the connection graph."""
        count = int(query(
            """
            SELECT count(*) FROM v_zone_crossflow
            WHERE origin_is_agg = 0 AND dest_is_agg = 0
            """
        )[0][0])
        assert count == 6, f"Expected 6 detail rows, got {count}"

    def test_avg_flow_per_connection_grand(self):
        """Grand total avg: 14590 / 10 = 1459.00."""
        rows = query(
            """
            SELECT avg_flow_per_connection FROM v_zone_crossflow
            WHERE origin_is_agg = 1 AND dest_is_agg = 1
            """
        )
        assert len(rows) == 1
        assert abs(float(rows[0][0]) - 1459.0) < 0.01
