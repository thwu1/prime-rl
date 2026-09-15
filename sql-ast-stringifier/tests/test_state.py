
"""
Tests for the SQL AST stringifier.

Each test case provides an AST JSON object and the expected SQL output.
The stringifier CLI is invoked in batch mode for efficiency.
"""

import json
import os
import subprocess
import pytest

# ── Test Case Definitions ────────────────────────────────────────────

TEST_CASES = [
    # 0: Simple SELECT with WHERE (baseline)
    {
        "name": "simple_select",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "a"}, "as": None},
                {"expr": {"type": "column_ref", "table": None, "column": "b"}, "as": None},
            ],
            "from": [{"db": None, "table": "t", "as": None}],
            "where": {
                "type": "binary_expr",
                "operator": ">",
                "left": {"type": "column_ref", "table": None, "column": "a"},
                "right": {"type": "number", "value": 1},
            },
        },
        "expected": 'SELECT "a", "b" FROM "t" WHERE "a" > 1',
    },
    # 1: CASE WHEN expression (baseline)
    {
        "name": "case_when",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "case",
                        "expr": None,
                        "args": [
                            {
                                "type": "when",
                                "cond": {
                                    "type": "binary_expr",
                                    "operator": ">",
                                    "left": {"type": "column_ref", "table": None, "column": "score"},
                                    "right": {"type": "number", "value": 90},
                                },
                                "result": {"type": "single_quote_string", "value": "A"},
                            },
                            {
                                "type": "when",
                                "cond": {
                                    "type": "binary_expr",
                                    "operator": ">",
                                    "left": {"type": "column_ref", "table": None, "column": "score"},
                                    "right": {"type": "number", "value": 80},
                                },
                                "result": {"type": "single_quote_string", "value": "B"},
                            },
                            {"type": "else", "result": {"type": "single_quote_string", "value": "C"}},
                        ],
                    },
                    "as": "grade",
                }
            ],
            "from": [{"db": None, "table": "students", "as": None}],
        },
        "expected": """SELECT CASE WHEN "score" > 90 THEN 'A' WHEN "score" > 80 THEN 'B' ELSE 'C' END AS "grade" FROM "students\"""",
    },
    # 2: Function call with alias (baseline)
    {
        "name": "function_call",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "function",
                        "name": {"name": [{"type": "default", "value": "COALESCE"}]},
                        "args": {
                            "type": "expr_list",
                            "value": [
                                {"type": "column_ref", "table": None, "column": "name"},
                                {"type": "single_quote_string", "value": "unknown"},
                            ],
                        },
                    },
                    "as": "display_name",
                }
            ],
            "from": [{"db": None, "table": "users", "as": None}],
        },
        "expected": """SELECT COALESCE("name", 'unknown') AS "display_name" FROM "users\"""",
    },
    # 3: JOIN with ON clause (baseline)
    {
        "name": "join_on",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": "u", "column": "name"}, "as": None}
            ],
            "from": [
                {"db": None, "table": "users", "as": "u"},
                {
                    "db": None,
                    "table": "orders",
                    "as": "o",
                    "join": "LEFT JOIN",
                    "on": {
                        "type": "binary_expr",
                        "operator": "=",
                        "left": {"type": "column_ref", "table": "u", "column": "id"},
                        "right": {"type": "column_ref", "table": "o", "column": "user_id"},
                    },
                },
            ],
        },
        "expected": 'SELECT "u"."name" FROM "users" AS "u" LEFT JOIN "orders" AS "o" ON "u"."id" = "o"."user_id"',
    },
    # 4: Top-level UNION ALL (baseline – unionToSQL handles _next correctly)
    {
        "name": "top_level_union",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "x"}, "as": None}
            ],
            "from": [{"db": None, "table": "t1", "as": None}],
            "_next": {
                "type": "select",
                "columns": [
                    {"expr": {"type": "column_ref", "table": None, "column": "y"}, "as": None}
                ],
                "from": [{"db": None, "table": "t2", "as": None}],
            },
            "set_op": "union all",
        },
        "expected": 'SELECT "x" FROM "t1" UNION ALL SELECT "y" FROM "t2"',
    },
    # ── Bug-specific tests ──────────────────────────────────────────
    # 5: Window function with BETWEEN frame clause (Bug 1)
    {
        "name": "window_frame_between",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "SUM",
                        "args": {
                            "expr": {"type": "column_ref", "table": None, "column": "amount"}
                        },
                        "over": {
                            "partitionby": [
                                {"type": "column_ref", "table": None, "column": "dept"}
                            ],
                            "orderby": [
                                {
                                    "expr": {"type": "column_ref", "table": None, "column": "hire_date"},
                                    "type": "ASC",
                                }
                            ],
                            "window_frame_clause": {
                                "type": "ROWS",
                                "start": {"type": "UNBOUNDED PRECEDING"},
                                "end": {"type": "CURRENT ROW"},
                            },
                        },
                    },
                    "as": "running_total",
                }
            ],
            "from": [{"db": None, "table": "employees", "as": None}],
        },
        "expected": 'SELECT SUM("amount") OVER (PARTITION BY "dept" ORDER BY "hire_date" ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "running_total" FROM "employees"',
    },
    # 6: WITH RECURSIVE CTE (Bug 2)
    {
        "name": "cte_recursive",
        "ast": {
            "type": "select",
            "with": [
                {
                    "name": {"type": "default", "value": "nums"},
                    "recursive": True,
                    "stmt": {
                        "ast": {
                            "type": "select",
                            "columns": [
                                {"expr": {"type": "number", "value": 1}, "as": "n"}
                            ],
                        }
                    },
                }
            ],
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "*"}, "as": None}
            ],
            "from": [{"db": None, "table": "nums", "as": None}],
        },
        "expected": 'WITH RECURSIVE "nums" AS (SELECT 1 AS "n") SELECT * FROM "nums"',
    },
    # 7: PostgreSQL :: cast syntax (Bug 3)
    {
        "name": "cast_double_colon",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "cast",
                        "keyword": "cast",
                        "expr": {"type": "column_ref", "table": None, "column": "price"},
                        "symbol": "::",
                        "target": [{"dataType": "numeric"}],
                    },
                    "as": None,
                }
            ],
            "from": [{"db": None, "table": "products", "as": None}],
        },
        "expected": 'SELECT "price"::numeric FROM "products"',
    },
    # 8: COUNT(DISTINCT ...) aggregate (Bug 4)
    {
        "name": "aggregate_distinct",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "COUNT",
                        "args": {
                            "expr": {"type": "column_ref", "table": None, "column": "status"},
                            "distinct": "DISTINCT",
                        },
                    },
                    "as": "unique_statuses",
                }
            ],
            "from": [{"db": None, "table": "orders", "as": None}],
        },
        "expected": 'SELECT COUNT(DISTINCT "status") AS "unique_statuses" FROM "orders"',
    },
    # 9: Aggregate FILTER clause (Bug 5)
    {
        "name": "aggregate_filter",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "COUNT",
                        "args": {"expr": {"type": "star", "value": "*"}},
                    },
                    "as": "total",
                },
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "COUNT",
                        "args": {"expr": {"type": "star", "value": "*"}},
                        "filter": {
                            "where": {
                                "type": "binary_expr",
                                "operator": "=",
                                "left": {"type": "column_ref", "table": None, "column": "active"},
                                "right": {"type": "boolean", "value": "true"},
                            }
                        },
                    },
                    "as": "active_count",
                },
            ],
            "from": [{"db": None, "table": "users", "as": None}],
        },
        "expected": 'SELECT COUNT(*) AS "total", COUNT(*) FILTER (WHERE "active" = TRUE) AS "active_count" FROM "users"',
    },
    # 10: Subquery with UNION in FROM (Bug 6)
    {
        "name": "subquery_union",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "*"}, "as": None}
            ],
            "from": [
                {
                    "db": None,
                    "table": None,
                    "as": "combined",
                    "expr": {
                        "type": "select",
                        "parentheses": True,
                        "columns": [
                            {
                                "expr": {"type": "column_ref", "table": None, "column": "id"},
                                "as": None,
                            }
                        ],
                        "from": [{"db": None, "table": "users", "as": None}],
                        "_next": {
                            "type": "select",
                            "columns": [
                                {
                                    "expr": {
                                        "type": "column_ref",
                                        "table": None,
                                        "column": "id",
                                    },
                                    "as": None,
                                }
                            ],
                            "from": [{"db": None, "table": "admins", "as": None}],
                        },
                        "set_op": "union",
                    },
                }
            ],
        },
        "expected": 'SELECT * FROM (SELECT "id" FROM "users" UNION SELECT "id" FROM "admins") AS "combined"',
    },
    # 11: DISTINCT ON (PostgreSQL) (Bug 7)
    {
        "name": "distinct_on",
        "ast": {
            "type": "select",
            "distinct": {
                "type": "DISTINCT",
                "columns": [
                    {"type": "column_ref", "table": None, "column": "department"},
                    {"type": "column_ref", "table": None, "column": "role"},
                ],
            },
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "department"}, "as": None},
                {"expr": {"type": "column_ref", "table": None, "column": "role"}, "as": None},
                {"expr": {"type": "column_ref", "table": None, "column": "salary"}, "as": None},
            ],
            "from": [{"db": None, "table": "employees", "as": None}],
        },
        "expected": 'SELECT DISTINCT ON ("department", "role") "department", "role", "salary" FROM "employees"',
    },
    # 12: ORDER BY with NULLS FIRST (Bug 8)
    {
        "name": "order_by_nulls",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": None, "column": "name"}, "as": None},
                {"expr": {"type": "column_ref", "table": None, "column": "score"}, "as": None},
            ],
            "from": [{"db": None, "table": "results", "as": None}],
            "orderby": [
                {
                    "expr": {"type": "column_ref", "table": None, "column": "score"},
                    "type": "DESC",
                    "nulls": "NULLS FIRST",
                }
            ],
        },
        "expected": 'SELECT "name", "score" FROM "results" ORDER BY "score" DESC NULLS FIRST',
    },
    # 13: LATERAL join (Bug 9)
    {
        "name": "lateral_join",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": "u", "column": "name"}, "as": None},
                {"expr": {"type": "column_ref", "table": "recent", "column": "total"}, "as": None},
            ],
            "from": [
                {"db": None, "table": "users", "as": "u"},
                {
                    "join": "LEFT JOIN",
                    "lateral": True,
                    "db": None,
                    "table": None,
                    "expr": {
                        "type": "select",
                        "parentheses": True,
                        "columns": [
                            {
                                "expr": {
                                    "type": "aggr_func",
                                    "name": "SUM",
                                    "args": {"expr": {"type": "column_ref", "table": None, "column": "amount"}},
                                },
                                "as": "total",
                            }
                        ],
                        "from": [{"db": None, "table": "orders", "as": None}],
                        "where": {
                            "type": "binary_expr",
                            "operator": "=",
                            "left": {"type": "column_ref", "table": "orders", "column": "user_id"},
                            "right": {"type": "column_ref", "table": "u", "column": "id"},
                        },
                    },
                    "as": "recent",
                    "on": {"type": "boolean", "value": "true"},
                },
            ],
        },
        "expected": 'SELECT "u"."name", "recent"."total" FROM "users" AS "u" LEFT JOIN LATERAL (SELECT SUM("amount") AS "total" FROM "orders" WHERE "orders"."user_id" = "u"."id") AS "recent" ON TRUE',
    },
    # ── Compound tests (require multiple fixes) ─────────────────────
    # 14: Compound – CTE RECURSIVE + window BETWEEN + ORDER BY NULLS in two locations
    {
        "name": "compound_cte_window_nulls",
        "ast": {
            "type": "select",
            "with": [
                {
                    "name": {"type": "default", "value": "ranked"},
                    "recursive": True,
                    "stmt": {
                        "ast": {
                            "type": "select",
                            "columns": [
                                {"expr": {"type": "column_ref", "table": None, "column": "id"}, "as": None},
                                {"expr": {"type": "column_ref", "table": None, "column": "score"}, "as": None},
                            ],
                            "from": [{"db": None, "table": "base_items", "as": None}],
                            "_next": {
                                "type": "select",
                                "columns": [
                                    {"expr": {"type": "column_ref", "table": "r", "column": "id"}, "as": None},
                                    {"expr": {"type": "column_ref", "table": "r", "column": "score"}, "as": None},
                                ],
                                "from": [
                                    {"db": None, "table": "ranked", "as": "r"},
                                    {
                                        "join": "INNER JOIN",
                                        "db": None,
                                        "table": "links",
                                        "as": "l",
                                        "on": {
                                            "type": "binary_expr",
                                            "operator": "=",
                                            "left": {"type": "column_ref", "table": "r", "column": "id"},
                                            "right": {"type": "column_ref", "table": "l", "column": "parent_id"},
                                        },
                                    },
                                ],
                            },
                            "set_op": "UNION ALL",
                        }
                    },
                }
            ],
            "columns": [
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "SUM",
                        "args": {"expr": {"type": "column_ref", "table": None, "column": "score"}},
                        "over": {
                            "orderby": [
                                {
                                    "expr": {"type": "column_ref", "table": None, "column": "score"},
                                    "type": "DESC",
                                    "nulls": "NULLS LAST",
                                }
                            ],
                            "window_frame_clause": {
                                "type": "ROWS",
                                "start": {"type": "UNBOUNDED PRECEDING"},
                                "end": {"type": "UNBOUNDED FOLLOWING"},
                            },
                        },
                    },
                    "as": "running_sum",
                }
            ],
            "from": [{"db": None, "table": "ranked", "as": None}],
            "orderby": [
                {
                    "expr": {"type": "column_ref", "table": None, "column": "score"},
                    "type": "DESC",
                    "nulls": "NULLS FIRST",
                }
            ],
        },
        "expected": 'WITH RECURSIVE "ranked" AS (SELECT "id", "score" FROM "base_items" UNION ALL SELECT "r"."id", "r"."score" FROM "ranked" AS "r" INNER JOIN "links" AS "l" ON "r"."id" = "l"."parent_id") SELECT SUM("score") OVER (ORDER BY "score" DESC NULLS LAST ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS "running_sum" FROM "ranked" ORDER BY "score" DESC NULLS FIRST',
    },
    # 15: Compound – :: cast inside COUNT(DISTINCT ...)
    {
        "name": "compound_cast_distinct",
        "ast": {
            "type": "select",
            "columns": [
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "COUNT",
                        "args": {
                            "expr": {
                                "type": "cast",
                                "keyword": "cast",
                                "expr": {"type": "column_ref", "table": None, "column": "code"},
                                "symbol": "::",
                                "target": [{"dataType": "text"}],
                            },
                            "distinct": "DISTINCT",
                        },
                    },
                    "as": None,
                }
            ],
            "from": [{"db": None, "table": "items", "as": None}],
        },
        "expected": 'SELECT COUNT(DISTINCT "code"::text) FROM "items"',
    },
    # 16: Compound – LATERAL + FILTER + subquery UNION (bugs 5, 6, 9)
    {
        "name": "compound_lateral_filter_subunion",
        "ast": {
            "type": "select",
            "columns": [
                {"expr": {"type": "column_ref", "table": "u", "column": "name"}, "as": None},
                {
                    "expr": {
                        "type": "aggr_func",
                        "name": "COUNT",
                        "args": {"expr": {"type": "star", "value": "*"}},
                        "filter": {
                            "where": {
                                "type": "binary_expr",
                                "operator": ">",
                                "left": {"type": "column_ref", "table": "t", "column": "amount"},
                                "right": {"type": "number", "value": 100},
                            }
                        },
                    },
                    "as": "big_txns",
                },
            ],
            "from": [
                {"db": None, "table": "users", "as": "u"},
                {
                    "join": "LEFT JOIN",
                    "lateral": True,
                    "db": None,
                    "table": None,
                    "expr": {
                        "type": "select",
                        "parentheses": True,
                        "columns": [
                            {
                                "expr": {"type": "column_ref", "table": None, "column": "amount"},
                                "as": None,
                            }
                        ],
                        "from": [{"db": None, "table": "purchases", "as": None}],
                        "where": {
                            "type": "binary_expr",
                            "operator": "=",
                            "left": {"type": "column_ref", "table": "purchases", "column": "user_id"},
                            "right": {"type": "column_ref", "table": "u", "column": "id"},
                        },
                        "_next": {
                            "type": "select",
                            "columns": [
                                {
                                    "expr": {"type": "column_ref", "table": None, "column": "amount"},
                                    "as": None,
                                }
                            ],
                            "from": [{"db": None, "table": "refunds", "as": None}],
                            "where": {
                                "type": "binary_expr",
                                "operator": "=",
                                "left": {"type": "column_ref", "table": "refunds", "column": "user_id"},
                                "right": {"type": "column_ref", "table": "u", "column": "id"},
                            },
                        },
                        "set_op": "UNION ALL",
                    },
                    "as": "t",
                    "on": {"type": "boolean", "value": "true"},
                },
            ],
            "groupby": {
                "columns": [{"type": "column_ref", "table": "u", "column": "name"}],
            },
        },
        "expected": 'SELECT "u"."name", COUNT(*) FILTER (WHERE "t"."amount" > 100) AS "big_txns" FROM "users" AS "u" LEFT JOIN LATERAL (SELECT "amount" FROM "purchases" WHERE "purchases"."user_id" = "u"."id" UNION ALL SELECT "amount" FROM "refunds" WHERE "refunds"."user_id" = "u"."id") AS "t" ON TRUE GROUP BY "u"."name"',
    },
]


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def batch_results():
    """Run all ASTs through the stringifier in a single batch call."""
    # Ensure Node.js dependencies are installed
    subprocess.run(
        ["npm", "install"],
        cwd="/app",
        capture_output=True,
        timeout=120,
    )

    tsx_bin = "/app/node_modules/.bin/tsx"
    if not os.path.exists(tsx_bin):
        pytest.fail(
            f"tsx binary not found at {tsx_bin}. "
            "npm install may have failed. "
            f"Files in /app: {os.listdir('/app') if os.path.isdir('/app') else 'DIR NOT FOUND'}"
        )

    asts = [tc["ast"] for tc in TEST_CASES]
    result = subprocess.run(
        [tsx_bin, "src/cli.ts"],
        input=json.dumps(asts),
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    if result.returncode != 0:
        err = result.stderr.strip()
        return [{"sql": None, "error": err}] * len(TEST_CASES)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return [
            {"sql": None, "error": f"Invalid JSON: {result.stdout[:300]}"}
        ] * len(TEST_CASES)


def _check(batch_results, idx):
    tc = TEST_CASES[idx]
    r = batch_results[idx]
    assert r["error"] is None, (
        f"[{tc['name']}] Stringifier error: {r['error']}"
    )
    assert r["sql"] == tc["expected"], (
        f"[{tc['name']}]\n  Expected: {tc['expected']}\n  Got:      {r['sql']}"
    )


# ── Baseline tests (should pass without fixes) ──────────────────────

def test_simple_select(batch_results):
    _check(batch_results, 0)

def test_case_when(batch_results):
    _check(batch_results, 1)

def test_function_call(batch_results):
    _check(batch_results, 2)

def test_join_on(batch_results):
    _check(batch_results, 3)

def test_top_level_union(batch_results):
    _check(batch_results, 4)


# ── Bug-specific tests ──────────────────────────────────────────────

def test_window_frame_between(batch_results):
    """Bug 1: Window BETWEEN frame clause must emit start AND end bounds."""
    _check(batch_results, 5)

def test_cte_recursive(batch_results):
    """Bug 2: WITH RECURSIVE must include the RECURSIVE keyword."""
    _check(batch_results, 6)

def test_cast_double_colon(batch_results):
    """Bug 3: PostgreSQL :: cast must produce expr::type, not type::expr."""
    _check(batch_results, 7)

def test_aggregate_distinct(batch_results):
    """Bug 4: Aggregate functions must include the DISTINCT keyword."""
    _check(batch_results, 8)

def test_aggregate_filter(batch_results):
    """Bug 5: Aggregate FILTER (WHERE ...) clause must be emitted."""
    _check(batch_results, 9)

def test_subquery_union(batch_results):
    """Bug 6: Subquery expressions with _next must use union dispatch."""
    _check(batch_results, 10)

def test_distinct_on(batch_results):
    """Bug 7: DISTINCT ON (cols) must include the ON clause with columns."""
    _check(batch_results, 11)

def test_order_by_nulls(batch_results):
    """Bug 8: ORDER BY must include NULLS FIRST/LAST when specified."""
    _check(batch_results, 12)

def test_lateral_join(batch_results):
    """Bug 9: LATERAL keyword must be emitted for lateral join references."""
    _check(batch_results, 13)


# ── Compound tests (require multiple fixes) ─────────────────────────

def test_compound_cte_window_nulls(batch_results):
    """Requires fixes for bugs 1, 2, and 8 (including window ORDER BY nulls)."""
    _check(batch_results, 14)

def test_compound_cast_distinct(batch_results):
    """Requires fixes for bugs 3 and 4."""
    _check(batch_results, 15)

def test_compound_lateral_filter_subunion(batch_results):
    """Requires fixes for bugs 5 (FILTER), 6 (subquery UNION), and 9 (LATERAL)."""
    _check(batch_results, 16)
