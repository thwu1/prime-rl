#!/usr/bin/env bash
#
# Solution: design covering indexes for 8 queries using index sharing,
# partial indexes, and ANALYZE for planner guidance. Configure pragmas
# for HTTP Range-request serving, build FTS5.

set -euo pipefail
cd /app

echo "=== Before optimization ==="
echo "Indexes on events:"
sqlite3 analytics.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events' AND sql IS NOT NULL;"
echo "Page size: $(sqlite3 analytics.db 'PRAGMA page_size;')"
echo ""

echo "=== Applying optimization ==="
python3 /solution/optimize.py

echo ""
echo "=== Verification ==="
echo "Indexes on events:"
sqlite3 analytics.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events' AND sql IS NOT NULL;"
echo ""
echo "Partial indexes:"
sqlite3 analytics.db "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='events' AND sql LIKE '%WHERE%';"
echo ""
echo "Page size: $(sqlite3 analytics.db 'PRAGMA page_size;')"
echo "Journal mode: $(sqlite3 analytics.db 'PRAGMA journal_mode;')"
echo "Auto vacuum: $(sqlite3 analytics.db 'PRAGMA auto_vacuum;')"
echo ""
echo "FTS5 test:"
sqlite3 analytics.db "SELECT snippet(pages_fts, 0, '[', ']', '...', 10) FROM pages_fts WHERE pages_fts MATCH 'analytics' LIMIT 3;"
echo ""
echo "=== Done ==="
