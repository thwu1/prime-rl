#!/usr/bin/env python3
"""Set up the network operations platform environment."""
import sqlite3
import os
import random

for d in ['/app/logs', '/app/config', '/app/docs']:
    os.makedirs(d, exist_ok=True)

db = sqlite3.connect('/app/netops.db')
db.execute('PRAGMA journal_mode=WAL')
cur = db.cursor()

cur.executescript('''
CREATE TABLE topologies (
    topology_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    node_count INTEGER NOT NULL,
    description TEXT
);

CREATE TABLE links (
    topology_id INTEGER NOT NULL REFERENCES topologies(topology_id),
    src_node INTEGER NOT NULL,
    dst_node INTEGER NOT NULL,
    PRIMARY KEY (topology_id, src_node, dst_node)
);

CREATE TABLE optimization_results (
    topology_id INTEGER PRIMARY KEY REFERENCES topologies(topology_id),
    min_diameter INTEGER NOT NULL,
    remove_src INTEGER NOT NULL,
    remove_dst INTEGER NOT NULL,
    add_src INTEGER NOT NULL,
    add_dst INTEGER NOT NULL,
    original_diameter INTEGER,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pipeline_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO pipeline_state VALUES ('current_stage', 'link_swap_optimization');
INSERT INTO pipeline_state VALUES ('status', 'stalled');
INSERT INTO pipeline_state VALUES ('stall_reason', 'computation_timeout');
INSERT INTO pipeline_state VALUES ('target_scope', 'all_flagged');
''')


def add_topology(tid, name, desc, n, edges):
    cur.execute('INSERT INTO topologies VALUES (?, ?, ?, ?)',
                (tid, name, n, desc))
    cur.executemany('INSERT INTO links VALUES (?, ?, ?)',
                    [(tid, u, v) for u, v in edges])


# T1: Small random tree (N=20, seed=42)
random.seed(42)
n = 20
edges = [(random.randint(1, i - 1), i) for i in range(2, n + 1)]
add_topology(1, 'branch_office_alpha',
             'Branch office alpha spanning tree', n, edges)

