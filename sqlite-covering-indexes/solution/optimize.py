#!/usr/bin/env python3
"""Optimize analytics.db for HTTP Range-request serving.

Strategy: Design 7 covering indexes for 8 analytical queries by exploiting
three key optimizations:

1. INDEX SHARING (Q1+Q8): Q8's required columns (event_type, timestamp, user_id)
   are a subset of Q1's index columns, so both queries share one index.

2. INDEX SHARING (Q4+Q5b): Q5's right-side join lookup needs
   (event_type, session_id) which is a prefix of Q4's index
   (event_type, session_id, device_type), so both share one index.

3. PARTIAL INDEX (Q3+Q7): Both Q3 and Q7 filter on event_type='purchase'.
   A partial index stores only ~5500 purchase rows (vs 160K total). With
   ANALYZE, the planner correctly prefers the small partial index over
   larger regular indexes, achieving covering access for both queries.

Column ordering follows: equality filters -> range filters -> GROUP BY -> output.
"""

import sqlite3
import sys

DB = "/app/analytics.db"


def optimize():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # ---------------------------------------------------------------
    # Drop the naive single-column indexes — they waste budget (3 of
    # the 7 allowed slots) and mislead the query planner.
    # ---------------------------------------------------------------
    for idx in ("idx_events_type", "idx_events_timestamp", "idx_events_user"):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")

    # ---------------------------------------------------------------
    # INDEX 1: Q1 + Q8 (shared)
    #
    # Q1: SELECT country, COUNT(DISTINCT user_id)
    #     WHERE event_type='pageview' AND timestamp BETWEEN ? AND ?
    #     GROUP BY country
    #
    # Q8: SELECT date(timestamp,'unixepoch'), COUNT(*), COUNT(DISTINCT user_id)
    #     WHERE event_type='pageview' AND timestamp >= ? AND timestamp < ?
    #     GROUP BY date(timestamp,'unixepoch')
    #
    # Q8's columns {event_type, timestamp, user_id} are a subset of
    # Q1's {event_type, timestamp, country, user_id}. Q1's wider
    # index provides covering access for Q8.
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q1_q8
        ON events(event_type, timestamp, country, user_id)
    """)

    # ---------------------------------------------------------------
    # INDEX 2: Q2
    # SELECT page_url, COUNT(DISTINCT session_id)
    # WHERE device_type='mobile' AND event_type='pageview'
    # GROUP BY page_url
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q2
        ON events(device_type, event_type, page_url, session_id)
    """)

    # ---------------------------------------------------------------
    # INDEX 3: Q3 + Q7 (shared partial index)
    #
    # Both queries filter on event_type='purchase'. A partial index
    # stores only ~5500 purchase events (vs ~160K total), giving the
    # query planner a clear cost advantage over regular indexes.
    #
    # Q3 needs: user_id (join with users), revenue_cents (SUM)
    # Q7 needs: revenue_cents > 10000 (range), country (GROUP BY),
    #           revenue_cents (SUM/AVG/MAX)
    #
    # Column order: user_id first (Q3 join), revenue_cents second
    # (Q7 range filter), country third (Q7 GROUP BY).
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q3_q7
        ON events(user_id, revenue_cents, country)
        WHERE event_type = 'purchase'
    """)

    # ---------------------------------------------------------------
    # INDEX 4: Q4 + Q5b (shared)
    #
    # Q4 subquery: SELECT session_id, device_type, COUNT(*)
    #              WHERE event_type='pageview' GROUP BY session_id
    #
    # Q5 e2 (LEFT JOIN): ON e1.session_id = e2.session_id
    #                     AND e2.event_type = 'purchase'
    #
    # Q5b needs (event_type, session_id) which is a 2-column prefix
    # of Q4's index. SQLite seeks event_type='purchase', session_id=?
    # for the join lookup. Only e2.session_id is needed as output,
    # which is in the index -> COVERING.
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q4_q5b
        ON events(event_type, session_id, device_type)
    """)

    # ---------------------------------------------------------------
    # INDEX 5: Q5 e1 side (referrer conversion — pageview side)
    # WHERE event_type='pageview' AND referrer IS NOT NULL
    # GROUP BY referrer; needs session_id for COUNT(DISTINCT)
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q5a
        ON events(event_type, referrer, session_id)
    """)

    # ---------------------------------------------------------------
    # INDEX 6: Q6 events side (engagement metrics)
    # WHERE event_type='pageview' AND duration_ms IS NOT NULL
    # JOIN pages ON page_url; needs duration_ms (AVG), user_id (DISTINCT)
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX idx_cov_q6
        ON events(event_type, page_url, duration_ms, user_id)
    """)

    # ---------------------------------------------------------------
    # INDEX 7: spare slot — kept empty to stay within budget.
    # The 6 indexes above cover all 8 queries via sharing.
    # Budget: 6/7 used on events.
    # ---------------------------------------------------------------

    conn.commit()

    # ---------------------------------------------------------------
    # Covering index on pages for Q6 join lookup.
    # In the HTTP VFS model, even 50-row table scans cost 20+ requests.
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_cov_pages
        ON pages(url, category)
    """)
    conn.commit()

    # ---------------------------------------------------------------
    # Set pragmas and rebuild with new page size.
    # journal_mode=DELETE: WAL is incompatible with static HTTP serving.
    # auto_vacuum=NONE: page offsets must remain stable for Range requests.
    # page_size=1024: optimal for 1KiB HTTP Range chunk granularity.
    # ---------------------------------------------------------------
    cur.execute("PRAGMA journal_mode = DELETE")
    cur.execute("PRAGMA auto_vacuum = NONE")
    cur.execute("PRAGMA page_size = 1024")
    cur.execute("VACUUM")
    conn.commit()

    # ---------------------------------------------------------------
    # ANALYZE: collect index statistics so the query planner can
    # accurately estimate costs and prefer partial/covering indexes
    # over non-covering alternatives. Critical for partial indexes.
    # ---------------------------------------------------------------
    cur.execute("ANALYZE")
    conn.commit()

    # ---------------------------------------------------------------
    # FTS5 external-content table on pages(title, category).
    # Created after VACUUM to avoid any virtual table rebuild issues.
    # ---------------------------------------------------------------
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            title, category,
            content=pages, content_rowid=id
        )
    """)
    cur.execute("""
        INSERT INTO pages_fts(rowid, title, category)
        SELECT id, title, category FROM pages
    """)
    conn.commit()

    # ---------------------------------------------------------------
    # Verify all eight queries now show COVERING INDEX
    # ---------------------------------------------------------------
    queries = {
        "Q1": """SELECT country, COUNT(DISTINCT user_id) FROM events
                 WHERE event_type='pageview'
                   AND timestamp BETWEEN 1696200000 AND 1696500000
                 GROUP BY country""",
        "Q2": """SELECT page_url, COUNT(DISTINCT session_id) FROM events
                 WHERE device_type='mobile' AND event_type='pageview'
                 GROUP BY page_url LIMIT 20""",
        "Q3": """SELECT u.plan_type, SUM(e.revenue_cents), COUNT(*)
                 FROM events e JOIN users u ON e.user_id=u.id
                 WHERE e.event_type='purchase' GROUP BY u.plan_type""",
        "Q4": """SELECT device_type, COUNT(*) FROM (
                   SELECT session_id, device_type, COUNT(*) AS pv_count
                   FROM events WHERE event_type='pageview'
                   GROUP BY session_id
                 ) GROUP BY device_type""",
        "Q5": """SELECT e1.referrer, COUNT(DISTINCT e1.session_id),
                        COUNT(DISTINCT e2.session_id)
                 FROM events e1
                 LEFT JOIN events e2
                   ON e1.session_id=e2.session_id AND e2.event_type='purchase'
                 WHERE e1.event_type='pageview' AND e1.referrer IS NOT NULL
                 GROUP BY e1.referrer""",
        "Q6": """SELECT p.category, COUNT(*), AVG(e.duration_ms),
                        COUNT(DISTINCT e.user_id)
                 FROM events e JOIN pages p ON e.page_url=p.url
                 WHERE e.event_type='pageview' AND e.duration_ms IS NOT NULL
                 GROUP BY p.category""",
        "Q7": """SELECT country, COUNT(*), SUM(revenue_cents),
                        AVG(revenue_cents), MAX(revenue_cents)
                 FROM events
                 WHERE event_type='purchase' AND revenue_cents > 10000
                 GROUP BY country HAVING COUNT(*) >= 3""",
        "Q8": """SELECT date(timestamp,'unixepoch'), COUNT(*),
                        COUNT(DISTINCT user_id)
                 FROM events
                 WHERE event_type='pageview'
                   AND timestamp >= 1696118400 AND timestamp < 1696723200
                 GROUP BY date(timestamp,'unixepoch')""",
    }

    ok = True
    for label, q in queries.items():
        rows = cur.execute(f"EXPLAIN QUERY PLAN {q}").fetchall()
        plan = "\n".join(r[3] for r in rows)
        if "COVERING INDEX" in plan:
            print(f"  {label}: COVERING INDEX")
        else:
            print(f"  {label}: MISSING COVERING INDEX")
            print(f"    Plan:\n    {plan}")
            ok = False

    # Check index count
    idx_rows = cur.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='events' AND sql IS NOT NULL"
    ).fetchall()
    print(f"\n  Events indexes: {len(idx_rows)} (max 7)")
    for r in idx_rows:
        print(f"    - {r[0]}")

    ps = cur.execute("PRAGMA page_size").fetchone()[0]
    jm = cur.execute("PRAGMA journal_mode").fetchone()[0]
    av = cur.execute("PRAGMA auto_vacuum").fetchone()[0]
    print(f"  page_size: {ps}, journal_mode: {jm}, auto_vacuum: {av}")

    conn.close()

    if not ok:
        print("\nSome queries did not achieve COVERING INDEX access.")
        sys.exit(1)
    else:
        print("\nAll queries optimized successfully.")


if __name__ == "__main__":
    optimize()
