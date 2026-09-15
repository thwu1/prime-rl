#!/usr/bin/env python3
"""Generate deterministic multi-format graph dataset for structural analysis task."""
import os
import gzip
import sqlite3
import random

random.seed(42)

edges = set()

def add_clique(nodes):
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            edges.add((min(nodes[i], nodes[j]), max(nodes[i], nodes[j])))

def add_edge(u, v):
    edges.add((min(u, v), max(u, v)))

# K8: nodes 1-8
add_clique(list(range(1, 9)))
# K7: nodes 9-15
add_clique(list(range(9, 16)))
# K6: nodes 16-21
add_clique(list(range(16, 22)))
# K5a: nodes 22-26
add_clique(list(range(22, 27)))
# K4: nodes 27-30
add_clique(list(range(27, 31)))
# Triangle A: nodes 31-33
add_clique([31, 32, 33])
# Triangle B: nodes 34-36
add_clique([34, 35, 36])
# K5b: nodes 37-41 (disconnected component)
add_clique(list(range(37, 42)))
# Lone edge: 42-43 (disconnected component)
add_edge(42, 43)
# Bridge edges connecting main chain
for u, v in [(8, 9), (15, 16), (21, 22), (26, 27), (30, 31), (33, 34)]:
    add_edge(u, v)

all_edges = sorted(edges)
assert len(all_edges) == 103, f"Expected 103 edges, got {len(all_edges)}"

# --- Create shuffled label mapping for SQLite indirection ---
node_ids = list(range(1, 44))
labels = [f"sensor_{i:03d}" for i in range(1, 44)]
random.shuffle(labels)
id_to_label = dict(zip(node_ids, labels))

# Assign groups
groups = {}
for n in range(1, 9): groups[n] = 'alpha'
for n in range(9, 16): groups[n] = 'beta'
for n in range(16, 22): groups[n] = 'gamma'
for n in range(22, 27): groups[n] = 'delta'
for n in range(27, 31): groups[n] = 'epsilon'
for n in range(31, 34): groups[n] = 'zeta'
for n in range(34, 37): groups[n] = 'eta'
for n in range(37, 42): groups[n] = 'theta'
for n in range(42, 44): groups[n] = 'iota'

# --- Deterministic edge split across 4 formats ---
random.seed(73)
shuffled_edges = list(all_edges)
random.shuffle(shuffled_edges)

n = len(shuffled_edges)
s1 = int(n * 0.40)   # ~41 edges for SQLite
s2 = int(n * 0.65)   # ~25 edges for Matrix Market
s3 = int(n * 0.85)   # ~21 edges for GraphML

sqlite_edges = shuffled_edges[:s1]
mtx_edges = shuffled_edges[s1:s2]
graphml_edges = shuffled_edges[s2:s3]
gz_edges = shuffled_edges[s3:]

os.makedirs('/opt/graphdata', exist_ok=True)

