"""Generate deterministic test instances in a SQLite database."""

import sqlite3
import random
import os

os.makedirs("/app/data", exist_ok=True)
os.makedirs("/app/output", exist_ok=True)

db_path = "/app/data/treebank.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""CREATE TABLE instances (
    id TEXT PRIMARY KEY,
    n INTEGER NOT NULL
)""")

c.execute("""CREATE TABLE arc_scores (
    instance_id TEXT NOT NULL,
    head_node INTEGER NOT NULL,
    dep_node INTEGER NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (instance_id, head_node, dep_node),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
)""")

c.execute("""CREATE TABLE gold_heads (
    instance_id TEXT NOT NULL,
    node INTEGER NOT NULL,
    head_node INTEGER NOT NULL,
    PRIMARY KEY (instance_id, node),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
)""")


def insert_instance(inst_id, n, scores, gold):
    c.execute("INSERT INTO instances VALUES (?, ?)", (inst_id, n))
    for i in range(n + 1):
        for j in range(1, n + 1):
            if i != j:
                c.execute("INSERT INTO arc_scores VALUES (?, ?, ?, ?)",
                          (inst_id, i, j, scores[i][j]))
    for j in range(1, n + 1):
        c.execute("INSERT INTO gold_heads VALUES (?, ?, ?)",
                  (inst_id, j, gold[j]))


# Instance: small (n=3)
scores_small = [
    [0.0, 1.0, 0.5, 0.2],
    [0.0, 0.0, 0.8, 0.3],
    [0.0, 0.6, 0.0, 0.9],
    [0.0, 0.4, 0.7, 0.0]
]
insert_instance("small", 3, scores_small, [-1, 0, 1, 2])

# Instance: small_alt (n=3, different scores)
scores_small_alt = [
    [0.0, 0.3, 1.1, 0.7],
    [0.0, 0.0, 0.5, 1.2],
    [0.0, 0.9, 0.0, 0.4],
    [0.0, 1.0, 0.2, 0.0]
]
insert_instance("small_alt", 3, scores_small_alt, [-1, 2, 0, 1])

# Instance: medium (n=7)
random.seed(42)
n = 7
scores_med = [[0.0] * (n + 1) for _ in range(n + 1)]
for i in range(n + 1):
    for j in range(1, n + 1):
        if i != j:
            scores_med[i][j] = round(random.gauss(0.5, 0.8), 4)
insert_instance("medium", n, scores_med, [-1, 0, 1, 2, 2, 0, 5, 6])

# Instance: large (n=12)
random.seed(123)
n = 12
scores_large = [[0.0] * (n + 1) for _ in range(n + 1)]
for i in range(n + 1):
    for j in range(1, n + 1):
        if i != j:
            scores_large[i][j] = round(random.gauss(0.0, 1.5), 4)
insert_instance("large", n, scores_large, [-1, 0, 1, 2, 0, 4, 5, 6, 0, 8, 9, 10, 0])

conn.commit()
conn.close()
print(f"Created SQLite database at {db_path}")
