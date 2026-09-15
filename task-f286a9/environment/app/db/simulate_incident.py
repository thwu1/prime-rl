#!/usr/bin/env python3
"""
Simulate the post-incident state of the database.

The buggy cleanup task has already executed once. Due to the API parameter
bug (?pending_delete with no value being treated as "no filter"), the
cleanup process received ALL 50 prefixes instead of just the 5 pending
deletion. It then withdrew every one of them and deleted their service
bindings.

This script modifies the database to reflect that post-incident state.
"""

import sqlite3

DB_PATH = '/app/db/features.db'


def simulate():
    conn = sqlite3.connect(DB_PATH)

    # The buggy cleanup withdrew ALL prefixes
    conn.execute("UPDATE prefixes SET advertised = 0")

    # The withdraw endpoint deletes service bindings for each prefix
    conn.execute("DELETE FROM service_bindings")

    conn.commit()

    withdrawn = conn.execute(
        "SELECT COUNT(*) FROM prefixes WHERE advertised = 0"
    ).fetchone()[0]
    bindings = conn.execute(
        "SELECT COUNT(*) FROM service_bindings"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM prefixes WHERE pending_delete = 1"
    ).fetchone()[0]

    print(f"Post-incident state applied:")
    print(f"  All {withdrawn} prefixes withdrawn (only {pending} were pending)")
    print(f"  Service bindings remaining: {bindings}")


if __name__ == '__main__':
    simulate()
