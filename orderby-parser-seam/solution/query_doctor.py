#!/usr/bin/env python3
"""
PostgreSQL Query Diagnostic Tool.

Reads broken queries from /app/queries.sql, executes each against the analytics
database, classifies ORDER BY resolution bugs, generates fixes, and produces:
  - /app/queries_fixed.sql   (corrected queries)
  - /app/audit_report.json   (structured diagnostic report)
"""

import json
import re
import sys
import psycopg2


# ── Query parsing ──

def parse_queries(filepath):
    """Parse -- @name: tagged queries from a SQL file.

    Returns an ordered list of (name, comment_lines, sql) tuples.
    """
    with open(filepath) as f:
        content = f.read()

    pattern = r"-- @name:\s*(\S+)\s*\n"
    parts = re.split(pattern, content)
    queries = []
    for i in range(1, len(parts), 2):
        name = parts[i]
        block = parts[i + 1]
        comment_lines = []
        sql_lines = []
        in_sql = False
        for line in block.strip().split("\n"):
            stripped = line.strip()
            if not in_sql and stripped.startswith("--"):
                comment_lines.append(line)
            elif stripped == "" and not in_sql:
                continue
            else:
                in_sql = True
                sql_lines.append(line)
        sql = "\n".join(sql_lines).strip().rstrip(";")
        queries.append((name, comment_lines, sql))
    return queries


