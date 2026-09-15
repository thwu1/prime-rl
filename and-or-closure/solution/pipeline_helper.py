#!/usr/bin/env python3
"""
Pipeline helper: extracts test cases from SQLite binary BLOBs,
feeds them to the compiled solver, and inserts results back into the database.

"""

import sqlite3
import struct
import subprocess
import sys

def main():
    if len(sys.argv) < 3:
        print("Usage: pipeline_helper.py <solver_binary> <database_path>",
              file=sys.stderr)
        sys.exit(1)

    solver_path = sys.argv[1]
    db_path = sys.argv[2]

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Read all test cases
    c.execute("SELECT id, n, values_packed FROM test_cases ORDER BY id")
    cases = c.fetchall()

    if not cases:
        print("No test cases found in database.", file=sys.stderr)
        sys.exit(1)

    # Format input for the solver (T / n / values format)
    lines = [str(len(cases))]
    for test_id, n, blob in cases:
        values = list(struct.unpack(f'<{n}Q', blob))
        lines.append(str(n))
        lines.append(' '.join(map(str, values)))
    input_str = '\n'.join(lines) + '\n'

    # Run the compiled solver
    result = subprocess.run(
        [solver_path],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=300
    )

    if result.returncode != 0:
        print(f"Solver failed with exit code {result.returncode}",
              file=sys.stderr)
        print(result.stderr[:2000], file=sys.stderr)
        sys.exit(1)

    # Parse output
    output_lines = result.stdout.strip().split('\n')
    if len(output_lines) != len(cases):
        print(f"Expected {len(cases)} output lines, got {len(output_lines)}",
              file=sys.stderr)
        sys.exit(1)

    # Clear any previous results and insert new ones
    c.execute("DELETE FROM results")
    for (test_id, _, _), answer_line in zip(cases, output_lines):
        closure_size = int(answer_line.strip())
        c.execute("INSERT INTO results (test_id, closure_size) VALUES (?, ?)",
                  (test_id, closure_size))

    conn.commit()
    conn.close()
    print(f"Inserted {len(cases)} results into {db_path}")

if __name__ == "__main__":
    main()
