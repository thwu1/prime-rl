
import json
import os
import re
import sqlite3

import pytest

DB_PATH = "/app/data/warehouse.db"


@pytest.fixture
def conn():
    assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def get_table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def get_column_names(conn, table):
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [r["name"] for r in rows]


# -- 1. Table structure -------------------------------------------------------

def test_main_tables_exist(conn):
    tables = get_table_names(conn)
    for t in ("packages", "authors", "categories", "licenses", "dependencies"):
        assert t in tables, f"Table '{t}' missing. Found: {tables}"


def test_packages_columns(conn):
    cols = set(get_column_names(conn, "packages"))
    required = {
        "id", "name", "version", "description", "homepage", "status", "tags",
        "first_release", "last_update", "monthly_downloads", "daily_avg",
        "trend", "dependency_depth", "author_id", "category_id", "license_id",
    }
    missing = required - cols
    assert not missing, f"Packages table missing columns: {missing}"
    extra = cols - required
    assert not extra, f"Packages table has unexpected columns: {extra}"


def test_packages_primary_key(conn):
    rows = conn.execute("PRAGMA table_info('packages')").fetchall()
    pk_cols = [r for r in rows if r["pk"] > 0]
    assert len(pk_cols) >= 1, "packages has no primary key"
    assert pk_cols[0]["name"] == "id", f"PK column should be 'id', got '{pk_cols[0]['name']}'"
    assert pk_cols[0]["type"].upper() == "INTEGER", "PK should be INTEGER"


def test_authors_columns(conn):
    cols = get_column_names(conn, "authors")
    assert "id" in cols
    assert "name" in cols
    assert "email" in cols


def test_dependencies_columns(conn):
    cols = get_column_names(conn, "dependencies")
    assert "package_id" in cols
    assert "dependency_name" in cols


# -- 2. Row counts ------------------------------------------------------------

def test_packages_count(conn):
    count = conn.execute("SELECT count(*) FROM packages").fetchone()[0]
    assert count == 20, f"Expected 20 packages, got {count}"


def test_authors_count(conn):
    count = conn.execute("SELECT count(*) FROM authors").fetchone()[0]
    assert count == 14, f"Expected 14 authors (Armin Ronacher deduped), got {count}"


def test_categories_count(conn):
    count = conn.execute("SELECT count(*) FROM categories").fetchone()[0]
    assert count == 11, f"Expected 11 categories, got {count}"


def test_licenses_count(conn):
    count = conn.execute("SELECT count(*) FROM licenses").fetchone()[0]
    assert count == 4, f"Expected 4 licenses, got {count}"


def test_dependencies_count(conn):
    count = conn.execute("SELECT count(*) FROM dependencies").fetchone()[0]
    assert count == 43, f"Expected 43 dependency edges, got {count}"


# -- 3. Name normalization -----------------------------------------------------

def test_all_names_lowercase(conn):
    rows = conn.execute("SELECT name FROM packages").fetchall()
    for row in rows:
        assert row["name"] == row["name"].lower(), \
            f"Package name not lowercase: {row['name']}"


# -- 4. Author parsing & deduplication ----------------------------------------

def test_author_parsing(conn):
    row = conn.execute(
        "SELECT name, email FROM authors WHERE name = 'Kenneth Reitz'"
    ).fetchone()
    assert row is not None, "Author 'Kenneth Reitz' not found"
    assert row["email"] == "me@kennethreitz.org"

    row2 = conn.execute(
        "SELECT name, email FROM authors WHERE email = 'aws-sdk-python@amazon.com'"
    ).fetchone()
    assert row2 is not None
    assert row2["name"] == "Amazon Web Services"


def test_author_whitespace_normalization(conn):
    """Double-space 'Armin  Ronacher' must be normalized to single space."""
    row = conn.execute(
        "SELECT count(*) FROM authors WHERE name LIKE '%Armin%Ronacher%'"
    ).fetchone()
    assert row[0] == 1, "Should have exactly one Armin Ronacher author row"

    row2 = conn.execute(
        "SELECT name FROM authors WHERE name LIKE '%Armin%'"
    ).fetchone()
    assert row2["name"] == "Armin Ronacher", \
        f"Author name not normalized: '{row2['name']}'"


def test_shared_author_deduplication(conn):
    """Flask and click share Armin Ronacher -> same author_id."""
    rows = conn.execute(
        "SELECT DISTINCT author_id FROM packages WHERE name IN ('flask', 'click')"
    ).fetchall()
    ids = [r[0] for r in rows]
    assert len(ids) == 1, f"Expected 1 shared author_id for flask+click, got {ids}"


# -- 5. Analytics-only packages -----------------------------------------------

