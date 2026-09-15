#!/usr/bin/env python3
"""Create the OSPF topology SQLite database.

Some link costs are intentionally NULL — they must be recovered from
the packet capture (router_logs.pcap) at solve time.
"""
import sqlite3

conn = sqlite3.connect('/app/topology.db')
c = conn.cursor()

c.execute('''CREATE TABLE routers (
    id TEXT PRIMARY KEY,
    loopback TEXT NOT NULL,
    area INTEGER NOT NULL,
    type TEXT NOT NULL,
    areas TEXT
)''')

c.execute('''CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint1 TEXT NOT NULL,
    endpoint2 TEXT NOT NULL,
    cost INTEGER,
    area INTEGER NOT NULL,
    FOREIGN KEY (endpoint1) REFERENCES routers(id),
    FOREIGN KEY (endpoint2) REFERENCES routers(id)
)''')

c.execute('''CREATE TABLE areas (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    default_cost INTEGER
)''')

c.execute('''CREATE TABLE external_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asbr TEXT NOT NULL,
    prefix TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    metric INTEGER NOT NULL,
    FOREIGN KEY (asbr) REFERENCES routers(id)
)''')

routers = [
    ('R1', '10.1.1.1/32', 0, 'internal', None),
    ('R2', '10.2.2.2/32', 0, 'internal', None),
    ('R3', '10.3.3.3/32', 0, 'internal', None),
    ('R4', '10.4.4.4/32', 0, 'ABR', '0,1'),
    ('R5', '10.5.5.5/32', 0, 'ABR', '0,2'),
    ('R6', '10.6.6.6/32', 0, 'ABR', '0,3'),
    ('R7', '10.7.7.7/32', 1, 'internal', None),
    ('R8', '10.8.8.8/32', 1, 'internal', None),
    ('R9', '10.9.9.9/32', 2, 'internal', None),
    ('R10', '10.10.10.10/32', 2, 'ASBR', None),
    ('R11', '10.11.11.11/32', 3, 'internal', None),
    ('R12', '10.12.12.12/32', 3, 'ASBR', None),
]
c.executemany('INSERT INTO routers VALUES (?,?,?,?,?)', routers)

# Links: some costs are NULL (must be recovered from pcap)
links = [
    ('R1', 'R2', 10, 0),
    ('R1', 'R3', None, 0),     # cost=20, only in pcap
    ('R2', 'R3', 5, 0),
    ('R2', 'R4', None, 0),     # cost=8, only in pcap
    ('R3', 'R5', 12, 0),
    ('R1', 'R6', None, 0),     # cost=15, only in pcap
    ('R4', 'R7', 3, 1),
    ('R4', 'R8', None, 1),     # cost=6, only in pcap
    ('R7', 'R8', 2, 1),
    ('R5', 'R9', 7, 2),
    ('R5', 'R10', None, 2),    # cost=14, only in pcap
    ('R9', 'R10', 4, 2),
    ('R6', 'R11', 4, 3),
    ('R6', 'R12', None, 3),    # cost=11, only in pcap
    ('R11', 'R12', 2, 3),
]
c.executemany(
    'INSERT INTO links (endpoint1, endpoint2, cost, area) VALUES (?,?,?,?)',
    links
)

areas = [
    (0, 'backbone', None),
    (1, 'stub', 1),
    (2, 'nssa', 1),
    (3, 'regular', None),
]
c.executemany('INSERT INTO areas VALUES (?,?,?)', areas)

externals = [
    ('R10', '172.16.0.0/16', 'E2', 20),
    ('R10', '172.17.0.0/16', 'E1', 30),
    ('R12', '192.168.0.0/16', 'E2', 15),
    ('R12', '192.168.1.0/24', 'E1', 25),
]
c.executemany(
    'INSERT INTO external_routes (asbr, prefix, metric_type, metric) VALUES (?,?,?,?)',
    externals
)

conn.commit()
conn.close()
