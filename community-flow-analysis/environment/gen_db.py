#!/usr/bin/env python3
"""Generate network.db: backbone topology with data quality issues and auxiliary tables."""
import sqlite3
import os
import random

os.makedirs('/app', exist_ok=True)
db = sqlite3.connect('/app/network.db')
c = db.cursor()

c.execute('''CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL
)''')

c.execute('''CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_a INTEGER NOT NULL,
    node_b INTEGER NOT NULL,
    capacity INTEGER NOT NULL,
    cost REAL NOT NULL,
    status TEXT NOT NULL
)''')

c.execute('''CREATE TABLE traffic_demands (
    id INTEGER PRIMARY KEY,
    source INTEGER NOT NULL,
    destination INTEGER NOT NULL,
    bandwidth REAL NOT NULL,
    priority TEXT NOT NULL
)''')

c.execute('''CREATE TABLE node_metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL
)''')

c.execute('''CREATE TABLE maintenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    performed_at TEXT NOT NULL,
    engineer TEXT NOT NULL
)''')

# Active nodes 1-31
regions = ['us-east', 'us-west', 'eu-west', 'ap-south', 'ap-east']
for i in range(1, 32):
    cidx = min((i - 1) // 6, 4)
    region = regions[cidx]
    ntype = 'core-router' if (i - 1) % 6 < 3 else 'edge-router'
    c.execute('INSERT INTO nodes VALUES (?,?,?,?,?)',
              (i, f'bb-{region[:4]}-{i:03d}', ntype, region, 'active'))

# Decommissioned nodes
c.execute('INSERT INTO nodes VALUES (?,?,?,?,?)',
          (32, 'bb-usea-032', 'core-router', 'us-east', 'decommissioned'))
c.execute('INSERT INTO nodes VALUES (?,?,?,?,?)',
          (33, 'bb-uswe-033', 'edge-router', 'us-west', 'decommissioned'))

# Intra-community K6 complete subgraphs, weight=10
communities = [
    list(range(1, 7)),
    list(range(7, 13)),
    list(range(13, 19)),
    list(range(19, 25)),
    list(range(25, 31)),
]
for comm in communities:
    for i in range(len(comm)):
        for j in range(i + 1, len(comm)):
            c.execute(
                'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
                (comm[i], comm[j], 10, 1.0, 'up'))

# Inter-community edges
for na, nb, cap, cost in [
    (6, 7, 5, 2.5), (5, 8, 3, 3.0),       # C0-C1
    (12, 13, 4, 2.0), (11, 14, 3, 2.5),    # C1-C2
    (18, 19, 6, 1.5), (17, 20, 2, 3.0),    # C2-C3
    (24, 25, 4, 2.0), (23, 26, 2, 2.5),    # C3-C4
    (3, 28, 2, 4.0),                         # C0-C4 shortcut
    (9, 22, 1, 5.0),                         # C1-C3 shortcut
]:
    c.execute(
        'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
        (na, nb, cap, cost, 'up'))

# Pendant edge (creates a bridge)
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (30, 31, 2, 1.0, 'up'))

# --- DATA QUALITY ISSUES ---
# Self-loops
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (10, 10, 5, 1.0, 'up'))
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (21, 21, 3, 1.0, 'up'))
# Zero-capacity link
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (3, 15, 0, 2.0, 'up'))
# Down link
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (7, 15, 4, 2.0, 'down'))
# Links to decommissioned nodes
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (32, 1, 3, 1.5, 'up'))
c.execute(
    'INSERT INTO links (node_a,node_b,capacity,cost,status) VALUES (?,?,?,?,?)',
    (33, 7, 2, 2.0, 'up'))

# Traffic demands
for d in [
    (1, 1, 29, 5.0, 'critical'),
    (2, 3, 22, 2.0, 'standard'),
    (3, 8, 25, 3.0, 'standard'),
    (4, 15, 30, 1.5, 'low'),
    (5, 2, 31, 0.5, 'low'),
    (6, 7, 19, 4.0, 'standard'),
    (7, 13, 28, 2.5, 'standard'),
]:
    c.execute('INSERT INTO traffic_demands VALUES (?,?,?,?,?)', d)

# Historical metrics (auxiliary context)
random.seed(42)
for nid in range(1, 34):
    for day in range(1, 8):
        c.execute(
            'INSERT INTO node_metrics_history (node_id,metric,value,recorded_at) VALUES (?,?,?,?)',
            (nid, 'cpu_util', round(random.uniform(10, 80), 2),
             f'2025-01-{day:02d}T12:00:00'))
        c.execute(
            'INSERT INTO node_metrics_history (node_id,metric,value,recorded_at) VALUES (?,?,?,?)',
            (nid, 'mem_util', round(random.uniform(20, 90), 2),
             f'2025-01-{day:02d}T12:00:00'))

# Maintenance log
for log in [
    ('node', 32, 'decommission', '2024-11-15T10:00:00', 'jsmith'),
    ('node', 33, 'decommission', '2024-12-01T14:00:00', 'jsmith'),
    ('link', 89, 'status_change', '2025-01-05T08:30:00', 'alee'),
    ('node', 10, 'firmware_update', '2025-01-03T22:00:00', 'bwong'),
    ('link', 45, 'capacity_upgrade', '2024-10-20T16:00:00', 'cpark'),
]:
    c.execute(
        'INSERT INTO maintenance_log (target_type,target_id,action,performed_at,engineer) '
        'VALUES (?,?,?,?,?)', log)

db.commit()
db.close()
