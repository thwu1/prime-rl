"""
Generate optimal covering index strategy for 7 analytical queries served via
sql.js-httpvfs, under a 6-index budget with partial index and ANALYZE requirements.

Index design principles for HTTP-VFS:
  - COVERING INDEX: all columns referenced by a query must appear in the index
    to avoid random table-row lookups (each = separate HTTP Range request)
  - SEARCH (not SCAN): equality-predicate columns at the index prefix enable
    O(log N) B-tree traversal instead of O(N) sequential scan
  - Column ordering: equality cols → range cols → GROUP BY cols → covering cols
  - Partial indexes: WHERE clause on CREATE INDEX excludes irrelevant rows,
    reducing index B-tree size and page count on the HTTP server

Index consolidation strategy:
  Q3 and Q7 share index (user_id, ts, event_type, value):
    - Q3 (WHERE user_id=? ORDER BY ts DESC LIMIT 10): SEARCH on user_id,
      ts at position 2 enables backward scan for ORDER BY DESC without temp
      B-tree, event_type covers SELECT
    - Q7 (WHERE user_id=? AND event_type=? ORDER BY ts DESC): SEARCH on
      user_id, post-filter event_type at position 3, ts ordering still works
      since user_id equality scopes the scan, value covers SELECT

  Q6 uses a partial index WHERE event_type = 'purchase':
    - Only ~10% of rows are purchases, so the partial index is ~10x smaller
    - The query's WHERE includes event_type='purchase', satisfying the
      partial predicate
    - Remaining predicates (country_code, ts range) use index columns for SEARCH
"""

import sqlite3
import sys

DB_PATH = '/app/analytics.db'
OPTIMIZE_PATH = '/app/optimize.sql'

INDEX_SPECS = [
    {
        'name': 'idx_q1_purchase_ts_country',
        'table': 'events',
        'columns': ['event_type', 'ts', 'country_code'],
        'where': None,
        'query': 'Q1',
        'rationale': (
            'Q1: WHERE event_type=? AND ts>=? AND ts<? '
            'GROUP BY country_code SELECT COUNT(*). '
            'event_type: equality prefix; ts: range; country_code: covering.'
        ),
    },
    {
        'name': 'idx_q2_category_user_value',
        'table': 'events',
        'columns': ['category', 'user_id', 'value'],
        'where': None,
        'query': 'Q2',
        'rationale': (
            'Q2: WHERE category=? AND value IS NOT NULL '
            'GROUP BY user_id SELECT SUM(value). '
            'category: equality prefix; user_id: GROUP BY; value: covering.'
        ),
    },
    {
        'name': 'idx_q3q7_user_ts_type_value',
        'table': 'events',
        'columns': ['user_id', 'ts', 'event_type', 'value'],
        'where': None,
        'query': 'Q3+Q7 (shared)',
        'rationale': (
            'Q3: WHERE user_id=? ORDER BY ts DESC LIMIT 10 SELECT ts, event_type. '
            'Q7: WHERE user_id=? AND event_type=? ORDER BY ts DESC SELECT ts, value. '
            'user_id: equality prefix for both; ts: position 2 enables ORDER BY DESC '
            'without temp B-tree (critical for Q3 LIMIT); event_type: covers Q3 SELECT '
            'and Q7 WHERE (post-filter); value: covers Q7 SELECT.'
        ),
    },
    {
        'name': 'idx_q4_type_device_user',
        'table': 'events',
        'columns': ['event_type', 'device', 'user_id'],
        'where': None,
        'query': 'Q4',
        'rationale': (
            'Q4: WHERE event_type=? GROUP BY device '
            'SELECT COUNT(DISTINCT user_id). '
            'event_type: equality prefix; device: GROUP BY (sorted after prefix); '
            'user_id: covering for COUNT(DISTINCT).'
        ),
    },
    {
        'name': 'idx_q5_type_category_value',
        'table': 'events',
        'columns': ['event_type', 'category', 'value'],
        'where': None,
        'query': 'Q5',
        'rationale': (
            'Q5: WHERE event_type=? AND value>0 '
            'GROUP BY category SELECT AVG(value), COUNT(*). '
            'event_type: equality prefix; category: GROUP BY (sorted after prefix, '
            'avoids temp B-tree); value: covering + filter + aggregate.'
        ),
    },
    {
        'name': 'idx_q6_partial_purchase_country_ts',
        'table': 'events',
        'columns': ['country_code', 'ts', 'user_id', 'value'],
        'where': "event_type = 'purchase'",
        'query': 'Q6 (partial)',
        'rationale': (
            'Q6: WHERE event_type=purchase AND country_code=? AND ts>=? AND ts<? '
            'SELECT SUM(value), COUNT(*), COUNT(DISTINCT user_id). '
            'PARTIAL INDEX WHERE event_type=purchase excludes ~90% of rows. '
            'country_code: equality prefix; ts: range; '
            'user_id + value: covering for aggregates.'
        ),
    },
]