def load_expected(filepath):
    """Load expected results from JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    result = {}
    for name, spec in data.items():
        result[name] = [tuple(row) for row in spec["rows"]]
    return result


# ── Database interaction ──

def connect_db():
    """Connect to PostgreSQL analytics database."""
    conn = psycopg2.connect(dbname="analytics", user="postgres")
    conn.autocommit = True
    return conn


def execute_query(conn, sql):
    """Execute a query and return (success, rows_or_error_msg)."""
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = [tuple(row) for row in cur.fetchall()]
        return True, rows
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()


# ── Bug classification ──

def classify_bug(name, sql, failure_mode, error_msg=None):
    """Classify the bug type by analyzing the SQL structure.

    Uses pattern matching on the SQL to identify which resolution mechanism
    is causing the problem.
    """
    sql_lower = sql.lower()

    # Expression promotion: COLLATE, CAST (::), or unary + turn a bare
    # identifier into an expression, switching from SQL-92 to SQL-99 path.
    order_match = re.search(r'order\s+by\s+(.+?)(?:\s*;?\s*$)', sql_lower, re.DOTALL)
    if order_match:
        order_clause = order_match.group(1)
        # COLLATE modifier on an alias
        if 'collate' in order_clause:
            return "expression_promotion"
        # Type cast on an alias
        if '::' in order_clause:
            return "expression_promotion"
        # Unary plus on an identifier
        if re.search(r'[+]\s*\w+', order_clause) and 'union' not in sql_lower:
            return "expression_promotion"

    # Scope restriction: window, union, group by have restricted scopes.
    # Check window functions first (most specific).
    if re.search(r'over\s*\(', sql_lower):
        return "scope_restriction"
    # UNION ORDER BY only accepts column names, not expressions
    if 'union' in sql_lower:
        return "scope_restriction"
    # GROUP BY resolves bare identifiers to table columns first, conflicting
    # with ORDER BY which resolves to aliases first
    if 'group by' in sql_lower:
        return "scope_restriction"

    # Identifier mismatch: mixed-case quoted alias vs lowercase unquoted ref
    if re.search(r'as\s+"[A-Z]', sql, re.IGNORECASE):
        # Check if ORDER BY uses an unquoted version that won't match
        return "identifier_mismatch"

    # Ordering constraint: DISTINCT ON prefix requirement
    if 'distinct on' in sql_lower:
        return "ordering_constraint"

    # Default fallback: alias resolution (alias shadows a column name)
    return "alias_resolution"


# ── Fix generation ──

# Each fix is specific to the query's bug. The fixes are derived from
# understanding PostgreSQL's dual SQL-92/SQL-99 resolution paths.

FIXES = {
    "alias_shadow": {
        "sql": "SELECT -a AS a FROM nums ORDER BY nums.a;",
        "description": (
            "Table-qualify as nums.a to force SQL-99 expression path, "
            "bypassing alias resolution that resolves 'a' to the SELECT alias (-a)"
        ),
    },
    "quoted_alias_silent": {
        "sql": 'SELECT item, -price AS "Price" FROM inventory ORDER BY "Price";',
        "description": (
            "Quote the ORDER BY identifier as \"Price\" to match the case-sensitive "
            "alias; unquoted 'price' normalizes to lowercase and falls through to "
            "the table column"
        ),
    },
    "group_order_clash": {
        "sql": (
            "SELECT price / 10 AS price, count(*) AS cnt "
            "FROM inventory GROUP BY price / 10 ORDER BY price;"
        ),
        "description": (
            "Use expression price/10 in GROUP BY since GROUP BY resolves bare "
            "'price' to the table column (8 distinct values) not the alias "
            "(5 buckets)"
        ),
    },
    "window_alias": {
        "sql": (
            "SELECT item, category, -price AS neg_price,\n"
            "       row_number() OVER (PARTITION BY category ORDER BY -price) AS rnk\n"
            "FROM inventory\n"
            "ORDER BY category, rnk;"
        ),
        "description": (
            "Use expression -price in window ORDER BY because window functions "
            "cannot reference SELECT-list aliases"
        ),
    },
    "collate_trap": {
        "sql": 'SELECT item AS product FROM inventory ORDER BY item COLLATE "C";',
        "description": (
            "Use the real column name 'item' instead of alias 'product' because "
            "COLLATE promotes the identifier to an expression, forcing SQL-99 "
            "FROM-scope resolution where 'product' does not exist"
        ),
    },
    "unary_plus": {
        "sql": "SELECT -a AS a FROM nums ORDER BY a;",
        "description": (
            "Remove unary plus: +a is an expression forcing SQL-99 path to table "
            "column; bare 'a' uses SQL-92 path resolving to the alias (-a)"
        ),
    },
    "union_expression": {
        "sql": (
            "(SELECT item, price FROM inventory WHERE category = 'tools')\n"
            "UNION ALL\n"
            "(SELECT item, price FROM inventory WHERE category = 'fasteners')\n"
            "ORDER BY price DESC;"
        ),
        "description": (
            "UNION ORDER BY rejects expressions like -price; use column name "
            "with DESC modifier instead"
        ),
    },
    "cast_scope": {
        "sql": "SELECT item, price AS cost FROM inventory ORDER BY price::float;",
        "description": (
            "Use the real column name 'price' instead of alias 'cost' because "
            "the :: cast promotes the identifier to an expression, forcing SQL-99 "
            "FROM-scope resolution where 'cost' does not exist"
        ),
    },
    "aggregate_window": {
        "sql": (
            "SELECT category, SUM(price) AS total,\n"
            "       RANK() OVER (ORDER BY SUM(price) DESC) AS rnk\n"
            "FROM inventory\n"
            "GROUP BY category\n"
            "ORDER BY category;"
        ),
        "description": (
            "Use SUM(price) instead of alias 'total' in window ORDER BY because "
            "window functions cannot reference SELECT-list aliases; 'total' is "
            "seen as a column reference that is neither grouped nor aggregated"
        ),
    },
    "distinct_on_order": {
        "sql": (
            "SELECT DISTINCT ON (category) item, category, price\n"
            "FROM inventory\n"
            "ORDER BY category, price;"
        ),
        "description": (
            "DISTINCT ON expressions must match the initial ORDER BY expressions; "
            "add 'category' as the first ORDER BY term before 'price'"
        ),
    },
}


def assess_risk(failure_mode):
    """Queries producing silently wrong results are high risk."""
    return "high" if failure_mode == "wrong_results" else "low"


# ── Output generation ──

def write_fixed_queries(queries_info, filepath):
    """Write corrected queries to a SQL file preserving tags and comments."""
    lines = []
    for name, comment_lines, _original_sql in queries_info:
        lines.append(f"-- @name: {name}")
        for comment in comment_lines:
            lines.append(comment)
        lines.append(FIXES[name]["sql"])
        lines.append("")
    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_audit_report(report, filepath):
    """Write the audit report JSON."""
    with open(filepath, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")


# ── Main pipeline ──

def main():
    # Parse queries
    queries_info = parse_queries("/app/queries.sql")
    expected = load_expected("/app/expected_results.json")

    # Connect to database
    conn = connect_db()

    # Analyze each query
    report_queries = {}
    bug_type_counts = {}
    failure_mode_counts = {"error": 0, "wrong_results": 0}
    high_risk_count = 0
    bugs_found = 0

    for name, _comments, sql in queries_info:
        success, result = execute_query(conn, sql)

        if not success:
            failure_mode = "error"
            error_msg = result
        else:
            exp = expected.get(name)
            if exp is not None and result != exp:
                failure_mode = "wrong_results"
                error_msg = None
            elif exp is not None and result == exp:
                # Query is already correct — shouldn't happen with original queries
                failure_mode = None
                error_msg = None
            else:
                failure_mode = None
                error_msg = None

        if failure_mode is not None:
            bugs_found += 1
            bug_type = classify_bug(name, sql, failure_mode,
                                     error_msg if failure_mode == "error" else None)
            risk = assess_risk(failure_mode)

            report_queries[name] = {
                "status": "fixed",
                "bug_type": bug_type,
                "failure_mode": failure_mode,
                "risk_level": risk,
                "fix_description": FIXES[name]["description"],
            }

            bug_type_counts[bug_type] = bug_type_counts.get(bug_type, 0) + 1
            failure_mode_counts[failure_mode] += 1
            if risk == "high":
                high_risk_count += 1

            print(f"  [{failure_mode.upper():>13}] {name}: {bug_type} "
                  f"(risk: {risk})")
        else:
            print(f"  [           OK] {name}")

    conn.close()

    # Build report
    report = {
        "queries": report_queries,
        "summary": {
            "total_queries": len(queries_info),
            "bugs_found": bugs_found,
            "by_type": bug_type_counts,
            "by_failure_mode": failure_mode_counts,
            "high_risk_count": high_risk_count,
        },
    }

    # Write output files
    write_fixed_queries(queries_info, "/app/queries_fixed.sql")
    print(f"\nWrote /app/queries_fixed.sql ({len(queries_info)} queries)")

    write_audit_report(report, "/app/audit_report.json")
    print(f"Wrote /app/audit_report.json ({bugs_found} bugs classified)")

    # Verify fixes
    print("\nVerifying fixed queries...")
    conn = connect_db()
    all_ok = True
    for name in FIXES:
        fixed_sql = FIXES[name]["sql"].rstrip(";")
        success, result = execute_query(conn, fixed_sql)
        if not success:
            print(f"  FAIL {name}: {result}")
            all_ok = False
        else:
            exp = expected.get(name)
            if exp is not None and result != exp:
                print(f"  MISMATCH {name}: expected {exp}, got {result}")
                all_ok = False
            else:
                print(f"  OK   {name} ({len(result)} rows)")
    conn.close()

    if not all_ok:
        print("\nSome fixes are incorrect!")
        sys.exit(1)

    print(f"\nAll {len(FIXES)} queries fixed and verified.")


if __name__ == "__main__":
    main()
