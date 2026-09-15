"""
Distributed SQL Aggregate Query Decomposer

Implement the decompose_query function to decompose aggregate SQL queries
for distributed execution across sharded DuckDB tables.
"""


def decompose_query(sql, shard_tables):
    """
    Decompose a SQL aggregate query for distributed execution.

    Args:
        sql: A SQL SELECT query targeting the 'sales' table, containing
             aggregate functions and optional SQL clauses.

             Supported single-column aggregates:
               COUNT(*), COUNT(col), COUNT(DISTINCT col),
               SUM, MIN, MAX, AVG,
               VAR_POP, VAR_SAMP, STDDEV_POP, STDDEV_SAMP

             Supported two-column aggregates:
               COVAR_POP(x, y), CORR(x, y)

             Supported clauses:
               WHERE, GROUP BY, HAVING, ORDER BY, LIMIT

             Expressions inside aggregates are allowed (e.g., AVG(price * quantity)).
             Queries may mix any combination of these aggregate types.

        shard_tables: List of shard table names (e.g., ['shard_0', ..., 'shard_3'])

    Returns:
        dict with:
            "shard_query_template": str
                SQL query with a {shard_table} placeholder for the table name.
                This query runs on each shard to compute partial aggregates.
                Must include GROUP BY columns (if any) and all intermediate
                aggregate columns needed by the merge query.
            "merge_query": str
                SQL query that reads from a table called 'shard_results'
                (the UNION ALL of all shard query outputs) and produces
                the final result equivalent to running the original query
                on the complete dataset.
    """
    raise NotImplementedError("Implement this function")
