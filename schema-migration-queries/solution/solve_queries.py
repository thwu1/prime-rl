#!/usr/bin/env python3
"""
Adapt TPC-H queries to the migrated warehouse schema.

Schema changes discovered by inspecting the database:
- lineitem -> line_items (fulfillment) + line_prices (financials)
  JOIN KEY: (order_key, line_number)  [changelog only mentions order_key!]
- orders -> sales_orders (column prefixes removed)
- nation -> nations (nation_id, nation_name, region_id)
- partsupp -> part_supply (part_key, supplier_key, available_qty, supply_cost)
- supplier, customer, part, region: UNCHANGED
"""


import duckdb
import os

ADAPTED_QUERIES = {
    1: """
SELECT
    li.return_flag AS l_returnflag,
    li.line_status AS l_linestatus,
    SUM(li.quantity) AS sum_qty,
    SUM(lp.extended_price) AS sum_base_price,
    SUM(lp.extended_price * (1 - lp.discount)) AS sum_disc_price,
    SUM(lp.extended_price * (1 - lp.discount) * (1 + lp.tax)) AS sum_charge,
    AVG(li.quantity) AS avg_qty,
    AVG(lp.extended_price) AS avg_price,
    AVG(lp.discount) AS avg_disc,
    COUNT(*) AS count_order
FROM
    line_items li
    JOIN line_prices lp
        ON li.order_key = lp.order_key AND li.line_number = lp.line_number
WHERE
    li.ship_date <= CAST('1998-09-02' AS DATE)
GROUP BY
    li.return_flag,
    li.line_status
ORDER BY
    li.return_flag,
    li.line_status
""",

    5: """
SELECT
    n.nation_name AS n_name,
    SUM(lp.extended_price * (1 - lp.discount)) AS revenue
FROM
    customer c
    JOIN sales_orders so ON c.c_custkey = so.customer_key
    JOIN line_items li ON li.order_key = so.order_key
    JOIN line_prices lp ON li.order_key = lp.order_key AND li.line_number = lp.line_number
    JOIN supplier s ON li.supplier_key = s.s_suppkey
    JOIN nations n ON s.s_nationkey = n.nation_id
    JOIN region r ON n.region_id = r.r_regionkey
WHERE
    c.c_nationkey = s.s_nationkey
    AND r.r_name = 'ASIA'
    AND so.order_date >= CAST('1994-01-01' AS DATE)
    AND so.order_date < CAST('1995-01-01' AS DATE)
GROUP BY
    n.nation_name
ORDER BY
    revenue DESC
""",

    7: """
SELECT
    supp_nation,
    cust_nation,
    l_year,
    SUM(volume) AS revenue
FROM
    (
        SELECT
            n1.nation_name AS supp_nation,
            n2.nation_name AS cust_nation,
            EXTRACT(YEAR FROM li.ship_date) AS l_year,
            lp.extended_price * (1 - lp.discount) AS volume
        FROM
            supplier s
            JOIN line_items li ON s.s_suppkey = li.supplier_key
            JOIN line_prices lp ON li.order_key = lp.order_key AND li.line_number = lp.line_number
            JOIN sales_orders so ON so.order_key = li.order_key
            JOIN customer c ON c.c_custkey = so.customer_key
            JOIN nations n1 ON s.s_nationkey = n1.nation_id
            JOIN nations n2 ON c.c_nationkey = n2.nation_id
        WHERE
            (
                (n1.nation_name = 'FRANCE' AND n2.nation_name = 'GERMANY')
                OR (n1.nation_name = 'GERMANY' AND n2.nation_name = 'FRANCE')
            )
            AND li.ship_date BETWEEN CAST('1995-01-01' AS DATE) AND CAST('1996-12-31' AS DATE)
    ) AS shipping
GROUP BY
    supp_nation,
    cust_nation,
    l_year
ORDER BY
    supp_nation,
    cust_nation,
    l_year
""",

    9: """
SELECT
    nation,
    o_year,
    SUM(amount) AS sum_profit
FROM
    (
        SELECT
            n.nation_name AS nation,
            EXTRACT(YEAR FROM so.order_date) AS o_year,
            lp.extended_price * (1 - lp.discount) - ps.supply_cost * li.quantity AS amount
        FROM
            part p
            JOIN line_items li ON p.p_partkey = li.part_key
            JOIN line_prices lp ON li.order_key = lp.order_key AND li.line_number = lp.line_number
            JOIN supplier s ON s.s_suppkey = li.supplier_key
            JOIN part_supply ps ON ps.supplier_key = li.supplier_key AND ps.part_key = li.part_key
            JOIN sales_orders so ON so.order_key = li.order_key
            JOIN nations n ON s.s_nationkey = n.nation_id
        WHERE
            p.p_name LIKE '%green%'
    ) AS profit
GROUP BY
    nation,
    o_year
ORDER BY
    nation,
    o_year DESC
""",

    21: """
SELECT
    s.s_name,
    COUNT(*) AS numwait
FROM
    supplier s
    JOIN line_items l1 ON s.s_suppkey = l1.supplier_key
    JOIN sales_orders so ON so.order_key = l1.order_key
    JOIN nations n ON s.s_nationkey = n.nation_id
WHERE
    so.status = 'F'
    AND l1.receipt_date > l1.commit_date
    AND EXISTS (
        SELECT *
        FROM line_items l2
        WHERE l2.order_key = l1.order_key
          AND l2.supplier_key <> l1.supplier_key
    )
    AND NOT EXISTS (
        SELECT *
        FROM line_items l3
        WHERE l3.order_key = l1.order_key
          AND l3.supplier_key <> l1.supplier_key
          AND l3.receipt_date > l3.commit_date
    )
    AND n.nation_name = 'SAUDI ARABIA'
GROUP BY
    s.s_name
ORDER BY
    numwait DESC,
    s.s_name
LIMIT 100
""",
}


def main():
    # Inspect schema to verify our understanding
    con = duckdb.connect('/app/warehouse.duckdb', read_only=True)

    print("=== Schema Discovery ===")
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables: {[t[0] for t in tables]}")

    for table in tables:
        tname = table[0]
        if tname == 'schema_changelog':
            continue
        cols = con.execute(f"DESCRIBE {tname}").fetchall()
        print(f"\n{tname}: {[c[0] for c in cols]}")

    print("\n=== Schema Changelog ===")
    changelog = con.execute("SELECT * FROM schema_changelog ORDER BY change_id").fetchall()
    for row in changelog:
        print(f"  [{row[1]}] {row[2]}")

    # Write and verify adapted queries
    os.makedirs('/app/adapted_queries', exist_ok=True)

    print("\n=== Verifying Adapted Queries ===")
    for qid, sql in sorted(ADAPTED_QUERIES.items()):
        try:
            result = con.execute(sql).fetchall()
            print(f"Q{qid}: OK ({len(result)} rows)")
        except Exception as e:
            print(f"Q{qid}: FAILED - {e}")
            raise

        with open(f'/app/adapted_queries/q{qid}.sql', 'w') as f:
            f.write(sql.strip() + '\n')

    con.close()
    print("\nAll adapted queries written to /app/adapted_queries/")


if __name__ == '__main__':
    main()
