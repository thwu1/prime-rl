"""
Tests for distributed SQL aggregate query decomposer.

"""
import math
import sys
import json

import duckdb
import pytest

sys.path.insert(0, '/app')
from dist_agg import decompose_query


CONFIG = json.load(open('/app/config.json'))
DB_PATH = CONFIG['database']
SHARD_TABLES = CONFIG['shard_tables']


def run_decomposed(conn, sql, shard_tables):
    """Run a query through the shard->merge decomposition pipeline."""
    result = decompose_query(sql, shard_tables)
    template = result['shard_query_template']
    merge_sql = result['merge_query']

    parts = []
    for st in shard_tables:
        shard_sql = template.format(shard_table=st)
        parts.append(f"({shard_sql})")
    union_sql = " UNION ALL ".join(parts)

    conn.execute(f"CREATE OR REPLACE TEMPORARY TABLE shard_results AS {union_sql}")
    conn.execute(merge_sql)
    columns = [desc[0] for desc in conn.description]
    rows = conn.fetchall()
    conn.execute("DROP TABLE IF EXISTS shard_results")
    return columns, rows


def run_original(conn, sql):
    """Run the original query directly."""
    conn.execute(sql)
    columns = [desc[0] for desc in conn.description]
    rows = conn.fetchall()
    return columns, rows


def compare_results(orig_rows, decomp_rows, rtol=1e-6, atol=1e-9):
    """Compare two result sets with floating-point tolerance."""
    assert len(orig_rows) == len(decomp_rows), (
        f"Row count mismatch: {len(orig_rows)} vs {len(decomp_rows)}"
    )

    def sort_key(row):
        return tuple(
            (0, str(v)) if v is not None else (1, '')
            for v in row
        )

    orig_sorted = sorted(orig_rows, key=sort_key)
    decomp_sorted = sorted(decomp_rows, key=sort_key)

    for i, (r1, r2) in enumerate(zip(orig_sorted, decomp_sorted)):
        assert len(r1) == len(r2), (
            f"Column count mismatch at row {i}: {len(r1)} vs {len(r2)}"
        )
        for j, (v1, v2) in enumerate(zip(r1, r2)):
            if v1 is None and v2 is None:
                continue
            assert not (v1 is None or v2 is None), (
                f"NULL mismatch at row {i}, col {j}: {v1!r} vs {v2!r}"
            )
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                assert math.isclose(float(v1), float(v2), rel_tol=rtol, abs_tol=atol), (
                    f"Numeric mismatch at row {i}, col {j}: {v1} vs {v2} "
                    f"(diff={abs(float(v1)-float(v2))})"
                )
            else:
                assert str(v1) == str(v2), (
                    f"Value mismatch at row {i}, col {j}: {v1!r} vs {v2!r}"
                )


QUERIES = [
    # --- Basic single-column aggregates ---
    (
        "count_star",
        "SELECT COUNT(*) AS total FROM sales"
    ),
    (
        "avg_no_group",
        "SELECT AVG(price) AS avg_price FROM sales"
    ),
    (
        "sum_min_max",
        "SELECT SUM(quantity) AS total_qty, MIN(price) AS min_p, MAX(price) AS max_p FROM sales"
    ),
    (
        "grouped_avg_count",
        "SELECT region, AVG(price) AS avg_price, COUNT(*) AS cnt FROM sales GROUP BY region"
    ),
    (
        "var_stddev_pop",
        "SELECT region, VAR_POP(price) AS var_p, STDDEV_POP(price) AS std_p FROM sales GROUP BY region"
    ),
    (
        "var_stddev_samp",
        "SELECT STDDEV_SAMP(price) AS std_s, VAR_SAMP(price) AS var_s FROM sales"
    ),
    (
        "expr_in_agg",
        "SELECT region, AVG(price * quantity) AS avg_revenue FROM sales GROUP BY region"
    ),
    (
        "where_clause",
        "SELECT region, AVG(price) AS avg_price, COUNT(*) AS cnt "
        "FROM sales WHERE quantity > 50 GROUP BY region"
    ),
    (
        "having_orderby_limit",
        "SELECT region, AVG(price) AS avg_price FROM sales "
        "GROUP BY region HAVING AVG(price) > 200 ORDER BY avg_price DESC LIMIT 2"
    ),
    (
        "complex_mixed",
        "SELECT region, product, AVG(price) AS avg_p, STDDEV_POP(quantity) AS std_q, "
        "SUM(price * quantity) AS revenue, COUNT(*) AS cnt "
        "FROM sales WHERE sale_date >= '2024-07-01' "
        "GROUP BY region, product HAVING COUNT(*) > 100 ORDER BY region, product"
    ),
    # --- COUNT(DISTINCT) ---
    (
        "count_distinct_scalar",
        "SELECT COUNT(DISTINCT product) AS n_products, "
        "COUNT(DISTINCT region) AS n_regions FROM sales"
    ),
    (
        "count_distinct_mixed",
        "SELECT region, COUNT(DISTINCT product) AS n_prods, "
        "AVG(price) AS avg_p, COUNT(*) AS cnt FROM sales GROUP BY region"
    ),
    # --- Two-variable statistics: COVAR_POP, CORR ---
    (
        "covar_corr_grouped",
        "SELECT region, COVAR_POP(price, quantity) AS cov_pq, "
        "CORR(price, quantity) AS corr_pq FROM sales GROUP BY region"
    ),
    # --- Kitchen sink: all types combined ---
    (
        "kitchen_sink",
        "SELECT region, COUNT(DISTINCT product) AS n_prods, "
        "AVG(price) AS avg_p, STDDEV_POP(quantity) AS std_q, "
        "COVAR_POP(price, quantity) AS cov_pq, "
        "CORR(price, discount) AS corr_pd, "
        "SUM(price * quantity) AS revenue "
        "FROM sales WHERE quantity > 10 GROUP BY region "
        "HAVING COUNT(*) > 500 ORDER BY region"
    ),
]


@pytest.mark.parametrize("name,query", QUERIES, ids=[q[0] for q in QUERIES])
def test_decomposition(name, query):
    """Test that decomposed execution matches original query results."""
    conn = duckdb.connect(DB_PATH)
    try:
        orig_cols, orig_rows = run_original(conn, query)
        decomp_cols, decomp_rows = run_decomposed(conn, query, SHARD_TABLES)

        assert len(orig_cols) == len(decomp_cols), (
            f"[{name}] Column count mismatch: {len(orig_cols)} vs {len(decomp_cols)}"
        )

        compare_results(orig_rows, decomp_rows)
    finally:
        conn.close()


@pytest.mark.parametrize("name,query", QUERIES, ids=[q[0] for q in QUERIES])
def test_return_format(name, query):
    """Test that decompose_query returns the expected dict format."""
    result = decompose_query(query, SHARD_TABLES)
    assert isinstance(result, dict), "decompose_query must return a dict"
    assert "shard_query_template" in result, "Missing 'shard_query_template' key"
    assert "merge_query" in result, "Missing 'merge_query' key"
    assert isinstance(result["shard_query_template"], str)
    assert isinstance(result["merge_query"], str)
    assert "{shard_table}" in result["shard_query_template"], (
        "shard_query_template must contain {shard_table} placeholder"
    )
