#!/usr/bin/env python3
import json
import sqlite3

with open('/tmp/network.json') as f:
    net = json.load(f)

conn = sqlite3.connect('/app/network.db')
c = conn.cursor()

c.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
for k in ('num_nodes', 'source', 'sink'):
    c.execute('INSERT INTO metadata VALUES (?, ?)', (k, net[k]))

c.execute('''CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node INTEGER NOT NULL,
    to_node INTEGER NOT NULL,
    capacity INTEGER NOT NULL,
    cost INTEGER NOT NULL
)''')

for e in net['edges']:
    c.execute(
        'INSERT INTO edges (from_node, to_node, capacity, cost) VALUES (?, ?, ?, ?)',
        (e['from'], e['to'], e['capacity'], e['cost']),
    )

conn.commit()
conn.close()
