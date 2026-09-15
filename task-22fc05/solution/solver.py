#!/usr/bin/env python3
"""Generate migration plan, VSchema, scatter analysis, and conflict report.

Assumes hybrid_router.py has already been placed in /app/output/.
"""

import json
import os
import sqlite3
import struct
from collections import defaultdict

from Crypto.Cipher import DES

APP_DIR = "/app"
OUTPUT_DIR = os.path.join(APP_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load configs
with open(os.path.join(APP_DIR, "table_config.json")) as f:
    table_config = json.load(f)

# ===================================================================
# Reference hash implementation for conflict analysis
# ===================================================================
_DES_CIPHER = DES.new(b"\x00" * 8, DES.MODE_ECB)


def _vhash(shard_key: int) -> bytes:
    shard_key = shard_key & 0xFFFFFFFFFFFFFFFF
    key_bytes = struct.pack(">Q", shard_key)
    return _DES_CIPHER.encrypt(key_bytes)


def _keyspace_id_to_shard(ksid: bytes) -> int:
    first_byte = ksid[0]
    boundaries = [0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
    for i, boundary in enumerate(boundaries):
        if first_byte < boundary:
            return i
    return 7


# ===================================================================
# 1. Transaction coupling analysis  (connected components via BFS)
# ===================================================================
transactions = []
with open(os.path.join(APP_DIR, "transaction_log.jsonl")) as f:
    for line in f:
        line = line.strip()
        if line:
            transactions.append(json.loads(line))

# Build adjacency list from multi-table transactions
edges = defaultdict(set)
for txn in transactions:
    tables = txn["tables_written"]
    if len(tables) > 1:
        for i in range(len(tables)):
            for j in range(i + 1, len(tables)):
                edges[tables[i]].add(tables[j])
                edges[tables[j]].add(tables[i])

# BFS to find connected components
all_tables = set(table_config.keys())
visited = set()
coupled_groups = []

for table in sorted(all_tables):
    if table in visited:
        continue
    component = []
    queue = [table]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        component.append(current)
        for neighbor in sorted(edges.get(current, [])):
            if neighbor not in visited:
                queue.append(neighbor)
    coupled_groups.append(sorted(component))

# Migration order: larger (riskier) groups first
migration_order = sorted(coupled_groups, key=lambda g: -len(g))

migration_plan = {
    "coupled_groups": coupled_groups,
    "migration_order": migration_order,
}

with open(os.path.join(OUTPUT_DIR, "migration_plan.json"), "w") as f:
    json.dump(migration_plan, f, indent=2)

# ===================================================================
# 2. Conflict report
# ===================================================================
legacy_conn = sqlite3.connect(os.path.join(APP_DIR, "legacy_mappings.db"))
legacy_cursor = legacy_conn.cursor()

conflict_report = {"per_table": {}, "overall_conflict_rate": 0.0}
total_conflicts_all = 0
total_records_all = 0

for table_name, config in table_config.items():
    threshold = config["threshold"]
    conflicts = 0
    total = 0

    legacy_cursor.execute(
        "SELECT record_id, shard_number FROM shard_map WHERE table_name = ?",
        (table_name,),
    )
    for record_id, legacy_shard in legacy_cursor.fetchall():
        if record_id <= threshold:
            total += 1
            ksid = _vhash(record_id)
            hash_shard = _keyspace_id_to_shard(ksid)
            if legacy_shard != hash_shard:
                conflicts += 1

    rate = conflicts / total if total > 0 else 0.0
    conflict_report["per_table"][table_name] = {
        "conflicts": conflicts,
        "total": total,
        "conflict_rate": rate,
    }
    total_conflicts_all += conflicts
    total_records_all += total

conflict_report["overall_conflict_rate"] = (
    total_conflicts_all / total_records_all if total_records_all > 0 else 0.0
)
legacy_conn.close()

with open(os.path.join(OUTPUT_DIR, "conflict_report.json"), "w") as f:
    json.dump(conflict_report, f, indent=2)

# ===================================================================
# 3. VSchema generation
# ===================================================================
vschema = {
    "sharded": True,
    "vindexes": {
        "hash_vdx": {
            "type": "hash",
        },
    },
    "tables": {},
}

for tname, tconfig in table_config.items():
    vschema["tables"][tname] = {
        "column_vindexes": [
            {
                "column": tconfig["shard_key"],
                "name": "hash_vdx",
            }
        ],
    }

with open(os.path.join(OUTPUT_DIR, "vschema.json"), "w") as f:
    json.dump(vschema, f, indent=2)

# ===================================================================
# 4. Scatter analysis
# ===================================================================
queries = []
with open(os.path.join(APP_DIR, "query_workload.jsonl")) as f:
    for line in f:
        line = line.strip()
        if line:
            queries.append(json.loads(line))

scatter_analysis = []
for query in queries:
    table = query["table"]
    shard_key = table_config[table]["shard_key"]
    sql = query["sql"]

    # Determine if the shard key column appears after WHERE
    where_idx = sql.upper().find("WHERE")
    if where_idx >= 0:
        where_clause = sql[where_idx:]
        is_scatter = shard_key not in where_clause
    else:
        is_scatter = True

    scatter_analysis.append(
        {
            "query_id": query["query_id"],
            "is_scatter": is_scatter,
        }
    )

with open(os.path.join(OUTPUT_DIR, "scatter_analysis.json"), "w") as f:
    json.dump(scatter_analysis, f, indent=2)

print("Solution outputs written to /app/output/")
