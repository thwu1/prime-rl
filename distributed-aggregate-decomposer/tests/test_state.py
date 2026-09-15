"""
Tests for distributed SQL aggregate query decomposer.
Verifies that the decompose_query function produces shard/merge query pairs
whose distributed execution matches monolithic execution on TPC-H data.

Tests cover:
- Distributive aggregates (SUM, COUNT, MIN, MAX)
- Algebraic aggregates (AVG over simple columns and compound expressions)
- Univariate statistics (VAR_POP, STDDEV_POP) via parallel variance formula
- Bivariate statistics (COVAR_POP) via parallel covariance formula
- HAVING clause rewriting for merge phase
- ORDER BY preservation
- Multi-table star-schema join queries with GROUP BY alias handling
- Return value structure

"""

import duckdb
import math
import pytest
import sys
import os

sys.path.insert(0, "/app")

DB_PATH = "/app/warehouse.duckdb"
NUM_SHARDS = 4


def get_connection():
    return duckdb.connect(DB_PATH, read_only=True)


def run_monolithic(sql):
    """Run query directly on full dataset."""
    con = get_connection()
    result = con.execute(sql).fetchdf()
    con.close()
    return result


def run_distributed(sql, decompose_fn, num_shards=NUM_SHARDS):
    """Run query via decompose -> shard -> merge pipeline."""
    decomposition = decompose_fn(sql, num_shards)
    shard_query = decomposition["shard_query"]
    merge_query = decomposition["merge_query"]
    final_columns = decomposition["final_columns"]

    # Get total row count from lineitem (primary fact table)
    con = get_connection()
    total_rows = con.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
    con.close()

    # Collect shard results using Arrow for type fidelity
    import pyarrow as pa

    all_shard_tables = []
    for shard_id in range(num_shards):
        con = get_connection()
        shard_sql = _inject_shard_filter(shard_query, shard_id, num_shards)
        try:
            shard_table = con.execute(shard_sql).fetch_arrow_table()
            all_shard_tables.append(shard_table)
        finally:
            con.close()

    # Concatenate shard results as Arrow tables (preserves types)
    if all_shard_tables:
        combined = pa.concat_tables(all_shard_tables)
    else:
        combined = pa.table({})

    # Run merge query on combined results
    merge_con = duckdb.connect(":memory:")
    merge_con.register("shard_results", combined)
    final_result = merge_con.execute(merge_query).fetchdf()
    merge_con.close()

    return final_result, final_columns


def _inject_shard_filter(query, shard_id, num_shards):
    """Inject a WHERE clause to filter rows for a specific shard.

    Uses hash-based partitioning on lineitem only (the fact table).
    Dimension tables (orders, customer, nation, etc.) are fully replicated
    on each shard to support star-schema join queries.
    """
    shard_filter_cte = f"""
    WITH lineitem AS (
        SELECT * FROM main.lineitem
        WHERE hash(l_orderkey || '-' || l_linenumber) % {num_shards} = {shard_id}
    ),
    orders AS (SELECT * FROM main.orders),
    customer AS (SELECT * FROM main.customer),
    part AS (SELECT * FROM main.part),
    supplier AS (SELECT * FROM main.supplier),
    nation AS (SELECT * FROM main.nation),
    region AS (SELECT * FROM main.region),
    partsupp AS (SELECT * FROM main.partsupp)
    """
    # Prepend the CTE to the shard query
    stripped = query.strip()
    if stripped.upper().startswith("WITH "):
        return f"{shard_filter_cte}, _original_query AS ({stripped}) SELECT * FROM _original_query"
    else:
        return shard_filter_cte + stripped


