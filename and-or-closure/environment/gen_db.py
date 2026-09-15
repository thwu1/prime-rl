#!/usr/bin/env python3
"""Generate the lattice.db SQLite database with AND-OR closure test cases.
Values are stored as packed binary BLOBs (little-endian uint64 arrays)."""
import sqlite3
import struct

def pack_values(values):
    return struct.pack(f'<{len(values)}Q', *values)

def make_chain(k):
    vals = set([0])
    for i in range(k):
        v = 0
        for b in range(i, k):
            v |= 1 << b
        vals.add(v)
    return sorted(vals)

db = sqlite3.connect('/app/lattice.db')
c = db.cursor()

c.execute('''CREATE TABLE test_cases (
    id INTEGER PRIMARY KEY,
    n INTEGER NOT NULL,
    values_packed BLOB NOT NULL
)''')

c.execute('''CREATE TABLE results (
    test_id INTEGER PRIMARY KEY REFERENCES test_cases(id),
    closure_size INTEGER NOT NULL
)''')

cases = [
    [0, 1, 3, 5],
    [0, 1, 2, 3, 4],
    [3, 12],
    [42],
    [2, 3, 7],
    [0, 3, 12, 15],
    [0, 1, 2, 3, 4, 5, 6],
    [6, 10, 14],
    [3, 5, 9, 17, 33],
    [0, 1099511627775],
    [0, 5, 10, 15],
    [1 << i for i in range(20)],
    make_chain(20),
    [1 << i for i in range(25)],
]

for i, vals in enumerate(cases, 1):
    c.execute('INSERT INTO test_cases VALUES (?, ?, ?)',
              (i, len(vals), pack_values(vals)))

db.commit()
db.close()
