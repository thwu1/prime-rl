#!/usr/bin/env python3
"""
Insert calibration results into SQLite and generate a tab-separated report.

"""
import json
import sqlite3


def main():
    with open('/app/results.json') as f:
        results = json.load(f)

    conn = sqlite3.connect('/app/calibration.db')
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS results (
        method TEXT,
        metric_name TEXT,
        value REAL,
        PRIMARY KEY (method, metric_name)
    )''')

    for method, metrics in results.items():
        for key, val in metrics.items():
            if isinstance(val, (int, float)):
                cur.execute(
                    'INSERT OR REPLACE INTO results (method, metric, value) '
                    'VALUES (?, ?, ?)',
                    (method, key, float(val))
                )

    conn.commit()

    cur.execute('SELECT method, metric_name, value FROM results '
                'ORDER BY method, metric_name')
    rows = cur.fetchall()

    with open('/app/report.txt', 'w') as f:
        f.write("method\tmetric\tvalue\n")
        for row in rows:
            f.write(f"{row[0]}\t{row[1]}\t{row[2]:.8f}\n")

    conn.close()
    print(f"Report: {len(rows)} rows written to /app/report.txt")


if __name__ == '__main__':
    main()