def compare_results(mono_df, dist_df, final_columns, rtol=1e-4):
    """Compare monolithic and distributed results for equivalence."""
    assert len(mono_df) == len(dist_df), (
        f"Row count mismatch: monolithic={len(mono_df)}, distributed={len(dist_df)}"
    )
    assert len(final_columns) == len(mono_df.columns), (
        f"Column count mismatch: final_columns has {len(final_columns)}, "
        f"monolithic has {len(mono_df.columns)}"
    )

    # Sort both dataframes by all string/non-numeric columns for stable comparison
    import pandas as pd
    non_numeric_positions = []
    for i in range(len(mono_df.columns)):
        dtype = mono_df.iloc[:, i].dtype
        if pd.api.types.is_string_dtype(dtype) or dtype == object:
            non_numeric_positions.append(i)

    if non_numeric_positions:
        mono_sort_cols = [mono_df.columns[i] for i in non_numeric_positions]
        dist_sort_cols = [dist_df.columns[i] for i in non_numeric_positions]
        mono_df = mono_df.sort_values(by=mono_sort_cols).reset_index(drop=True)
        dist_df = dist_df.sort_values(by=dist_sort_cols).reset_index(drop=True)

    # Compare column by column
    for i, col_name in enumerate(final_columns):
        mono_col = mono_df.iloc[:, i]
        dist_col = dist_df.iloc[:, i]

        if pd.api.types.is_numeric_dtype(mono_col.dtype):
            for row_idx in range(len(mono_col)):
                m_val = float(mono_col.iloc[row_idx])
                d_val = float(dist_col.iloc[row_idx])
                if m_val == 0:
                    assert abs(d_val) < 1e-6, (
                        f"Column '{col_name}' row {row_idx}: "
                        f"monolithic=0, distributed={d_val}"
                    )
                else:
                    rel_err = abs(m_val - d_val) / abs(m_val)
                    assert rel_err < rtol, (
                        f"Column '{col_name}' row {row_idx}: "
                        f"monolithic={m_val}, distributed={d_val}, "
                        f"rel_error={rel_err}"
                    )
        else:
            for row_idx in range(len(mono_col)):
                assert str(mono_col.iloc[row_idx]) == str(dist_col.iloc[row_idx]), (
                    f"Column '{col_name}' row {row_idx}: "
                    f"monolithic={mono_col.iloc[row_idx]}, "
                    f"distributed={dist_col.iloc[row_idx]}"
                )


@pytest.fixture(scope="module")
def decompose_fn():
    from decomposer import decompose_query
    return decompose_query


class TestBasicDistributiveAggregates:
    """Test SUM, COUNT, MIN, MAX - directly distributive aggregates."""

    def test_sum_count_star(self, decompose_fn):
        sql = """
        SELECT l_returnflag, l_linestatus,
               SUM(l_quantity) AS sum_qty,
               COUNT(*) AS count_order
        FROM lineitem
        GROUP BY l_returnflag, l_linestatus
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_min_max(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               MIN(l_extendedprice) AS min_price,
               MAX(l_extendedprice) AS max_price,
               MIN(l_quantity) AS min_qty,
               MAX(l_quantity) AS max_qty
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_count_column(self, decompose_fn):
        sql = """
        SELECT l_linestatus,
               COUNT(l_comment) AS cnt_comment,
               SUM(l_quantity) AS total_qty
        FROM lineitem
        GROUP BY l_linestatus
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)


class TestAvgDecomposition:
    """Test AVG decomposition into SUM/COUNT."""

    def test_simple_avg(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               AVG(l_quantity) AS avg_qty,
               AVG(l_extendedprice) AS avg_price
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_avg_over_expression(self, decompose_fn):
        sql = """
        SELECT l_returnflag, l_linestatus,
               AVG(l_extendedprice * (1 - l_discount)) AS avg_disc_price,
               AVG(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS avg_charge
        FROM lineitem
        GROUP BY l_returnflag, l_linestatus
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_mixed_avg_and_sum(self, decompose_fn):
        """Mix of AVG and distributive aggregates (TPC-H Q1 style)."""
        sql = """
        SELECT l_returnflag, l_linestatus,
               SUM(l_quantity) AS sum_qty,
               SUM(l_extendedprice) AS sum_base_price,
               AVG(l_quantity) AS avg_qty,
               AVG(l_extendedprice) AS avg_price,
               COUNT(*) AS count_order
        FROM lineitem
        WHERE l_shipdate <= DATE '1998-09-02'
        GROUP BY l_returnflag, l_linestatus
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)


