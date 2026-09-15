#!/usr/bin/env python3
"""
Store analysis results in a SQLite database.
"""
import sqlite3
import json
import sys
import os


def store_results(db_path, site_dirs):
    conn = sqlite3.connect(db_path)

    for site_dir in site_dirs:
        site_name = os.path.basename(site_dir)
        results_path = os.path.join(site_dir, 'results.json')

        if not os.path.exists(results_path):
            print(f"Warning: {results_path} not found, skipping", file=sys.stderr)
            continue

        with open(results_path) as f:
            results = json.load(f)

        total_settlement = results.get('total_settlement')
        has_consolidation = 'pore_pressures' in results

        conn.execute(
            "INSERT OR REPLACE INTO analysis_results "
            "(total_settlement, site_name, has_consolidation, raw_json) "
            "VALUES (?, ?, ?, ?)",
            (site_name, total_settlement, int(has_consolidation), json.dumps(results))
        )

    conn.commit()
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: store_results.py <db_path> <site_name1> [site_name2] ...",
              file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    site_dirs = [os.path.join('sites', s) for s in sys.argv[2:]]
    store_results(db_path, site_dirs)
