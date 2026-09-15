#!/usr/bin/env python3
"""
Generate benchmark SQLite database and device topology Graphviz DOT files.

"""
import sqlite3
import os

DB_PATH = "/app/devices.db"
DOT_DIR = "/app/devices"

os.makedirs(DOT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript("""
CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    qubits INTEGER NOT NULL,
    dot_file TEXT NOT NULL
);

CREATE TABLE benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    max_swaps INTEGER NOT NULL,
    perm_type TEXT NOT NULL CHECK (perm_type IN ('explicit', 'seeded_random')),
    perm_seed INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

CREATE TABLE explicit_permutations (
    benchmark_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    target INTEGER NOT NULL,
    PRIMARY KEY (benchmark_id, position),
    FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id)
);

CREATE TABLE topology_properties (
    device_id INTEGER NOT NULL,
    property TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (device_id, property),
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
""")


def write_dot(filename, label, n, edges, extra_attrs=""):
    path = os.path.join(DOT_DIR, filename)
    name = filename.replace(".dot", "")
    with open(path, "w") as f:
        f.write("graph %s {\n" % name)
        f.write('  label="%s";\n' % label)
        f.write("  node [shape=circle, fontsize=10];\n")
        if extra_attrs:
            f.write("  %s\n" % extra_attrs)
        for u, v in edges:
            f.write("  %d -- %d;\n" % (u, v))
        f.write("}\n")
    return filename


def add_device(name, desc, n, dot_file, props=None):
    c.execute(
        "INSERT INTO devices (name, description, qubits, dot_file) VALUES (?,?,?,?)",
        (name, desc, n, dot_file),
    )
    dev_id = c.lastrowid
    if props:
        for k, v in props.items():
            c.execute(
                "INSERT INTO topology_properties (device_id, property, value) VALUES (?,?,?)",
                (dev_id, k, str(v)),
            )
    return dev_id


def add_benchmark(dev_id, name, desc, max_swaps, perm=None, perm_type="explicit", perm_seed=None):
    c.execute(
        "INSERT INTO benchmarks (device_id, name, description, max_swaps, perm_type, perm_seed) "
        "VALUES (?,?,?,?,?,?)",
        (dev_id, name, desc, max_swaps, perm_type, perm_seed),
    )
    bid = c.lastrowid
    if perm_type == "explicit" and perm is not None:
        for i, t in enumerate(perm):
            c.execute(
                "INSERT INTO explicit_permutations (benchmark_id, position, target) VALUES (?,?,?)",
                (bid, i, t),
            )
    return bid


# ==== Path topologies ====

dot = write_dot("path6.dot", "6-qubit linear chain", 6,
                [(i, i + 1) for i in range(5)], "rankdir=LR;")
d = add_device("path6", "Linear chain, 6 qubits", 6, dot,
               {"topology_class": "path", "diameter": "5",
                "optimal_formula": "inversions(perm)"})
add_benchmark(d, "path_basic",
              "Linear chain, 6 qubits, moderate permutation",
              9, [3, 5, 1, 0, 4, 2])

dot = write_dot("path8.dot", "8-qubit linear chain", 8,
                [(i, i + 1) for i in range(7)], "rankdir=LR;")
d = add_device("path8", "Linear chain, 8 qubits", 8, dot,
               {"topology_class": "path", "diameter": "7",
                "optimal_formula": "inversions(perm)"})
add_benchmark(d, "path_reversed",
              "Linear chain, 8 qubits, fully reversed",
              28, [7, 6, 5, 4, 3, 2, 1, 0])

dot = write_dot("path5.dot", "5-qubit linear chain", 5,
                [(i, i + 1) for i in range(4)], "rankdir=LR;")
d = add_device("path5", "Linear chain, 5 qubits", 5, dot,
               {"topology_class": "path", "diameter": "4",
                "optimal_formula": "inversions(perm)"})
add_benchmark(d, "path_identity",
              "Linear chain, 5 qubits, identity mapping",
              0, [0, 1, 2, 3, 4])

dot = write_dot("path200.dot", "200-qubit linear chain", 200,
                [(i, i + 1) for i in range(199)], "rankdir=LR;")
d = add_device("path200", "Linear chain, 200 qubits", 200, dot,
               {"topology_class": "path", "diameter": "199",
                "optimal_formula": "inversions(perm)"})
add_benchmark(d, "path_large",
              "Linear chain, 200 qubits, random permutation (seed 42)",
              10122, perm_type="seeded_random", perm_seed=42)


# ==== Complete topologies ====

def complete_edges(n):
    return [(i, j) for i in range(n) for j in range(i + 1, n)]

dot = write_dot("complete8.dot", "8-qubit fully connected", 8,
                complete_edges(8))
d = add_device("complete8", "Fully connected, 8 qubits", 8, dot,
               {"topology_class": "complete",
                "optimal_formula": "n - cycles(perm)"})
add_benchmark(d, "complete_single_cycle",
              "Fully connected, 8 qubits, single cyclic rotation",
              7, [1, 2, 3, 4, 5, 6, 7, 0])

dot = write_dot("complete6.dot", "6-qubit fully connected", 6,
                complete_edges(6))
d = add_device("complete6", "Fully connected, 6 qubits", 6, dot,
               {"topology_class": "complete",
                "optimal_formula": "n - cycles(perm)"})
add_benchmark(d, "complete_transpositions",
              "Fully connected, 6 qubits, three pair swaps",
              3, [1, 0, 3, 2, 5, 4])

dot = write_dot("complete10.dot", "10-qubit fully connected", 10,
                complete_edges(10))
d = add_device("complete10", "Fully connected, 10 qubits", 10, dot,
               {"topology_class": "complete",
                "optimal_formula": "n - cycles(perm)"})
add_benchmark(d, "complete_mixed",
              "Fully connected, 10 qubits, mixed cycle structure",
              7, [3, 5, 9, 7, 8, 1, 2, 0, 6, 4])


# ==== Tree topologies ====

tree7_edges = [(0, 1), (0, 2), (1, 3), (1, 4), (2, 5), (2, 6)]
dot = write_dot("btree7.dot", "7-qubit binary tree (depth 2)", 7,
                tree7_edges)
d = add_device("btree7", "Binary tree, 7 qubits, depth 2", 7, dot,
               {"topology_class": "tree", "tree_type": "binary",
                "depth": "2", "branching_factor": "2"})
add_benchmark(d, "binary_tree",
              "Binary tree, 7 qubits, depth 2",
              8, [6, 4, 5, 1, 3, 0, 2])

star7_edges = [(0, i) for i in range(1, 7)]
dot = write_dot("star7.dot", "7-qubit star (hub=0)", 7,
                star7_edges)
d = add_device("star7", "Star topology, 7 qubits, hub at position 0", 7, dot,
               {"topology_class": "star", "hub_vertex": "0",
                "diameter": "2"})
add_benchmark(d, "star",
              "Star topology, 7 qubits, hub at position 0",
              12, [0, 3, 6, 5, 1, 4, 2])

cat_edges = [(0, 1), (1, 2), (2, 3), (3, 4),
             (0, 5), (1, 6), (2, 7), (3, 8), (4, 9)]
dot = write_dot("caterpillar10.dot", "10-qubit caterpillar tree", 10,
                cat_edges)
d = add_device("caterpillar10", "Caterpillar tree, 10 qubits, spine with pendant leaves", 10, dot,
               {"topology_class": "tree", "tree_type": "caterpillar",
                "spine_length": "5", "pendant_count": "5"})
add_benchmark(d, "caterpillar",
              "Caterpillar tree, 10 qubits, spine with pendant leaves",
              15, [5, 6, 7, 8, 9, 0, 1, 2, 3, 4])


# ==== Cycle ====

ring_edges = [(i, (i + 1) % 8) for i in range(8)]
dot = write_dot("ring8.dot", "8-qubit ring", 8, ring_edges)
d = add_device("ring8", "Ring topology, 8 qubits", 8, dot,
               {"topology_class": "cycle", "diameter": "4"})
add_benchmark(d, "ring",
              "Ring topology, 8 qubits, two disjoint rotations",
              20, [3, 0, 1, 2, 7, 4, 5, 6])


# ==== Grid ====

grid_edges = []
for r in range(3):
    for col in range(3):
        v = r * 3 + col
        if col + 1 < 3:
            grid_edges.append((v, v + 1))
        if r + 1 < 3:
            grid_edges.append((v, v + 3))

dot = write_dot("grid3x3.dot", "3x3 qubit grid", 9, grid_edges)
d = add_device("grid3x3", "3x3 grid, 9 qubits", 9, dot,
               {"topology_class": "grid", "rows": "3", "cols": "3",
                "diameter": "4"})
add_benchmark(d, "grid_3x3",
              "3x3 grid, 9 qubits, reversed permutation",
              36, [8, 7, 6, 5, 4, 3, 2, 1, 0])


# ==== General (random connected) ====

random_edges = [
    (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 8), (0, 12), (0, 15),
    (1, 2), (1, 3), (1, 9), (2, 4), (2, 5), (2, 13), (3, 4), (4, 17),
    (5, 12), (5, 13), (5, 16), (6, 7), (6, 9), (6, 15), (7, 10),
    (8, 10), (8, 11), (8, 15), (9, 13), (10, 14), (10, 16), (10, 18),
    (12, 19), (13, 14), (13, 16), (15, 18), (16, 19), (17, 19),
]
dot = write_dot("random20.dot", "20-qubit random connected graph", 20,
                random_edges)
d = add_device("random20", "Random connected graph, 20 qubits, extra edges", 20, dot,
               {"topology_class": "general", "generation_method": "random_spanning_tree+extras",
                "generation_seed": "123"})
add_benchmark(d, "random_connected",
              "Random connected graph, 20 qubits, extra edges",
              400,
              [5, 14, 0, 3, 8, 6, 9, 18, 4, 7, 19, 2, 10, 12, 17, 1, 11, 13, 16, 15])

conn.commit()
conn.close()

print("Created %s and %d DOT files in %s/" % (DB_PATH, len(os.listdir(DOT_DIR)), DOT_DIR))
