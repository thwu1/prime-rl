#!/usr/bin/env python3
"""
Fix ORDER BY scoping bugs in /app/queries.sql.

Each bug exploits a different aspect of PostgreSQL's dual SQL-92 / SQL-99
identifier resolution in ORDER BY:
  SQL-92 path: bare identifier -> resolves against SELECT-list aliases
  SQL-99 path: any expression  -> resolves against FROM scope (table columns)

GROUP BY reverses the priority (table first, then aliases).
Window ORDER BY and UNION ORDER BY have their own restricted rules.
"""

import re
import sys
import psycopg2


# Mapping from query name to the corrected SQL (with trailing semicolon).
# Each fix targets the specific parser-seam bug in the original query.
FIXES = {
    "alias_shadow": (
        # Bug: ORDER BY a resolves to alias (-a AS a), sorting negated values.
        # Fix: table-qualified nums.a forces SQL-99 expression path -> table column.
        "SELECT -a AS a FROM nums ORDER BY nums.a;"
    ),
    "quoted_alias_silent": (
        # Bug: quoted "Price" (uppercase P) doesn't match bare 'price' (lowercase)
        # via strcmp, so ORDER BY falls through to table column price.
        # Fix: use quoted "Price" to match the alias exactly.
        'SELECT item, -price AS "Price" FROM inventory ORDER BY "Price";'
    ),
    "group_order_clash": (
        # Bug: GROUP BY price resolves to the table column (8 distinct values),
        # but the intent is to group by the expression price/10 (5 buckets).
        # Fix: use the expression in GROUP BY.
        "SELECT price / 10 AS price, count(*) AS cnt "
        "FROM inventory GROUP BY price / 10 ORDER BY price;"
    ),
    "window_alias": (
        # Bug: window ORDER BY cannot resolve SELECT-list aliases.
        # Fix: use the expression -price directly.
        "SELECT item, category, -price AS neg_price,\n"
        "       row_number() OVER (PARTITION BY category ORDER BY -price) AS rnk\n"
        "FROM inventory\n"
        "ORDER BY category, rnk;"
    ),
    "collate_trap": (
        # Bug: COLLATE wraps 'product' into an expression, forcing SQL-99 path
        # which looks in FROM for 'product' (doesn't exist; actual column is 'item').
        # Fix: use the real column name.
        'SELECT item AS product FROM inventory ORDER BY item COLLATE "C";'
    ),
    "unary_plus": (
        # Bug: +a is an expression (unary plus), forcing SQL-99 path to table column.
        # Fix: bare a uses SQL-92 path and resolves to alias.
        "SELECT -a AS a FROM nums ORDER BY a;"
    ),
    "union_expression": (
        # Bug: UNION ORDER BY rejects expressions; only column names are allowed.
        # Fix: use the column name with DESC modifier.
        "(SELECT item, price FROM inventory WHERE category = 'tools')\n"
        "UNION ALL\n"
        "(SELECT item, price FROM inventory WHERE category = 'fasteners')\n"
        "ORDER BY price DESC;"
    ),
}

# Expected results for verification (mirrors test_state.py).
EXPECTED = {
    "alias_shadow": [(0,), (-1,), (-2,), (-3,)],
    "quoted_alias_silent": [
        ("Valve", -45), ("Pipe", -30), ("Wrench", -25), ("Hammer", -18),
        ("Switch", -15), ("Wire", -10), ("Bolt", -2), ("Nail", -1),
    ],
    "group_order_clash": [(0, 2), (1, 3), (2, 1), (3, 1), (4, 1)],
    "window_alias": [
        ("Switch", "electrical", -15, 1),
        ("Wire", "electrical", -10, 2),
        ("Bolt", "fasteners", -2, 1),
        ("Nail", "fasteners", -1, 2),
        ("Valve", "plumbing", -45, 1),
        ("Pipe", "plumbing", -30, 2),
        ("Wrench", "tools", -25, 1),
        ("Hammer", "tools", -18, 2),
    ],
    "collate_trap": [
        ("Bolt",), ("Hammer",), ("Nail",), ("Pipe",),
        ("Switch",), ("Valve",), ("Wire",), ("Wrench",),
    ],
    "unary_plus": [(-3,), (-2,), (-1,), (0,)],
    "union_expression": [
        ("Wrench", 25), ("Hammer", 18), ("Bolt", 2), ("Nail", 1),
    ],
}


def parse_queries(filepath):
    """Parse -- @name: tagged queries from a SQL file."""
    with open(filepath) as f:
        content = f.read()
    pattern = r"-- @name:\s*(\S+)\s*\n"
    parts = re.split(pattern, content)
    queries = {}
    comments = {}
    for i in range(1, len(parts), 2):
        name = parts[i]
        block = parts[i + 1]
        comment_lines = []
        for line in block.strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("--"):
                comment_lines.append(line)
            elif stripped == "":
                continue
            else:
                break
        queries[name] = None  # placeholder
        comments[name] = comment_lines
    return queries, comments


def main():
    _, comments = parse_queries("/app/queries.sql")

    # Reconstruct the file with corrected queries
    output_parts = []
    for name in FIXES:
        output_parts.append(f"-- @name: {name}")
        if name in comments:
            output_parts.extend(comments[name])
        output_parts.append(FIXES[name])
        output_parts.append("")

    with open("/app/queries.sql", "w") as f:
        f.write("\n".join(output_parts) + "\n")

    print("Fixed queries written to /app/queries.sql")

    # Verify every fixed query against the database
    conn = psycopg2.connect(dbname="analytics", user="postgres")
    conn.autocommit = True
    cur = conn.cursor()

    all_ok = True
    for name, sql in FIXES.items():
        try:
            cur.execute(sql.rstrip(";"))
            rows = cur.fetchall()
            actual = [tuple(row) for row in rows]
            expected = [tuple(r) for r in EXPECTED[name]]
            if actual != expected:
                print(f"  MISMATCH {name}: expected {expected}, got {actual}")
                all_ok = False
            else:
                print(f"  OK {name} ({len(rows)} rows)")
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            all_ok = False

    cur.close()
    conn.close()

    if not all_ok:
        print("FAILED: some queries still produce wrong results")
        sys.exit(1)

    print("All 7 queries fixed and verified.")


if __name__ == "__main__":
    main()
