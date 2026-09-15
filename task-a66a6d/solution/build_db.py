#!/usr/bin/env python3
"""Build the SQLite analytical database from manifest.json using jq filters."""
import sqlite3
import subprocess


def run_jq(filter_path):
    """Run a jq filter and return stdout."""
    result = subprocess.run(
        ["jq", "-r", "-f", filter_path, "/app/manifest.json"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


# Run jq filters to extract data
dep_edges_out = run_jq("/app/jq_filters/dep_edges.jq")
node_attrs_out = run_jq("/app/jq_filters/node_attrs.jq")

# Create database
conn = sqlite3.connect("/app/pipeline.db")

conn.executescript("""
    DROP TABLE IF EXISTS tags;
    DROP TABLE IF EXISTS edges;
    DROP TABLE IF EXISTS nodes;
    DROP VIEW IF EXISTS v_bottlenecks;
    DROP VIEW IF EXISTS v_test_coverage;

    CREATE TABLE nodes (
        id TEXT PRIMARY KEY,
        resource_type TEXT NOT NULL,
        name TEXT NOT NULL,
        execution_time INTEGER NOT NULL
    );

    CREATE TABLE edges (
        child_id TEXT NOT NULL,
        parent_id TEXT NOT NULL,
        PRIMARY KEY (child_id, parent_id)
    );

    CREATE TABLE tags (
        node_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (node_id, tag)
    );
""")

# Load nodes and tags from node_attrs jq output
for line in node_attrs_out.split("\n"):
    if not line:
        continue
    parts = line.split("\t")
    uid, rtype, name, exec_time = parts[0], parts[1], parts[2], int(parts[3])
    conn.execute("INSERT INTO nodes VALUES (?, ?, ?, ?)",
                 (uid, rtype, name, exec_time))
    if len(parts) > 4 and parts[4]:
        for tag in parts[4].split(","):
            tag = tag.strip()
            if tag:
                conn.execute("INSERT OR IGNORE INTO tags VALUES (?, ?)",
                             (uid, tag))

# Load edges from dep_edges jq output
for line in dep_edges_out.split("\n"):
    if not line:
        continue
    child_id, parent_id = line.split("\t")
    conn.execute("INSERT INTO edges VALUES (?, ?)", (child_id, parent_id))

# Create analytical views
conn.executescript("""
    CREATE VIEW v_bottlenecks AS
    SELECT n.id, n.resource_type, n.execution_time,
           (SELECT COUNT(*) FROM edges e WHERE e.parent_id = n.id) AS fanout,
           n.execution_time * (SELECT COUNT(*) FROM edges e
                               WHERE e.parent_id = n.id) AS risk_score
    FROM nodes n
    ORDER BY risk_score DESC, n.id ASC;

    CREATE VIEW v_test_coverage AS
    SELECT n.id, n.name, n.resource_type,
           (SELECT COUNT(*) FROM edges e
            JOIN nodes t ON t.id = e.child_id
            WHERE e.parent_id = n.id
              AND t.resource_type = 'test') AS test_count
    FROM nodes n
    WHERE n.resource_type IN ('model', 'seed')
    ORDER BY test_count ASC, n.id ASC;
""")

conn.commit()
conn.close()
print("Database built at /app/pipeline.db")
