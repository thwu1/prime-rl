#!/usr/bin/env python3

"""Build the DuckDB-based batch reference oracle at /app/oracle/."""

import os
import subprocess

os.makedirs('/app/oracle', exist_ok=True)

# --- Write oracle computation script ---
ORACLE_PY = r'''#!/usr/bin/env python3
"""Batch reference oracle using DuckDB for SQL aggregation."""

import sys
import json
import duckdb


def simulate_watermark_acceptance(txns, delay):
    """Replay watermark acceptance logic matching the fixed pipeline."""
    max_et = None
    watermark = None
    accepted = []
    rejected = 0
    for txn in txns:
        et = txn['ts']
        if watermark is not None and et < watermark:
            rejected += 1
            continue
        accepted.append(txn)
        if max_et is None or et > max_et:
            max_et = et
            new_wm = max_et - delay
            if watermark is None or new_wm > watermark:
                watermark = new_wm
    return accepted, rejected


def main():
    delay = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    txns = []
    with open('/app/data/transactions.jsonl') as f:
        for line in f:
            txns.append(json.loads(line))

    accepted, rejected_count = simulate_watermark_acceptance(txns, delay)

    # Use DuckDB for batch SQL aggregation
    con = duckdb.connect(':memory:')
    con.execute("""
        CREATE TABLE accepted_txns (
            from_account INTEGER,
            to_account INTEGER,
            amount INTEGER
        )
    """)
    con.executemany(
        "INSERT INTO accepted_txns VALUES (?, ?, ?)",
        [(t['from_account'], t['to_account'], t['amount']) for t in accepted]
    )

    credits = {}
    for row in con.execute(
        "SELECT to_account, SUM(amount) FROM accepted_txns GROUP BY to_account"
    ).fetchall():
        credits[row[0]] = int(row[1])

    debits = {}
    for row in con.execute(
        "SELECT from_account, SUM(amount) FROM accepted_txns GROUP BY from_account"
    ).fetchall():
        debits[row[0]] = int(row[1])

    # Compute balance via DuckDB FULL OUTER JOIN
    balance_rows = con.execute("""
        WITH cred AS (
            SELECT to_account AS account, SUM(amount) AS credits
            FROM accepted_txns GROUP BY to_account
        ),
        deb AS (
            SELECT from_account AS account, SUM(amount) AS debits
            FROM accepted_txns GROUP BY from_account
        )
        SELECT
            COALESCE(c.account, d.account) AS account,
            COALESCE(c.credits, 0) - COALESCE(d.debits, 0) AS balance
        FROM cred c
        FULL OUTER JOIN deb d ON c.account = d.account
    """).fetchall()

    balance = {int(row[0]): int(row[1]) for row in balance_rows}
    total = sum(balance.values())

    result = {
        'watermark_delay': delay,
        'accepted_count': len(accepted),
        'rejected_count': rejected_count,
        'credits': credits,
        'debits': debits,
        'balance': balance,
        'total': total,
    }

    with open('/app/oracle/batch_results.json', 'w') as f:
        json.dump(result, f, indent=2)

    con.close()
    print(f"Oracle: delay={delay} accepted={len(accepted)} rejected={rejected_count} total={total}")


if __name__ == '__main__':
    main()
'''

with open('/app/oracle/oracle_compute.py', 'w') as f:
    f.write(ORACLE_PY)

# --- Write shell entry point ---
COMPUTE_SH = '#!/usr/bin/env bash\n'
COMPUTE_SH += '# DuckDB batch reference oracle\n'
COMPUTE_SH += '# Usage: compute.sh <watermark_delay>\n'
COMPUTE_SH += 'DELAY="${1:-5}"\n'
COMPUTE_SH += 'python3 /app/oracle/oracle_compute.py "$DELAY"\n'

with open('/app/oracle/compute.sh', 'w') as f:
    f.write(COMPUTE_SH)
os.chmod('/app/oracle/compute.sh', 0o755)

# Verify oracle works
result = subprocess.run(
    ['bash', '/app/oracle/compute.sh', '5'],
    capture_output=True, text=True, cwd='/app'
)
print(result.stdout)
if result.returncode != 0:
    print(f"Oracle build error: {result.stderr}")
    raise SystemExit(1)

print("Oracle built successfully.")