# ============================================================
# 1. SQLite database — edges stored via TEXT labels, not IDs
# ============================================================
db_path = '/opt/graphdata/network.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE sensors (
    sensor_id INTEGER PRIMARY KEY,
    label TEXT UNIQUE NOT NULL,
    group_name TEXT,
    deploy_date TEXT
)''')

c.execute('''CREATE TABLE connections (
    conn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_label TEXT NOT NULL,
    target_label TEXT NOT NULL,
    signal_strength REAL,
    first_seen TEXT,
    FOREIGN KEY (source_label) REFERENCES sensors(label),
    FOREIGN KEY (target_label) REFERENCES sensors(label)
)''')

c.execute('''CREATE TABLE connection_metadata (
    meta_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conn_id INTEGER,
    property_name TEXT,
    property_value TEXT,
    FOREIGN KEY (conn_id) REFERENCES connections(conn_id)
)''')

c.execute('''CREATE TABLE maintenance_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_label TEXT,
    event_type TEXT,
    event_date TEXT,
    notes TEXT
)''')

# Insert sensors
for nid in node_ids:
    lbl = id_to_label[nid]
    c.execute('INSERT INTO sensors VALUES (?, ?, ?, ?)',
              (nid, lbl, groups[nid],
               f'2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}'))

# Insert edges — some stored with source/target swapped (graph is undirected)
for u, v in sqlite_edges:
    if random.random() < 0.3:
        src, tgt = id_to_label[v], id_to_label[u]
    else:
        src, tgt = id_to_label[u], id_to_label[v]
    c.execute('INSERT INTO connections (source_label, target_label, signal_strength, first_seen) VALUES (?, ?, ?, ?)',
              (src, tgt, round(random.uniform(0.3, 1.0), 3),
               f'2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}'))

# Duplicate entries for first 8 edges (reversed labels, different timestamp)
for u, v in sqlite_edges[:8]:
    c.execute('INSERT INTO connections (source_label, target_label, signal_strength, first_seen) VALUES (?, ?, ?, ?)',
              (id_to_label[v], id_to_label[u], round(random.uniform(0.3, 1.0), 3),
               f'2025-{random.randint(1,6):02d}-{random.randint(1,28):02d}'))

# Metadata (red herring complexity)
for i in range(1, 20):
    c.execute('INSERT INTO connection_metadata (conn_id, property_name, property_value) VALUES (?, ?, ?)',
              (i, 'quality', random.choice(['excellent', 'good', 'fair', 'poor'])))

# Maintenance log (red herring)
for _ in range(25):
    c.execute('INSERT INTO maintenance_log (sensor_label, event_type, event_date, notes) VALUES (?, ?, ?, ?)',
              (random.choice(labels),
               random.choice(['calibration', 'replacement', 'firmware_update', 'inspection']),
               f'2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}',
               random.choice(['Routine', 'Urgent', 'Scheduled', 'Post-incident'])))

conn.commit()
conn.close()

# ============================================================
# 2. Matrix Market coordinate pattern symmetric
# ============================================================
mtx_path = '/opt/graphdata/adjacency_secondary.mtx'
max_id_mtx = max(max(u, v) for u, v in mtx_edges)
with open(mtx_path, 'w') as f:
    f.write('%%MatrixMarket matrix coordinate pattern symmetric\n')
    f.write('% Secondary monitoring system adjacency fragment\n')
    f.write('% Collected from backup sensors\n')
    f.write(f'{max_id_mtx} {max_id_mtx} {len(mtx_edges)}\n')
    for u, v in mtx_edges:
        f.write(f'{max(u, v)} {min(u, v)}\n')

# ============================================================
# 3. GraphML with XML namespace
# ============================================================
graphml_path = '/opt/graphdata/supplement.graphml'
gml_nodes = set()
for u, v in graphml_edges:
    gml_nodes.add(u)
    gml_nodes.add(v)

with open(graphml_path, 'w') as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<graphml xmlns="http://graphml.graphdrawing.org/xmlns"\n')
    f.write('         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n')
    f.write('         xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns">\n')
    f.write('  <key id="w" for="edge" attr.name="weight" attr.type="double"/>\n')
    f.write('  <key id="g" for="node" attr.name="group" attr.type="string"/>\n')
    f.write('  <graph id="supplement" edgedefault="undirected">\n')
    for nd in sorted(gml_nodes):
        f.write(f'    <node id="v{nd}">\n')
        f.write(f'      <data key="g">{groups[nd]}</data>\n')
        f.write(f'    </node>\n')
    for i, (u, v) in enumerate(graphml_edges):
        f.write(f'    <edge id="e{i}" source="v{u}" target="v{v}">\n')
        f.write(f'      <data key="w">1.0</data>\n')
        f.write(f'    </edge>\n')
    f.write('  </graph>\n')
    f.write('</graphml>\n')

# ============================================================
# 4. Gzipped edge list — 0-INDEXED with self-loop noise
# ============================================================
gz_path = '/opt/graphdata/corrections.edges.gz'
with gzip.open(gz_path, 'wt') as f:
    f.write('# Field survey corrections - edge data\n')
    f.write('# Format: source_id destination_id\n')
    f.write('# Note: IDs follow 0-based survey convention\n')
    for u, v in gz_edges:
        f.write(f'{u-1} {v-1}\n')
    # Self-loop noise
    for node in [3, 18, 39]:
        f.write(f'{node-1} {node-1}\n')

# ============================================================
# 5. Misleading README
# ============================================================
with open('/opt/graphdata/README.md', 'w') as f:
    f.write('# Sensor Network Connectivity Study\n\n')
    f.write('All sensor connectivity data is stored in the SQLite database `network.db`.\n\n')
    f.write('## Schema\n')
    f.write('- `sensors`: Sensor registry (sensor_id, label, group_name, deploy_date)\n')
    f.write('- `connections`: Pairwise connectivity records (source_label, target_label, signal_strength)\n')
    f.write('- `connection_metadata`: Additional properties per connection\n')
    f.write('- `maintenance_log`: Service event history\n\n')
    f.write('## Notes\n')
    f.write('- All sensor IDs are 1-indexed integers\n')
    f.write('- Edge data references sensors by their label (text) field\n')
    f.write('- The graph is undirected; each connection appears once\n')

print("Graph data generated successfully across 4 formats")
print(f"  SQLite:       {len(sqlite_edges)} unique edges (+8 duplicates)")
print(f"  MatrixMarket: {len(mtx_edges)} edges")
print(f"  GraphML:      {len(graphml_edges)} edges")
print(f"  Gzipped:      {len(gz_edges)} edges (+3 self-loops)")
print(f"  Total unique: {len(all_edges)} edges, {len(set().union(*[{u,v} for u,v in all_edges]))} nodes")