class TestStatisticalAggregates:
    """Test VARIANCE and STDDEV decomposition using parallel formula."""

    def test_variance(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               VAR_POP(l_quantity) AS var_qty
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_stddev(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               STDDEV_POP(l_extendedprice) AS stddev_price
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_mixed_statistical(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               AVG(l_quantity) AS avg_qty,
               VAR_POP(l_quantity) AS var_qty,
               STDDEV_POP(l_quantity) AS stddev_qty,
               COUNT(*) AS cnt
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)


class TestBivariateStatistics:
    """Test COVAR_POP decomposition using parallel covariance formula.

    COVAR_POP(Y, X) = E[YX] - E[Y]*E[X]
    Requires tracking SUM(Y*X), SUM(Y), SUM(X), COUNT(*) across shards.
    """

    def test_covar_pop(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               COVAR_POP(l_quantity, l_extendedprice) AS cov_qty_price
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_covar_pop_mixed_with_univariate(self, decompose_fn):
        """Mix of COVAR_POP with VAR_POP, AVG, and COUNT."""
        sql = """
        SELECT l_returnflag,
               COVAR_POP(l_quantity, l_extendedprice) AS cov_qty_price,
               VAR_POP(l_quantity) AS var_qty,
               AVG(l_extendedprice) AS avg_price,
               COUNT(*) AS cnt
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_covar_pop_different_columns(self, decompose_fn):
        """COVAR_POP on a different pair of columns."""
        sql = """
        SELECT l_returnflag,
               COVAR_POP(l_extendedprice, l_discount) AS cov_price_disc,
               COVAR_POP(l_quantity, l_discount) AS cov_qty_disc
        FROM lineitem
        GROUP BY l_returnflag
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)


class TestHavingClause:
    """Test that HAVING clauses are correctly rewritten for merge phase."""

    def test_having_on_count(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               SUM(l_quantity) AS sum_qty,
               COUNT(*) AS cnt
        FROM lineitem
        GROUP BY l_returnflag
        HAVING COUNT(*) > 100
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_having_on_avg(self, decompose_fn):
        sql = """
        SELECT l_linestatus,
               AVG(l_extendedprice) AS avg_price
        FROM lineitem
        GROUP BY l_linestatus
        HAVING AVG(l_extendedprice) > 30000
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_having_aggregate_not_in_select(self, decompose_fn):
        """HAVING references an aggregate that is not in the SELECT list."""
        sql = """
        SELECT l_returnflag,
               SUM(l_quantity) AS sum_qty
        FROM lineitem
        GROUP BY l_returnflag
        HAVING AVG(l_extendedprice) > 10000
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)


class TestOrderBy:
    """Test that ORDER BY is correctly applied in merge phase."""

    def test_order_by_aggregate(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               SUM(l_quantity) AS sum_qty
        FROM lineitem
        GROUP BY l_returnflag
        ORDER BY sum_qty DESC
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        # For ORDER BY tests, compare without re-sorting
        assert len(mono) == len(dist)
        for i, col_name in enumerate(cols):
            mono_col = mono.iloc[:, i]
            dist_col = dist.iloc[:, i]
            for row_idx in range(len(mono_col)):
                m_val = mono_col.iloc[row_idx]
                d_val = dist_col.iloc[row_idx]
                if isinstance(m_val, (int, float)):
                    if float(m_val) == 0:
                        assert abs(float(d_val)) < 1e-6
                    else:
                        assert abs(float(m_val) - float(d_val)) / abs(float(m_val)) < 1e-4
                else:
                    assert str(m_val) == str(d_val)


class TestMultiTableJoin:
    """Test queries spanning multiple joined tables.

    These test that GROUP BY column references are correctly remapped
    from table-qualified identifiers (e.g. n.n_name) to shard-output
    aliases (e.g. nation_name) in the merge query, since the merge
    operates on shard_results rather than the original tables.
    """

    def test_star_schema_aggregation(self, decompose_fn):
        """Star-schema join: lineitem -> orders -> customer -> nation."""
        sql = """
        SELECT n.n_name AS nation_name,
               SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue,
               AVG(l.l_quantity) AS avg_qty,
               COUNT(*) AS cnt
        FROM lineitem AS l
        JOIN orders AS o ON l.l_orderkey = o.o_orderkey
        JOIN customer AS c ON o.o_custkey = c.c_custkey
        JOIN nation AS n ON c.c_nationkey = n.n_nationkey
        GROUP BY n.n_name
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_join_with_bivariate(self, decompose_fn):
        """Multi-table join with COVAR_POP - combines two challenges."""
        sql = """
        SELECT n.n_name AS nation_name,
               COVAR_POP(l.l_extendedprice, l.l_discount) AS cov_price_disc,
               AVG(l.l_quantity) AS avg_qty,
               COUNT(*) AS cnt
        FROM lineitem AS l
        JOIN orders AS o ON l.l_orderkey = o.o_orderkey
        JOIN customer AS c ON o.o_custkey = c.c_custkey
        JOIN nation AS n ON c.c_nationkey = n.n_nationkey
        GROUP BY n.n_name
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        compare_results(mono, dist, cols)

    def test_join_with_having_and_order(self, decompose_fn):
        """Multi-table join with HAVING and ORDER BY."""
        sql = """
        SELECT n.n_name AS nation_name,
               SUM(l.l_extendedprice) AS total_price,
               COUNT(*) AS cnt
        FROM lineitem AS l
        JOIN orders AS o ON l.l_orderkey = o.o_orderkey
        JOIN customer AS c ON o.o_custkey = c.c_custkey
        JOIN nation AS n ON c.c_nationkey = n.n_nationkey
        GROUP BY n.n_name
        HAVING COUNT(*) > 100
        ORDER BY total_price DESC
        """
        mono = run_monolithic(sql)
        dist, cols = run_distributed(sql, decompose_fn)
        # ORDER BY - compare without re-sorting
        assert len(mono) == len(dist)
        for i, col_name in enumerate(cols):
            mono_col = mono.iloc[:, i]
            dist_col = dist.iloc[:, i]
            for row_idx in range(len(mono_col)):
                m_val = mono_col.iloc[row_idx]
                d_val = dist_col.iloc[row_idx]
                try:
                    m_f = float(m_val)
                    d_f = float(d_val)
                    if m_f == 0:
                        assert abs(d_f) < 1e-6
                    else:
                        assert abs(m_f - d_f) / abs(m_f) < 1e-4
                except (ValueError, TypeError):
                    assert str(m_val) == str(d_val)


class TestReturnStructure:
    """Test the structure of the decompose_query return value."""

    def test_returns_dict_with_required_keys(self, decompose_fn):
        sql = "SELECT SUM(l_quantity) AS s FROM lineitem"
        result = decompose_fn(sql, 4)
        assert isinstance(result, dict)
        assert "shard_query" in result
        assert "merge_query" in result
        assert "final_columns" in result

    def test_shard_query_is_valid_sql(self, decompose_fn):
        sql = "SELECT AVG(l_quantity) AS avg_qty FROM lineitem GROUP BY l_returnflag"
        result = decompose_fn(sql, 4)
        con = get_connection()
        # Should parse and execute without error
        con.execute(result["shard_query"]).fetchdf()
        con.close()

    def test_merge_query_references_shard_results(self, decompose_fn):
        sql = "SELECT SUM(l_quantity) AS s FROM lineitem"
        result = decompose_fn(sql, 4)
        assert "shard_results" in result["merge_query"].lower()

    def test_final_columns_match_original(self, decompose_fn):
        sql = """
        SELECT l_returnflag,
               SUM(l_quantity) AS sum_qty,
               AVG(l_extendedprice) AS avg_price
        FROM lineitem
        GROUP BY l_returnflag
        """
        result = decompose_fn(sql, 4)
        cols = result["final_columns"]
        assert len(cols) == 3
        assert cols[0].lower() == "l_returnflag"
        assert cols[1].lower() == "sum_qty"
        assert cols[2].lower() == "avg_price"
