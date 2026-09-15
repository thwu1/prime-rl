#!/usr/bin/env python3
"""Query interface for the users database with WAF protection.

Accepts a SQL WHERE clause, validates it against the WAF, and executes
the query against the users table if allowed.
"""

import sys
import sqlite3
from waf import WAF

DB_PATH = '/app/database.db'


def run_query(where_clause):
    waf = WAF()
    allowed, triggered = waf.check(where_clause)

    if not allowed:
        rules = ', '.join(r[0] for r in triggered)
        print(f"BLOCKED by WAF rules: {rules}")
        return None

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = f"SELECT * FROM users WHERE {where_clause}"
        cursor.execute(query)
        results = cursor.fetchall()

        if results:
            columns = [desc[0] for desc in cursor.description]
            print('\t'.join(columns))
            print('-' * 60)
            for row in results:
                print('\t'.join(
                    str(v) if v is not None else 'NULL' for v in row))
        else:
            print("No results found.")

        conn.close()
        return results
    except Exception as e:
        print(f"Query error: {e}")
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 query_runner.py \"<WHERE clause>\"")
        print("       python3 query_runner.py --stdin")
        sys.exit(1)

    if sys.argv[1] == '--stdin':
        where_clause = sys.stdin.read().strip()
    else:
        where_clause = ' '.join(sys.argv[1:])

    run_query(where_clause)
