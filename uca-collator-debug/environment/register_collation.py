#!/usr/bin/env python3
"""
Register the UCA collation as a SQLite3 custom collation function,
import a multilingual dataset, and produce sorted output.

Usage:
    python3 register_collation.py
"""

import sqlite3
import sys
import os

sys.path.insert(0, '/app')
from collator import UCACollator


def main():
    collator = UCACollator('/app/data/allkeys.txt', 'NON_IGNORABLE')

    def uca_collation(s1, s2):
        return collator.compare(s1, s2) < 0

    conn = sqlite3.connect(':memory:')
    conn.create_collation('UCA', uca_collation)

    conn.execute('CREATE TABLE texts (line TEXT)')

    with open('/app/data/multilingual_dataset.txt', 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                conn.execute('INSERT INTO texts VALUES (?)', (stripped,))

    os.makedirs('/app/output', exist_ok=True)

    cursor = conn.execute('SELECT line FROM texts ORDER BY line COLLATE UCA')
    with open('/app/output/sorted_multilingual.txt', 'w', encoding='utf-8') as out:
        for row in cursor:
            out.write(row[0] + '\n')

    conn.close()
    print("Sorted output written to /app/output/sorted_multilingual.txt")


if __name__ == '__main__':
    main()
