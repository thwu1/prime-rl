#!/usr/bin/env python3
"""Create SQLite database from request_stats CSV and run evaluation queries."""

import sqlite3
import csv
import json

conn = sqlite3.connect('/app/analysis.db')
conn.execute('''CREATE TABLE IF NOT EXISTS request_stats (
    request_id TEXT,
    total_prefill_tokens INTEGER,
    total_decode_tokens INTEGER,
    total_cached_blocks INTEGER,
    total_new_blocks INTEGER
)''')

with open('/app/request_stats.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        conn.execute(
            'INSERT INTO request_stats VALUES (?, ?, ?, ?, ?)',
            (row['request_id'].strip(),
             int(row['total_prefill_tokens']),
             int(row['total_decode_tokens']),
             int(row['total_cached_blocks']),
             int(row['total_new_blocks']))
        )
conn.commit()

cur = conn.cursor()

# Highest cache efficiency: request with max cached/(cached+new)
cur.execute("""
    SELECT request_id
    FROM request_stats
    WHERE total_cached_blocks + total_new_blocks > 0
    ORDER BY CAST(total_cached_blocks AS REAL) /
             (total_cached_blocks + total_new_blocks) DESC
    LIMIT 1
""")
highest_eff = cur.fetchone()[0]

# Average decode tokens per request
cur.execute(
    "SELECT ROUND(AVG(CAST(total_decode_tokens AS REAL)), 2) "
    "FROM request_stats"
)
avg_decode = cur.fetchone()[0]

# Total blocks allocated (cached + new)
cur.execute(
    "SELECT SUM(total_cached_blocks + total_new_blocks) FROM request_stats"
)
total_blocks = cur.fetchone()[0]

# Jain's fairness index: (sum(x))^2 / (n * sum(x^2))
cur.execute("""
    SELECT ROUND(
        SUM(CAST(total_decode_tokens AS REAL)) *
        SUM(CAST(total_decode_tokens AS REAL)) /
        (COUNT(*) * SUM(CAST(total_decode_tokens AS REAL) *
                        CAST(total_decode_tokens AS REAL))),
        4
    )
    FROM request_stats
""")
fairness = cur.fetchone()[0]

conn.close()

result = {
    "highest_cache_efficiency_request": highest_eff,
    "avg_decode_tokens": avg_decode,
    "total_blocks_allocated": total_blocks,
    "fairness_index": fairness
}

with open('/app/evaluation.json', 'w') as f:
    json.dump(result, f, indent=2)