def test_analytics_only_packages(conn):
    """Packages only in downloads source should have NULL metadata but valid analytics."""
    analytics_only = ["uvicorn", "pydantic", "black", "mypy", "ruff"]
    for pkg_name in analytics_only:
        row = conn.execute(
            "SELECT description, homepage, monthly_downloads, daily_avg, trend "
            "FROM packages WHERE name = ?", (pkg_name,)
        ).fetchone()
        assert row is not None, f"Analytics-only package '{pkg_name}' not found"
        assert row["description"] is None, \
            f"{pkg_name} should have NULL description, got '{row['description']}'"
        assert row["homepage"] is None, \
            f"{pkg_name} should have NULL homepage"
        assert row["monthly_downloads"] is not None, \
            f"{pkg_name} should have monthly_downloads"
        assert row["daily_avg"] is not None, \
            f"{pkg_name} should have daily_avg"


def test_analytics_only_first_release(conn):
    """Analytics-only packages should use first_seen as first_release."""
    expected = {
        "uvicorn": "2017-08-15",
        "pydantic": "2017-06-03",
        "black": "2018-03-14",
        "mypy": "2012-12-01",
        "ruff": "2022-08-30",
    }
    for pkg, exp_date in expected.items():
        row = conn.execute(
            "SELECT first_release FROM packages WHERE name = ?", (pkg,)
        ).fetchone()
        assert row is not None, f"Package {pkg} not found"
        assert row[0] == exp_date, \
            f"{pkg}: expected first_release={exp_date}, got {row[0]}"


# -- 6. Data transformations ---------------------------------------------------

def test_dates_iso_format(conn):
    rows = conn.execute(
        "SELECT name, first_release FROM packages WHERE first_release IS NOT NULL"
    ).fetchall()
    assert len(rows) == 20, "All 20 packages should have first_release"
    for row in rows:
        d = row["first_release"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), \
            f"first_release for {row['name']} not ISO date: {d}"


def test_specific_dates(conn):
    expected = {
        "requests": "2011-02-14",
        "flask": "2010-04-01",
        "pandas": "2009-01-11",
        "django": "2005-07-21",
        "fastapi": "2018-12-05",
        "pillow": "2010-07-31",
    }
    for pkg, exp_date in expected.items():
        row = conn.execute(
            "SELECT first_release FROM packages WHERE name = ?", (pkg,)
        ).fetchone()
        assert row is not None, f"Package {pkg} not found"
        assert row[0] == exp_date, \
            f"{pkg}: expected first_release={exp_date}, got {row[0]}"


def test_datetimes_iso_format(conn):
    rows = conn.execute(
        "SELECT name, last_update FROM packages WHERE last_update IS NOT NULL"
    ).fetchall()
    assert len(rows) == 15, "15 registry packages should have last_update"
    for row in rows:
        dt = row["last_update"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", dt), \
            f"last_update for {row['name']} not ISO datetime: {dt}"


def test_downloads_integer_type(conn):
    rows = conn.execute(
        "SELECT typeof(monthly_downloads) as t FROM packages "
        "WHERE monthly_downloads IS NOT NULL"
    ).fetchall()
    for row in rows:
        assert row["t"] == "integer", \
            f"monthly_downloads type should be integer, got {row['t']}"

    val = conn.execute(
        "SELECT monthly_downloads FROM packages WHERE name = 'boto3'"
    ).fetchone()[0]
    assert val == 9876543


def test_tags_json_arrays(conn):
    rows = conn.execute(
        "SELECT name, tags FROM packages WHERE tags IS NOT NULL"
    ).fetchall()
    assert len(rows) == 15, "15 registry packages should have tags"
    for row in rows:
        parsed = json.loads(row["tags"])
        assert isinstance(parsed, list), f"Tags for {row['name']} not a list"
        assert all(isinstance(t, str) for t in parsed)

    req_tags = json.loads(
        conn.execute("SELECT tags FROM packages WHERE name='requests'").fetchone()[0]
    )
    assert set(req_tags) == {"http", "web", "networking"}


# -- 7. Foreign keys -----------------------------------------------------------

def test_foreign_keys(conn):
    fks = conn.execute("PRAGMA foreign_key_list('packages')").fetchall()
    fk_tables = {fk["table"] for fk in fks}
    assert "authors" in fk_tables, f"No FK to authors. FK tables: {fk_tables}"
    assert "categories" in fk_tables, f"No FK to categories. FK tables: {fk_tables}"
    assert "licenses" in fk_tables, f"No FK to licenses. FK tables: {fk_tables}"


def test_dependency_fk(conn):
    fks = conn.execute("PRAGMA foreign_key_list('dependencies')").fetchall()
    fk_tables = {fk["table"] for fk in fks}
    assert "packages" in fk_tables, \
        f"dependencies should have FK to packages. FK tables: {fk_tables}"


def test_fk_referential_integrity(conn):
    orphan_authors = conn.execute(
        "SELECT count(*) FROM packages "
        "WHERE author_id IS NOT NULL AND author_id NOT IN (SELECT id FROM authors)"
    ).fetchone()[0]
    assert orphan_authors == 0, f"{orphan_authors} packages with orphan author_id"

    orphan_cats = conn.execute(
        "SELECT count(*) FROM packages "
        "WHERE category_id IS NOT NULL AND category_id NOT IN (SELECT id FROM categories)"
    ).fetchone()[0]
    assert orphan_cats == 0

    orphan_lics = conn.execute(
        "SELECT count(*) FROM packages "
        "WHERE license_id IS NOT NULL AND license_id NOT IN (SELECT id FROM licenses)"
    ).fetchone()[0]
    assert orphan_lics == 0


# -- 8. Dependency depth -------------------------------------------------------

def test_dependency_depth(conn):
    expected_depths = {
        "click": 0, "numpy": 0, "pillow": 0, "ruff": 0,
        "requests": 1, "flask": 1, "django": 1, "pandas": 1,
        "sqlalchemy": 1, "pytest": 1, "rich": 1, "pydantic": 1,
        "uvicorn": 1, "black": 1, "mypy": 1,
        "fastapi": 2, "scrapy": 2, "celery": 2, "boto3": 2, "httpx": 2,
    }
    for pkg, expected in expected_depths.items():
        row = conn.execute(
            "SELECT dependency_depth FROM packages WHERE name = ?", (pkg,)
        ).fetchone()
        assert row is not None, f"Package {pkg} not found"
        assert row[0] == expected, \
            f"{pkg}: expected dependency_depth={expected}, got {row[0]}"


# -- 9. FTS --------------------------------------------------------------------

def test_fts_configuration(conn):
    fts_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'packages_fts'"
    ).fetchone()
    assert fts_row is not None, "packages_fts table not found"
    schema = fts_row[0].lower()
    assert "fts5" in schema, "FTS table should use FTS5"
    assert "porter" in schema, "FTS table should use porter tokenizer"

    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    trigger_names = [t[0].lower() for t in triggers]
    assert any("insert" in tn or "_ai" in tn for tn in trigger_names), \
        f"No insert trigger found. Triggers: {trigger_names}"
    assert any("delete" in tn or "_ad" in tn for tn in trigger_names), \
        f"No delete trigger found. Triggers: {trigger_names}"