# T2: Binary-ish tree (N=5000, seed=100)
random.seed(100)
n = 5000
edges = []
for i in range(2, n + 1):
    p = 1 if i <= 3 else random.randint(max(1, i // 2 - 50), i - 1)
    edges.append((p, i))
add_topology(2, 'datacenter_west',
             'Data center west spanning tree', n, edges)

# T3: Path graph (N=600)
n = 600
edges = [(i, i + 1) for i in range(1, n)]
add_topology(3, 'backbone_east',
             'East coast backbone linear topology', n, edges)

# T4: Large random tree (N=80000, seed=456)
random.seed(456)
n = 80000
edges = []
for i in range(2, n + 1):
    p = random.randint(max(1, i - 5), i - 1) if random.random() < 0.2 \
        else random.randint(1, i - 1)
    edges.append((p, i))
add_topology(4, 'metro_core',
             'Metropolitan core network', n, edges)

# T5: Large caterpillar (N=120000, seed=789)
random.seed(789)
n = 120000
spine = n // 3
edges = [(i, i + 1) for i in range(1, spine)]
node = spine + 1
while node <= n:
    edges.append((random.randint(1, spine), node))
    node += 1
add_topology(5, 'campus_south',
             'Southern campus network', n, edges)

db.commit()
db.close()

# Log files
with open('/app/logs/alerts.log', 'w') as f:
    f.write("""\
[2026-06-10 03:00:01] INFO  monitor: periodic topology health scan initiated
[2026-06-10 03:00:14] WARN  monitor: topology=branch_office_alpha worst_case_hops=12 threshold=8 STATUS=EXCEEDED
[2026-06-10 03:00:15] WARN  monitor: topology=datacenter_west worst_case_hops=53 threshold=30 STATUS=EXCEEDED
[2026-06-10 03:00:16] WARN  monitor: topology=backbone_east worst_case_hops=599 threshold=400 STATUS=EXCEEDED
[2026-06-10 03:00:17] WARN  monitor: topology=metro_core worst_case_hops=34 threshold=25 STATUS=EXCEEDED
[2026-06-10 03:00:18] WARN  monitor: topology=campus_south worst_case_hops=186 threshold=120 STATUS=EXCEEDED
[2026-06-10 03:00:19] INFO  monitor: 5 topologies flagged for remediation
""")

with open('/app/logs/pipeline.log', 'w') as f:
    f.write("""\
[2026-06-10 03:01:00] Pipeline v2.3 starting
[2026-06-10 03:01:00] Config: /app/config/optimizer.conf
[2026-06-10 03:01:00] Database: /app/netops.db
[2026-06-10 03:01:01] Protocol: /app/docs/link_optimization_protocol.md
[2026-06-10 03:01:02] Loading flagged topologies from database...
[2026-06-10 03:01:04] Running remediation for 5 flagged topologies...
[2026-06-10 03:01:05] Output targets: optimization_results table, /app/reports/audit.json, /app/reports/topology_changes.{dot,svg}
[2026-06-10 03:15:00] TIMEOUT after 840s - computation did not complete
[2026-06-10 03:15:01] 0 of 5 results committed to optimization_results table
[2026-06-10 03:15:02] Pipeline stalled at stage link_swap_optimization. Manual intervention required.
[2026-06-10 03:15:03] Pending deliverables: optimization_results rows, audit report, change visualization
""")

# Config
with open('/app/config/optimizer.conf', 'w') as f:
    f.write("""\
[database]
path = /app/netops.db

[pipeline]
current_stage = link_swap_optimization
protocol_doc = /app/docs/link_optimization_protocol.md
log_dir = /app/logs

[targets]
scope = all_flagged

[output]
report_dir = /app/reports
audit_file = audit.json
visualization_dot = topology_changes.dot
visualization_svg = topology_changes.svg
visualization_topology = branch_office_alpha
""")

# Documentation
with open('/app/docs/link_optimization_protocol.md', 'w') as f:
    f.write("""\
# Link Optimization Protocol v2.3

## Purpose

When monitored network topologies exhibit worst-case hop distances (diameter)
that exceed operational thresholds, this protocol defines the remediation.

## Remediation: Single-Link Swap

Each managed topology is a spanning tree (connected acyclic graph with N-1
links for N nodes). The remediation procedure is:

1. Remove exactly one existing link from the topology.
2. Add exactly one new link between any two nodes.
3. The modified topology must remain a valid spanning tree (connected,
   exactly N-1 links, no cycles).
4. Objective: minimize the diameter of the resulting tree. The diameter
   is the maximum shortest-path hop distance between any pair of nodes.

The optimal swap achieves the globally minimum diameter over all possible
single-link swaps.

## Data Model

- Table `topologies`: topology_id, name, node_count, description
- Table `links`: topology_id, src_node, dst_node (undirected, stored once)
- Nodes are numbered 1 to node_count for each topology.

## Deliverables

### 1. Database Results

Insert one row per flagged topology into `optimization_results`:
- topology_id
- min_diameter: minimum achievable diameter after the optimal swap
- remove_src, remove_dst: the existing link to remove
- add_src, add_dst: the new link to add
- original_diameter: the diameter of the topology before any swap

### 2. Audit Report

Generate `/app/reports/audit.json` by querying the completed
`optimization_results` table using `sqlite3` in JSON output mode
(`sqlite3 -json`) and reshaping with `jq`.

Required structure:

    {
      "topologies": [
        {
          "id": <topology_id>,
          "name": "<topology name>",
          "node_count": <N>,
          "original_diameter": <diameter before swap>,
          "optimized_diameter": <minimum achievable diameter>,
          "swap": {
            "remove_src": <src of removed link>,
            "remove_dst": <dst of removed link>,
            "add_src": <src of added link>,
            "add_dst": <dst of added link>
          }
        },
        ...
      ]
    }

The array must be sorted by topology id.

### 3. Change Visualization

Generate a Graphviz DOT file at `/app/reports/topology_changes.dot`
depicting the `branch_office_alpha` topology (topology 1). Show all
original edges plus the newly added link. The removed link must have
attribute `[style=dashed color=red]` and the added link must have
attribute `[style=bold color=green]`. All other edges use default style.

Render to SVG at `/app/reports/topology_changes.svg` using the `dot`
command-line tool.

## Performance

Topologies range from tens to over 100,000 nodes. Efficient algorithms
(sub-quadratic) are required for larger instances.
""")

print("Environment setup complete.")
