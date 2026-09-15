#!/usr/bin/env python3
"""
Import enriched NDJSON data into SQLite database.
Reads /app/build/enriched.ndjson and inserts into /app/results.db.
"""

import json
import sqlite3


def main():
    conn = sqlite3.connect("/app/results.db")
    with open("/app/build/enriched.ndjson") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            conn.execute(
                "INSERT INTO loan_results VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    obj["id"],
                    obj["computed_apr"],
                    obj["transaction_type"],
                    obj["tolerance_pct"],
                    obj.get("disclosed_apr"),
                    obj.get("within_tolerance"),
                    obj["term_years"],
                    obj["apor_rate"],
                    obj["rate_spread"],
                    obj["high_cost"],
                ),
            )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
