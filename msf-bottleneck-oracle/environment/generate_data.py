#!/usr/bin/env python3
"""Generate network topology SQLite database, analysis configuration, and pipeline files."""
import sqlite3
import random
import json
import os

random.seed(152102026)
os.makedirs('/app/network', exist_ok=True)

# ===== NODES =====
SITES = [('alpha', 28, 4), ('beta', 22, 4), ('gamma', 15, 3)]
nodes = []
site_active = {}
nid = 0

for site, n_act, n_dec in SITES:
    site_active[site] = []
    for i in range(n_act):
        nid += 1
        nodes.append((nid, f'{site}-r{i+1:03d}', site, 'active'))
        site_active[site].append(nid)
    for i in range(n_dec):
        nid += 1
        nodes.append((nid, f'{site}-r{n_act+i+1:03d}', site, 'decommissioned'))

active_set = set()
for ids in site_active.values():
    active_set.update(ids)

# ===== EDGES =====
edges = []
eid = [0]
seen = set()


def add(a, b, lt='fiber'):
    if a == b:
        return False
    k = (min(a, b), max(a, b))
    if k in seen:
        return False
    seen.add(k)
    eid[0] += 1
    edges.append((eid[0], a, b, lt))
    return True


# Intra-site: spanning tree + extra edges
for site, ns in site_active.items():
    p = ns[:]
    random.shuffle(p)
    for i in range(1, len(p)):
        add(p[i], p[random.randint(0, i - 1)])
    done = 0
    for _ in range(len(p) * 10):
        if done >= len(p) * 2:
            break
        a, b = random.sample(p, 2)
        before = len(edges)
        add(a, b)
        if len(edges) > before:
            done += 1

# Cross-site: alpha <-> beta (creates one connected component)
added_cross = 0
for _ in range(100):
    if added_cross >= 4:
        break
    a = random.choice(site_active['alpha'])
    b = random.choice(site_active['beta'])
    before = len(edges)
    add(a, b)
    if len(edges) > before:
        added_cross += 1

# Trap: edges involving decommissioned nodes (bypass uniqueness)
decom = [n[0] for n in nodes if n[3] == 'decommissioned']
for _ in range(10):
    eid[0] += 1
    edges.append((eid[0], random.choice(decom), random.choice(list(active_set)), 'copper'))

# Trap: self-loop edges
for _ in range(4):
    eid[0] += 1
    a = random.choice(list(active_set))
    edges.append((eid[0], a, a, 'loopback'))

