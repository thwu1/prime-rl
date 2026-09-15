
import os
import pytest
import duckdb

TABLES = ["sequential_data", "wide_integers", "text_logs", "sensor_metrics"]

SIZE_TARGETS_BYTES = {
    "sequential_data": 15 * 1024 * 1024,   # 15 MB
    "wide_integers": 45 * 1024 * 1024,     # 45 MB
    "text_logs": 30 * 1024 * 1024,         # 30 MB
    "sensor_metrics": 50 * 1024 * 1024,    # 50 MB
}

ROW_GROUP_RANGES = {
    "sequential_data": (20, 40),
    "sensor_metrics": (25, 70),
}


@pytest.fixture(scope="module")
def db():
    con = duckdb.connect("/app/warehouse.duckdb", read_only=True)
    yield con
    con.close()


# ========== File existence ==========

@pytest.mark.parametrize("table", TABLES)
def test_output_file_exists(table):
    path = f"/app/output/{table}.parquet"
    assert os.path.isfile(path), f"Output file not found: {path}"


# ========== Row count ==========

@pytest.mark.parametrize("table", TABLES)
def test_row_count_matches(table, db):
    expected = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    actual = db.execute(
        f"SELECT COUNT(*) FROM read_parquet('/app/output/{table}.parquet')"
    ).fetchone()[0]
    assert actual == expected, (
        f"{table}: row count {actual} != expected {expected}"
    )


# ========== Column names ==========

@pytest.mark.parametrize("table", TABLES)
def test_column_names_match(table, db):
    expected_cols = sorted(
        [d[0] for d in db.execute(f"SELECT * FROM {table} LIMIT 0").description]
    )
    actual_cols = sorted(
        [
            d[0]
            for d in db.execute(
                f"SELECT * FROM read_parquet('/app/output/{table}.parquet') LIMIT 0"
            ).description
        ]
    )
    assert actual_cols == expected_cols, (
        f"{table}: columns {actual_cols} != expected {expected_cols}"
    )


# ========== Per-column data integrity ==========

@pytest.mark.parametrize("table", TABLES)
def test_per_column_aggregates(table, db):
    """Verify MIN, MAX, and COUNT DISTINCT match for every column."""
    cols_info = db.execute(f"DESCRIBE {table}").fetchall()
    for col_name, col_type, *_ in cols_info:
        expected = db.execute(
            f"SELECT MIN({col_name})::VARCHAR, MAX({col_name})::VARCHAR, "
            f"COUNT(DISTINCT {col_name}) FROM {table}"
        ).fetchone()
        actual = db.execute(
            f"SELECT MIN({col_name})::VARCHAR, MAX({col_name})::VARCHAR, "
            f"COUNT(DISTINCT {col_name}) "
            f"FROM read_parquet('/app/output/{table}.parquet')"
        ).fetchone()
        assert actual == expected, (
            f"{table}.{col_name}: aggregates {actual} != expected {expected}"
        )


# ========== File size targets ==========

@pytest.mark.parametrize("table", TABLES)
def test_file_size_under_target(table):
    path = f"/app/output/{table}.parquet"
    size = os.path.getsize(path)
    target = SIZE_TARGETS_BYTES[table]
    size_mb = size / (1024 * 1024)
    target_mb = target / (1024 * 1024)
    assert size <= target, (
        f"{table}.parquet is {size_mb:.2f} MB, exceeds target of {target_mb:.0f} MB"
    )


# ========== Row group count ==========

@pytest.mark.parametrize("table", ["sequential_data", "sensor_metrics"])
def test_row_group_count_in_range(table, db):
    rg_count = db.execute(f"""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/{table}.parquet')
    """).fetchone()[0]
    lo, hi = ROW_GROUP_RANGES[table]
    assert lo <= rg_count <= hi, (
        f"{table}: {rg_count} row groups, expected between {lo} and {hi}"
    )


# ========== Zone map filtering ==========

def test_zone_map_sequential_data_ts(db):
    """A 2-day window on ts must overlap at most 5 row groups."""
    overlapping = db.execute("""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/sequential_data.parquet')
        WHERE path_in_schema = 'ts'
        AND CAST(stats_min AS TIMESTAMP) <= TIMESTAMP '2024-01-12 00:00:00'
        AND CAST(stats_max AS TIMESTAMP) >= TIMESTAMP '2024-01-10 00:00:00'
    """).fetchone()[0]
    assert overlapping <= 5, (
        f"sequential_data ts zone map: {overlapping} row groups overlap "
        f"a 2-day window (max 5)"
    )


def test_zone_map_wide_integers_score(db):
    """score BETWEEN 5000 AND 6000 must overlap at most 25% of total row groups."""
    total_rgs = db.execute("""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/wide_integers.parquet')
    """).fetchone()[0]
    overlapping = db.execute("""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/wide_integers.parquet')
        WHERE path_in_schema = 'score'
        AND CAST(stats_min AS BIGINT) <= 6000
        AND CAST(stats_max AS BIGINT) >= 5000
    """).fetchone()[0]
    threshold = total_rgs * 0.25
    assert overlapping <= threshold, (
        f"wide_integers score zone map: {overlapping}/{total_rgs} row groups overlap "
        f"score BETWEEN 5000 AND 6000 (max {threshold:.0f}, i.e. 25%)"
    )


def test_zone_map_text_logs_severity(db):
    """severity='CRITICAL' must overlap at most 2 row groups."""
    overlapping = db.execute("""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/text_logs.parquet')
        WHERE path_in_schema = 'severity'
        AND stats_min <= 'CRITICAL'
        AND stats_max >= 'CRITICAL'
    """).fetchone()[0]
    assert overlapping <= 2, (
        f"text_logs severity zone map: {overlapping} row groups overlap "
        f"severity='CRITICAL' (max 2)"
    )


def test_zone_map_sensor_metrics_measured_at(db):
    """A 3-day window on measured_at must overlap at most 10 row groups."""
    overlapping = db.execute("""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/sensor_metrics.parquet')
        WHERE path_in_schema = 'measured_at'
        AND CAST(stats_min AS TIMESTAMP) <= TIMESTAMP '2024-06-04 00:00:00'
        AND CAST(stats_max AS TIMESTAMP) >= TIMESTAMP '2024-06-01 00:00:00'
    """).fetchone()[0]
    assert overlapping <= 10, (
        f"sensor_metrics measured_at zone map: {overlapping} row groups overlap "
        f"a 3-day window (max 10)"
    )


# ========== Parquet readability ==========

@pytest.mark.parametrize("table", TABLES)
def test_parquet_is_readable(table, db):
    """Confirm the file can be fully scanned without errors."""
    count = db.execute(
        f"SELECT COUNT(*) FROM read_parquet('/app/output/{table}.parquet')"
    ).fetchone()[0]
    assert count > 0, f"{table}.parquet is empty or unreadable"