def test_fts_search_results(conn):
    # "framework" appears in descriptions of flask, django, pytest, scrapy, fastapi
    results = conn.execute("""
        SELECT p.name FROM packages p
        JOIN packages_fts ON p.rowid = packages_fts.rowid
        WHERE packages_fts MATCH 'framework'
    """).fetchall()
    names = {r[0] for r in results}
    assert names == {"flask", "django", "pytest", "scrapy", "fastapi"}, \
        f"FTS 'framework' returned {names}"

    # "HTTP" appears in descriptions of requests and httpx
    results2 = conn.execute("""
        SELECT p.name FROM packages p
        JOIN packages_fts ON p.rowid = packages_fts.rowid
        WHERE packages_fts MATCH 'HTTP'
    """).fetchall()
    names2 = {r[0] for r in results2}
    assert names2 == {"requests", "httpx"}, f"FTS 'HTTP' returned {names2}"


# -- 10. View -------------------------------------------------------------------

def test_view_exists(conn):
    view_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='package_intelligence'"
    ).fetchone()
    assert view_row is not None, "View 'package_intelligence' not found"


def test_view_columns_and_data(conn):
    rows = conn.execute("SELECT * FROM package_intelligence").fetchall()
    assert len(rows) == 20

    cols = rows[0].keys()
    for expected_col in (
        "id", "name", "version", "author_name", "author_email",
        "category", "license", "monthly_downloads", "daily_avg", "trend",
        "dependency_depth", "first_release", "last_update",
        "description", "tags", "status", "homepage",
    ):
        assert expected_col in cols, f"View missing column '{expected_col}'"

    # Spot-check: requests should resolve correctly
    req = conn.execute(
        "SELECT author_name, author_email, category, monthly_downloads, dependency_depth "
        "FROM package_intelligence WHERE name='requests'"
    ).fetchone()
    assert req["author_name"] == "Kenneth Reitz"
    assert req["author_email"] == "me@kennethreitz.org"
    assert req["category"] == "Networking"
    assert req["monthly_downloads"] == 5842937
    assert req["dependency_depth"] == 1

    # Spot-check: analytics-only package
    uvi = conn.execute(
        "SELECT author_name, description, monthly_downloads, dependency_depth "
        "FROM package_intelligence WHERE name='uvicorn'"
    ).fetchone()
    assert uvi["author_name"] is None
    assert uvi["description"] is None
    assert uvi["monthly_downloads"] == 2100000
    assert uvi["dependency_depth"] == 1


# -- 11. Indexes & WAL ---------------------------------------------------------

def test_fk_indexes(conn):
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='packages'"
    ).fetchall()
    idx_names = [i[0] for i in indexes]

    indexed_cols = set()
    for idx_name in idx_names:
        info = conn.execute(f"PRAGMA index_info('{idx_name}')").fetchall()
        for row in info:
            indexed_cols.add(row["name"])

    assert "author_id" in indexed_cols, \
        f"author_id not indexed. Indexed cols: {indexed_cols}"
    assert "category_id" in indexed_cols, \
        f"category_id not indexed. Indexed cols: {indexed_cols}"
    assert "license_id" in indexed_cols, \
        f"license_id not indexed. Indexed cols: {indexed_cols}"


def test_wal_mode(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"Expected WAL mode, got '{mode}'"