def build_optimize_sql():
    """Generate the optimize.sql content."""
    lines = []
    lines.append('-- Covering index strategy for HTTP-VFS query optimization')
    lines.append('-- 6 indexes for 7 queries (Q3+Q7 consolidated, Q6 partial)')
    lines.append('')

    for spec in INDEX_SPECS:
        lines.append(f'-- {spec["query"]}: {spec["rationale"]}')
        cols = ', '.join(spec['columns'])
        where_clause = f' WHERE {spec["where"]}' if spec['where'] else ''
        lines.append(
            f'CREATE INDEX IF NOT EXISTS {spec["name"]} '
            f'ON {spec["table"]}({cols}){where_clause};'
        )
        lines.append('')

    lines.append('-- Collect statistics for cost-based index selection')
    lines.append('ANALYZE;')
    lines.append('')
    lines.append('-- Reduce page size for HTTP range-request serving')
    lines.append('-- journal_mode must be DELETE for page_size change to take effect')
    lines.append('PRAGMA journal_mode = DELETE;')
    lines.append('PRAGMA page_size = 1024;')
    lines.append('VACUUM;')

    return '\n'.join(lines) + '\n'


def verify_solution():
    """Verify that optimize.sql produces correct query plans."""
    conn = sqlite3.connect(DB_PATH)

    queries = {
        'Q1': ("SELECT country_code, COUNT(*) as cnt FROM events "
               "WHERE event_type = 'purchase' AND ts >= 1704067200 AND ts < 1706745600 "
               "GROUP BY country_code ORDER BY cnt DESC"),
        'Q2': ("SELECT user_id, SUM(value) as total_value FROM events "
               "WHERE category = 'electronics' AND value IS NOT NULL "
               "GROUP BY user_id ORDER BY total_value DESC LIMIT 20"),
        'Q3': ("SELECT ts, event_type FROM events "
               "WHERE user_id = 'U00042' ORDER BY ts DESC LIMIT 10"),
        'Q4': ("SELECT device, COUNT(DISTINCT user_id) as unique_users FROM events "
               "WHERE event_type = 'pageview' GROUP BY device"),
        'Q5': ("SELECT category, AVG(value) as avg_value, COUNT(*) as cnt FROM events "
               "WHERE event_type = 'purchase' AND value > 0 "
               "GROUP BY category ORDER BY avg_value DESC"),
        'Q6': ("SELECT SUM(value) as total_revenue, COUNT(*) as num_transactions, "
               "COUNT(DISTINCT user_id) as unique_buyers FROM events "
               "WHERE event_type = 'purchase' AND country_code = 'US' "
               "AND ts >= 1719792000 AND ts < 1722470400"),
        'Q7': ("SELECT event_type, ts, value FROM events "
               "WHERE user_id = 'U00042' AND event_type = 'purchase' "
               "ORDER BY ts DESC"),
    }

    print(f'Verifying {len(queries)} queries...')
    all_ok = True
    for qname, query in queries.items():
        plan_rows = conn.execute(f'EXPLAIN QUERY PLAN {query}').fetchall()
        plan_str = ' '.join(str(r) for r in plan_rows)
        has_covering = 'COVERING INDEX' in plan_str
        has_search = 'SEARCH' in plan_str
        status = 'OK' if (has_covering and has_search) else 'FAIL'
        if status == 'FAIL':
            all_ok = False
        print(f'  {qname}: {status} (covering={has_covering}, search={has_search})')
        if status == 'FAIL':
            print(f'       Plan: {plan_str}')

    # Check index count
    idx_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    print(f'\nUser-created indexes: {idx_count} (max 6)')

    # Check partial index
    partial = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL AND sql LIKE '%WHERE %'"
    ).fetchall()
    print(f'Partial indexes: {len(partial)} ({", ".join(r[0] for r in partial)})')

    # Check ANALYZE
    stat_count = conn.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
    print(f'sqlite_stat1 rows: {stat_count}')

    # Check page size
    page_size = conn.execute('PRAGMA page_size').fetchone()[0]
    print(f'Page size: {page_size}')

    conn.close()

    if not all_ok or idx_count > 6 or len(partial) < 1 or stat_count == 0:
        print('\nERROR: Solution verification failed')
        sys.exit(1)

    print('\nAll checks passed.')


if __name__ == '__main__':
    sql_content = build_optimize_sql()

    with open(OPTIMIZE_PATH, 'w') as f:
        f.write(sql_content)

    print(f'Written {OPTIMIZE_PATH} ({len(INDEX_SPECS)} indexes, '
          f'{sum(1 for s in INDEX_SPECS if s["where"])} partial)')

    # Apply and verify
    import subprocess
    subprocess.run(
        ['sqlite3', DB_PATH],
        input=sql_content,
        text=True,
        check=True,
    )

    verify_solution()
