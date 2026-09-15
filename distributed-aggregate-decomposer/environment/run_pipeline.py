"""
Diagnostic tool to test the distributed query pipeline.
Runs a SQL query both monolithically and through the distributed decompose pipeline,
then compares results.

Usage: python3 /app/run_pipeline.py "SELECT ..."
"""
import sys
import os

sys.path.insert(0, "/app")

import duckdb
import pyarrow as pa
import pandas as pd

DB_PATH = "/app/warehouse.duckdb"
NUM_SHARDS = 4


def run_monolithic(sql):
    con = duckdb.connect(DB_PATH, read_only=True)
    result = con.execute(sql).fetchdf()
    con.close()
    return result


def inject_shard_filter(query, shard_id, num_shards):
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
    stripped = query.strip()
    if stripped.upper().startswith("WITH "):
        return f"{shard_filter_cte}, _original_query AS ({stripped}) SELECT * FROM _original_query"
    else:
        return shard_filter_cte + stripped


def run_distributed(sql, num_shards=NUM_SHARDS):
    from decomposer import decompose_query
    decomposition = decompose_query(sql, num_shards)
    shard_query = decomposition["shard_query"]
    merge_query = decomposition["merge_query"]
    final_columns = decomposition["final_columns"]

    all_shard_tables = []
    for shard_id in range(num_shards):
        con = duckdb.connect(DB_PATH, read_only=True)
        shard_sql = inject_shard_filter(shard_query, shard_id, num_shards)
        try:
            shard_table = con.execute(shard_sql).fetch_arrow_table()
            all_shard_tables.append(shard_table)
        finally:
            con.close()

    if all_shard_tables:
        combined = pa.concat_tables(all_shard_tables)
    else:
        combined = pa.table({})

    merge_con = duckdb.connect(":memory:")
    merge_con.register("shard_results", combined)
    final_result = merge_con.execute(merge_query).fetchdf()
    merge_con.close()

    return final_result, final_columns, decomposition


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 /app/run_pipeline.py \"SQL QUERY\"")
        print()
        print("Runs a query both directly and via the distributed pipeline,")
        print("then compares results to identify discrepancies.")
        sys.exit(1)

    sql = sys.argv[1]
    print(f"Query: {sql}")
    print()

    print("=== Monolithic Result ===")
    mono = run_monolithic(sql)
    print(mono.to_string())
    print()

    try:
        dist, cols, decomposition = run_distributed(sql)
        print("=== Distributed Result ===")
        print(dist.to_string())
        print()
        print(f"Final columns: {cols}")
        print()
        print("=== Generated Queries ===")
        print(f"Shard query:  {decomposition['shard_query']}")
        print(f"Merge query:  {decomposition['merge_query']}")
        print()

        # Sort both by non-numeric columns for stable comparison
        non_numeric_cols_mono = [c for c in mono.columns if pd.api.types.is_string_dtype(mono[c]) or mono[c].dtype == object]
        non_numeric_cols_dist = [c for c in dist.columns if pd.api.types.is_string_dtype(dist[c]) or dist[c].dtype == object]

        if non_numeric_cols_mono:
            mono = mono.sort_values(by=non_numeric_cols_mono).reset_index(drop=True)
        if non_numeric_cols_dist:
            dist = dist.sort_values(by=non_numeric_cols_dist).reset_index(drop=True)

        # Compare
        if len(mono) != len(dist):
            print(f"FAIL: Row counts differ (monolithic={len(mono)}, distributed={len(dist)})")
        elif len(mono.columns) != len(dist.columns):
            print(f"FAIL: Column counts differ (monolithic={len(mono.columns)}, distributed={len(dist.columns)})")
        else:
            mismatches = 0
            for i in range(len(mono.columns)):
                for j in range(len(mono)):
                    m = mono.iloc[j, i]
                    d = dist.iloc[j, i]
                    try:
                        m_f = float(m)
                        d_f = float(d)
                        if m_f != 0 and abs(m_f - d_f) / abs(m_f) > 1e-4:
                            mismatches += 1
                            print(f"  MISMATCH col={mono.columns[i]} row={j}: monolithic={m_f:.6f}, distributed={d_f:.6f}, rel_err={abs(m_f - d_f) / abs(m_f):.6e}")
                        elif m_f == 0 and abs(d_f) > 1e-6:
                            mismatches += 1
                            print(f"  MISMATCH col={mono.columns[i]} row={j}: monolithic=0, distributed={d_f:.6f}")
                    except (ValueError, TypeError):
                        if str(m) != str(d):
                            mismatches += 1
                            print(f"  MISMATCH col={mono.columns[i]} row={j}: monolithic={m}, distributed={d}")

            if mismatches == 0:
                print("RESULT: PASS - Results match within tolerance")
            else:
                print(f"\nRESULT: FAIL - {mismatches} value mismatch(es) found")

    except Exception as e:
        print(f"=== Distributed Execution Failed ===")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
