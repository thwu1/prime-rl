#!/usr/bin/env python3

"""
ORDER BY Resolution Audit — Solver

Analyzes 10 SQL queries for PostgreSQL ORDER BY scoping bugs.
PostgreSQL uses two resolution paths for ORDER BY identifiers:
  - SQL-92 path: bare identifiers match SELECT-list aliases first.
  - SQL-99 path: expressions (qualified refs, COLLATE, unary ops)
                 resolve from FROM scope only — aliases are invisible.

Additionally:
  - GROUP BY resolves FROM scope first, then aliases (opposite of ORDER BY).
  - Window OVER(ORDER BY) resolves exclusively from FROM scope.
  - UNION ORDER BY only accepts column names/positions, not expressions.

This solver evaluates each query, classifies it, fixes buggy ones,
and writes a diagnostic.json report.
"""

import subprocess
import json
import sys


def run_query(qnum):
    """Execute query and return (success, output_lines)."""
    result = subprocess.run(
        [
            "psql", "-d", "benchdb", "-U", "postgres",
            "-t", "-A", "-F", "|",
            "-f", f"/app/queries/q{qnum}.sql",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    return True, lines


def load_expected(qnum):
    """Load expected output."""
    with open(f"/app/expected/q{qnum}.txt") as f:
        return [l.strip() for l in f if l.strip()]


def check_match(qnum):
    """Check if query output matches expected. Returns (matches, detail)."""
    ok, result = run_query(qnum)
    if not ok:
        return False, f"ERROR: {result}"
    expected = load_expected(qnum)
    if result == expected:
        return True, "output matches"
    return False, f"got {len(result)} rows, expected {len(expected)}"


# ─── Query analysis and fixes ───────────────────────────────────────────────

# Each entry: (is_buggy, category, explanation, fixed_sql_or_None)
ANALYSIS = {
    1: {
        "buggy": True,
        "category": "alias_shadow",
        "explanation": (
            "Bare identifier 'amount' matches alias '-amount AS amount' via "
            "SQL-92 path, sorting by the negated value instead of the original "
            "column. Fix: qualify as transactions.amount to force expression path."
        ),
        "fixed_sql": """\
-- Report: transactions with negated amounts, sorted by original amount ascending
SELECT account, -amount AS amount
FROM transactions
ORDER BY transactions.amount;
""",
    },
    2: {
        "buggy": True,
        "category": "group_order_precedence",
        "explanation": (
            "GROUP BY 'amount' resolves to the table column (10 distinct values), "
            "producing 10 groups instead of 2. ORDER BY 'amount' resolves to the "
            "CASE alias. Fix: GROUP BY 1 to group by the CASE expression."
        ),
        "fixed_sql": """\
-- Report: transaction count by size category, sorted by category
SELECT
    CASE WHEN amount >= 250 THEN 'large' ELSE 'small' END AS amount,
    COUNT(*) AS tx_count
FROM transactions
GROUP BY 1
ORDER BY amount;
""",
    },
    3: {
        "buggy": False,
        "category": "none",
        "explanation": (
            "CORRECT: OVER(ORDER BY SUM(amount) DESC) uses the aggregate "
            "expression directly, not the alias 'total'. Expression resolves "
            "correctly from FROM scope via the aggregate. No bug."
        ),
        "fixed_sql": None,
    },
    4: {
        "buggy": True,
        "category": "quoted_case",
        "explanation": (
            'Quoted alias "Amount" (capital A) does not match unquoted '
            "'amount' (lowercase) via case-sensitive strcmp. Falls through to "
            "expression path, sorts by original column instead of negated alias. "
            'Fix: ORDER BY "Amount" to match the quoted alias exactly.'
        ),
        "fixed_sql": """\
-- Report: transactions with inverted amounts, sorted by the inverted amount ascending
SELECT account, -amount AS "Amount"
FROM transactions
ORDER BY "Amount";
""",
    },
    5: {
        "buggy": True,
        "category": "window_scope",
        "explanation": (
            "Window OVER(ORDER BY ...) resolves from FROM scope only. "
            "'total' is a SELECT alias for SUM(amount), not a FROM column. "
            "Fix: use SUM(amount) directly in the OVER clause."
        ),
        "fixed_sql": """\
-- Report: accounts ranked by total, showing rank position
SELECT account,
       SUM(amount) AS total,
       RANK() OVER (ORDER BY SUM(amount) DESC) AS ranking
FROM transactions
GROUP BY account
ORDER BY ranking;
""",
    },
    6: {
        "buggy": False,
        "category": "none",
        "explanation": (
            "CORRECT: ORDER BY account COLLATE \"C\" uses the original column "
            "name 'account', not the alias 'acct'. The expression path resolves "
            "'account' from FROM scope where it exists. No bug."
        ),
        "fixed_sql": None,
    },
    7: {
        "buggy": True,
        "category": "union_expression",
        "explanation": (
            "UNION ORDER BY only accepts result column names or ordinal "
            "positions, not arbitrary expressions. '-amount' is an expression. "
            "Fix: ORDER BY amount DESC."
        ),
        "fixed_sql": """\
-- Report: all credit and debit transactions, sorted by amount descending
(SELECT account, amount, 'credit' AS direction FROM transactions WHERE tx_type = 'credit')
UNION ALL
(SELECT account, amount, 'debit' AS direction FROM transactions WHERE tx_type = 'debit')
ORDER BY amount DESC;
""",
    },
    8: {
        "buggy": True,
        "category": "collate_expression",
        "explanation": (
            "COLLATE wraps 'acct' into a CollateExpr node, making it an "
            "expression. The expression path looks for 'acct' in FROM scope, "
            "but 'acct' is only a SELECT alias for 'account'. "
            "Fix: use the original column name 'account'."
        ),
        "fixed_sql": """\
-- Report: transactions sorted by account alias (C locale) then amount
SELECT account AS acct, amount
FROM transactions
ORDER BY account COLLATE "C", amount;
""",
    },
    9: {
        "buggy": False,
        "category": "none",
        "explanation": (
            "CORRECT: ORDER BY amount + fee is an expression with bare column "
            "names. The expression path resolves 'amount' and 'fee' from FROM "
            "scope where they exist as actual columns. The alias 'total_cost' "
            "is not involved. No bug."
        ),
        "fixed_sql": None,
    },
    10: {
        "buggy": True,
        "category": "unary_expression",
        "explanation": (
            "Unary '+' makes '+fee' an expression. The expression path finds "
            "'fee' in the table (original column), ignoring the alias "
            "'-fee AS fee'. Sorts by original fee, not negated. "
            "Fix: remove the '+' so bare 'fee' matches the alias."
        ),
        "fixed_sql": """\
-- Report: fee inversion sorted ascending (most negative first)
SELECT account, -fee AS fee
FROM transactions
ORDER BY fee;
""",
    },
}


def main():
    print("=" * 60)
    print("ORDER BY Resolution Audit")
    print("=" * 60)

    # Phase 1: Evaluate each query
    print("\n--- Phase 1: Evaluate queries ---\n")
    for qnum in range(1, 11):
        matches, detail = check_match(qnum)
        info = ANALYSIS[qnum]
        status = "CORRECT" if not info["buggy"] else "BUGGY"
        print(f"q{qnum:2d}: {status:7s} | {detail}")
        if info["buggy"]:
            print(f"       Category: {info['category']}")
            print(f"       {info['explanation'][:80]}...")

    # Phase 2: Apply fixes to buggy queries
    print("\n--- Phase 2: Apply fixes ---\n")
    for qnum in range(1, 11):
        info = ANALYSIS[qnum]
        if info["buggy"] and info["fixed_sql"]:
            with open(f"/app/queries/q{qnum}.sql", "w") as f:
                f.write(info["fixed_sql"])
            print(f"q{qnum}: fixed")

    # Phase 3: Verify all queries now produce correct output
    print("\n--- Phase 3: Verify fixes ---\n")
    all_pass = True
    for qnum in range(1, 11):
        matches, detail = check_match(qnum)
        status = "PASS" if matches else "FAIL"
        print(f"q{qnum:2d}: {status} | {detail}")
        if not matches:
            all_pass = False

    # Phase 4: Write diagnostic.json
    print("\n--- Phase 4: Write diagnostic.json ---\n")
    diagnostic = {
        "queries": [
            {
                "query": qnum,
                "status": "buggy" if ANALYSIS[qnum]["buggy"] else "correct",
                "category": ANALYSIS[qnum]["category"],
            }
            for qnum in range(1, 11)
        ]
    }
    with open("/app/diagnostic.json", "w") as f:
        json.dump(diagnostic, f, indent=2)
    print("Written /app/diagnostic.json")

    if all_pass:
        print("\nAll 10 queries verified. Diagnostic report written.")
    else:
        print("\nSome queries still failing!")
        sys.exit(1)


if __name__ == "__main__":
    main()