# ===== IDENTIFY VALID EDGES =====
valid = {e[0] for e in edges if e[1] != e[2] and e[1] in active_set and e[2] in active_set}
no_metric = set(random.sample(list(valid), max(3, len(valid) // 12)))
graph_eids = valid - no_metric

# ===== MEASUREMENTS =====
TS = [
    '2026-01-10T08:00:00',
    '2026-02-14T12:00:00',
    '2026-03-20T16:00:00',
    '2026-04-05T10:00:00',
    '2026-05-12T14:00:00',
]

graph_edge_list = [e for e in edges if e[0] in graph_eids]
weights = random.sample(range(500, 200000), len(graph_edge_list))
assert len(set(weights)) == len(weights), "Weights must be unique"

meas = []
mid = 0

for idx, e in enumerate(graph_edge_list):
    w = weights[idx]
    nm = random.randint(2, 5)
    tss = sorted(random.sample(TS, min(nm, len(TS))))
    for ti, t in enumerate(tss):
        mid += 1
        if ti == len(tss) - 1:
            # Latest measurement produces target weight exactly:
            # weight = latency_us + 100 * loss_permille + jitter_us
            ml = min(12, max(0, (w - 100) // 100))
            lp = random.randint(0, ml) if ml > 0 else 0
            rem = w - 100 * lp
            lat = random.randint(max(1, rem // 4), max(2, 3 * rem // 4))
            jit = rem - lat
            assert jit >= 0 and lat >= 1
            assert lat + 100 * lp + jit == w
        else:
            # Earlier measurements: random noise (different weight)
            lat = random.randint(100, 9000)
            lp = random.randint(0, 15)
            jit = random.randint(10, 800)
        meas.append((mid, e[0], t, lat, lp, jit))

# Noise: measurements for invalid edges (traps)
for e in edges:
    if e[0] not in valid and random.random() < 0.4:
        mid += 1
        meas.append((mid, e[0], '2026-03-20T16:00:00',
                      random.randint(200, 5000), random.randint(0, 10),
                      random.randint(20, 400)))

# ===== QUERIES =====
hname = {n[0]: n[1] for n in nodes}
ab = site_active['alpha'] + site_active['beta']
gm = site_active['gamma']

queries = []
qid = 0

# Within alpha+beta component
for _ in range(35):
    a, b = random.sample(ab, 2)
    qid += 1
    queries.append((qid, hname[a], hname[b]))

# Within gamma component
for _ in range(10):
    a, b = random.sample(gm, 2)
    qid += 1
    queries.append((qid, hname[a], hname[b]))

# Cross-component (should return -1)
for _ in range(5):
    qid += 1
    queries.append((qid, hname[random.choice(ab)], hname[random.choice(gm)]))

# ===== WRITE SQLITE DATABASE =====
conn = sqlite3.connect('/app/network/topology.db')
c = conn.cursor()

c.execute('''CREATE TABLE nodes (
    node_id INTEGER PRIMARY KEY,
    hostname TEXT NOT NULL UNIQUE,
    site TEXT NOT NULL,
    status TEXT NOT NULL
)''')

c.execute('''CREATE TABLE edges (
    edge_id INTEGER PRIMARY KEY,
    src_node INTEGER NOT NULL,
    dst_node INTEGER NOT NULL,
    link_type TEXT NOT NULL
)''')

c.execute('''CREATE TABLE measurements (
    measurement_id INTEGER PRIMARY KEY,
    edge_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    latency_us INTEGER NOT NULL,
    loss_permille INTEGER NOT NULL,
    jitter_us INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE analysis_queries (
    query_id INTEGER PRIMARY KEY,
    src_hostname TEXT NOT NULL,
    dst_hostname TEXT NOT NULL
)''')

c.execute('CREATE INDEX idx_meas_edge ON measurements(edge_id)')
c.execute('CREATE INDEX idx_meas_ts ON measurements(edge_id, collected_at)')

c.executemany('INSERT INTO nodes VALUES(?,?,?,?)', nodes)
c.executemany('INSERT INTO edges VALUES(?,?,?,?)', edges)
c.executemany('INSERT INTO measurements VALUES(?,?,?,?,?,?)', meas)
c.executemany('INSERT INTO analysis_queries VALUES(?,?,?)', queries)

conn.commit()
conn.close()

# ===== WRITE CONFIG =====
config = {
    "description": "Network topology analysis pipeline",
    "data_source": "topology.db",
    "graph_construction": {
        "nodes": "Include only nodes with status = 'active'.",
        "edges": "Exclude self-loops (src_node = dst_node). Exclude edges where either endpoint is not an active node. Exclude edges that have no rows in the measurements table.",
        "weight": "For each qualifying edge, use the measurement with the latest collected_at. Edge weight = latency_us + 100 * loss_permille + jitter_us."
    },
    "analyses": [
        {
            "id": "topology",
            "fields": {
                "active_node_count": "integer: count of active nodes",
                "edge_count": "integer: count of qualifying edges in the graph",
                "num_components": "integer: number of connected components",
                "component_sizes": "list[int]: component sizes sorted ascending"
            }
        },
        {
            "id": "msf",
            "fields": {
                "msf_total_weight": "integer: total edge weight of the minimum spanning forest"
            }
        },
        {
            "id": "bottleneck",
            "description": "For each row in analysis_queries (ordered by query_id), compute the maximum single-edge weight on the unique MSF path between the two named nodes. Return -1 if the nodes are in different components.",
            "fields": {
                "bottleneck_answers": "list[int]: one answer per query"
            }
        },
        {
            "id": "critical",
            "description": "An MSF edge is critical if removing it either disconnects a component (no replacement non-MSF edge exists) or the best replacement edge weight exceeds the removed edge weight by more than the threshold.",
            "threshold": 500,
            "fields": {
                "critical_edges": "list of [hostname_a, hostname_b, weight] triples sorted by weight ascending; hostnames alphabetically ordered within each entry"
            }
        },
        {
            "id": "second_best",
            "fields": {
                "second_best_msf_weight": "integer: total weight of second-best spanning forest obtainable by swapping exactly one MSF edge for one non-MSF edge, or -1 if no swap is possible"
            }
        }
    ],
    "visualization": {
        "output_dot": "/app/pipeline/build/msf.dot",
        "output_svg": "/app/output/msf.svg",
        "site_colors": {
            "alpha": "#4a90d9",
            "beta": "#d94a4a",
            "gamma": "#4ad94a"
        },
        "graph_title": "Network MSF Topology"
    },
    "output_file": "/app/results.json"
}

with open('/app/network/config.json', 'w') as f:
    json.dump(config, f, indent=2)

# ===== WRITE PIPELINE FILES =====
os.makedirs('/app/pipeline/sql', exist_ok=True)
os.makedirs('/app/pipeline/filters', exist_ok=True)
os.makedirs('/app/pipeline/build', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# --- SQL extraction scripts ---
with open('/app/pipeline/sql/extract_nodes.sql', 'w') as f:
    f.write("SELECT node_id, hostname, site, status FROM nodes WHERE status = 'active';\n")

with open('/app/pipeline/sql/extract_edges.sql', 'w') as f:
    f.write("""\
SELECT e.edge_id, e.src_node, e.dst_node,
       m.collected_at, m.latency_us, m.loss_permille, m.jitter_us
FROM edges e
INNER JOIN measurements m ON m.edge_id = e.edge_id
WHERE e.src_node != e.dst_node;
""")

with open('/app/pipeline/sql/extract_queries.sql', 'w') as f:
    f.write("SELECT query_id, src_hostname, dst_hostname FROM analysis_queries ORDER BY query_id;\n")

# --- jq filter for computing edge weights from latest measurements ---
with open('/app/pipeline/filters/compute_weights.jq', 'w') as f:
    f.write("""\
# Group measurements by edge, keep only the latest measurement per edge,
# and compute composite weight = latency_us + 100 * loss_permille + jitter_us
[
  group_by(.edge_id)[]
  | sort_by(.collected_at)
  | last
  | {edge_id, src_node, dst_node, weight: (.latency_us + (100 * .loss_permille) + .jitter_us)}
]
""")

# --- Makefile ---
# NOTE: Makefile requires real tab characters for recipe indentation
makefile = (
    "# Network topology analysis pipeline\n"
    "# Stages: extract -> transform -> analyze -> visualize\n"
    "#\n"
    "# Usage: make all\n"
    "#   Implemented stages: extract, transform\n"
    "#   Unimplemented: analyze (requires /app/pipeline/analyze.py)\n"
    "#                  visualize (requires msf.dot from analyze stage)\n"
    "\n"
    "DB       = /app/network/topology.db\n"
    "CONFIG   = /app/network/config.json\n"
    "BUILD    = /app/pipeline/build\n"
    "OUTPUT   = /app/output\n"
    "SQL      = /app/pipeline/sql\n"
    "FILTERS  = /app/pipeline/filters\n"
    "\n"
    ".PHONY: all clean extract transform\n"
    "\n"
    "all: $(BUILD)/.analyzed $(OUTPUT)/msf.svg\n"
    "\n"
    "$(BUILD):\n"
    "\tmkdir -p $@\n"
    "\n"
    "$(OUTPUT):\n"
    "\tmkdir -p $@\n"
    "\n"
    "# ── Stage 1: Extract ──────────────────────────────────────\n"
    "# Pull raw data from SQLite as JSON using sqlite3 CLI\n"
    "\n"
    "$(BUILD)/nodes.json: $(SQL)/extract_nodes.sql | $(BUILD)\n"
    "\tsqlite3 $(DB) '.mode json' '.read $<' > $@\n"
    "\n"
    "$(BUILD)/raw_edges.json: $(SQL)/extract_edges.sql | $(BUILD)\n"
    "\tsqlite3 $(DB) '.mode json' '.read $<' > $@\n"
    "\n"
    "$(BUILD)/queries.json: $(SQL)/extract_queries.sql | $(BUILD)\n"
    "\tsqlite3 $(DB) '.mode json' '.read $<' > $@\n"
    "\n"
    "extract: $(BUILD)/nodes.json $(BUILD)/raw_edges.json $(BUILD)/queries.json\n"
    "\n"
    "# ── Stage 2: Transform ──────────────────────────────────\n"
    "# Use jq to aggregate measurements and compute edge weights\n"
    "\n"
    "$(BUILD)/weighted_edges.json: $(BUILD)/raw_edges.json $(FILTERS)/compute_weights.jq\n"
    "\tjq -f $(FILTERS)/compute_weights.jq $< > $@\n"
    "\n"
    "transform: $(BUILD)/weighted_edges.json\n"
    "\n"
    "# ── Stage 3: Analyze ────────────────────────────────────\n"
    "# Run graph analysis: MSF, bottleneck paths, critical edges, etc.\n"
    "# Produces /app/results.json and $(BUILD)/msf.dot\n"
    "\n"
    "$(BUILD)/.analyzed: $(BUILD)/weighted_edges.json $(BUILD)/nodes.json $(BUILD)/queries.json $(CONFIG)\n"
    "\tpython3 /app/pipeline/analyze.py\n"
    "\ttouch $@\n"
    "\n"
    "# ── Stage 4: Visualize ──────────────────────────────────\n"
    "# Render MSF graph to SVG using Graphviz dot\n"
    "\n"
    "$(OUTPUT)/msf.svg: $(BUILD)/.analyzed | $(OUTPUT)\n"
    "\tdot -Tsvg $(BUILD)/msf.dot -o $@\n"
    "\n"
    "visualize: $(OUTPUT)/msf.svg\n"
    "\n"
    "# ── Housekeeping ─────────────────────────────────────────\n"
    "clean:\n"
    "\trm -rf $(BUILD) $(OUTPUT) /app/results.json\n"
)

with open('/app/pipeline/Makefile', 'w') as f:
    f.write(makefile)
