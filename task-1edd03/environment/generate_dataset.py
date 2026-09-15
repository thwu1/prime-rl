#!/usr/bin/env python3
"""Generate regression forensics dataset with intentional data quality issues.
Deterministic (seed=42). Produces files in /app/."""
import csv
import hashlib
import json
import random
import os

random.seed(42)

FIELDS = [
    'FIX_ID', 'FIX_COMMITS_MERCURIAL', 'FIX_COMMITS_GIT',
    'BUG_IDS', 'BUG_COMMITS_MERCURIAL', 'BUG_COMMITS_GIT',
    'NO_FILE_SHARED', 'NEW_LINES_ONLY_FIX', 'REMOVE_LINES_ONLY_BUG', 'NO_BUG'
]


def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


def hashes(pfx, base, n):
    return " ".join(sha1(f"{pfx}-{base}-{i}") for i in range(n))


clean_rows = []


def add(fix_id, bug_ids, has_fix=True, nfs=False, nlo=False, rlo=False, nb=False):
    if isinstance(bug_ids, int):
        bug_ids = [bug_ids]
    nfc = random.randint(1, 3) if has_fix else 0
    nbc = random.randint(1, 4) if not nb else 0
    clean_rows.append({
        'FIX_ID': str(fix_id),
        'FIX_COMMITS_MERCURIAL': hashes("fm", fix_id, nfc) if has_fix else "",
        'FIX_COMMITS_GIT': hashes("fg", fix_id, nfc) if has_fix else "",
        'BUG_IDS': " ".join(str(b) for b in bug_ids),
        'BUG_COMMITS_MERCURIAL': hashes("bm", bug_ids[0], nbc) if not nb else "",
        'BUG_COMMITS_GIT': hashes("bg", bug_ids[0], nbc) if not nb else "",
        'NO_FILE_SHARED': "" if not has_fix else str(nfs),
        'NEW_LINES_ONLY_FIX': "" if not has_fix else str(nlo),
        'REMOVE_LINES_ONLY_BUG': str(rlo),
        'NO_BUG': str(nb),
    })


# === Chain: 10001 -> 10002 -> ... -> 10013 (12 edges) ===
for i in range(10001, 10013):
    add(i + 1, i)

# === Hub: 10013->10014, then 10014 causes 20 regressions ===
add(10014, 10013)
for i in range(10100, 10120):
    add(i, 10014, nfs=random.random() < 0.15)

# Second-level regressions from hub children
for i in range(10200, 10206):
    add(i, 10100 + (i - 10200))

# === Cycle A: 20001 -> 20002 -> 20003 -> 20001 ===
add(20002, 20001)
add(20003, 20002)
add(20001, 20003)

# === Cycle B: 20004 -> 20005 -> 20006 -> 20007 -> 20004 ===
add(20005, 20004)
add(20006, 20005)
add(20007, 20006)
add(20004, 20007)

# Extensions from cycles
add(20010, 20001)
add(20011, 20010)
add(20012, 20004)
add(20013, 20012)
add(20014, 20013)

# === Multi-regressor rows ===
add(30001, [30101, 30102])
add(30002, [30103, 30104, 30105])
add(30003, 30001)
add(30004, 30002)
add(30005, [30003, 30004])

# === Tree structure ===
add(40002, 40001)
add(40003, 40001)
add(40004, 40001)
add(40005, 40002)
add(40006, 40002)
add(40007, 40003)
add(40008, 40003)
add(40009, 40003)
add(40010, 40005)
add(40011, 40005)

# === Unfixed regressions (empty FIX_COMMITS) ===
uf_pool = list(range(50001, 50021))
for i in range(50101, 50251):
    add(i, random.choice(uf_pool), has_fix=False)

# === NO_FILE_SHARED=True ===
nfs_pool = list(range(60101, 60131))
for i in range(60001, 60081):
    add(i, random.choice(nfs_pool), nfs=True, nlo=random.random() < 0.3)

# === REMOVE_LINES_ONLY_BUG=True ===
rlo_pool = list(range(60251, 60271))
for i in range(60201, 60241):
    add(i, random.choice(rlo_pool), rlo=True)

# === NO_BUG=True ===
nb_pool = list(range(60351, 60371))
for i in range(60301, 60341):
    add(i, random.choice(nb_pool), nb=True)

# === Random dense subgraph ===
pool = list(range(70001, 70501))
for fix in random.sample(pool, 400):
    n = random.choices([1, 2, 3], weights=[0.75, 0.2, 0.05])[0]
    bugs = random.sample([b for b in pool if b != fix], n)
    add(fix, bugs,
        nfs=random.random() < 0.12,
        nlo=random.random() < 0.06,
        rlo=random.random() < 0.03,
        nb=random.random() < 0.02)

# ============================================================
# Inject data quality issues
# ============================================================
all_rows = [dict(r) for r in clean_rows]

# 1. Self-loops: inject FIX_ID into its own BUG_IDS
sl_indices = random.sample(range(len(all_rows)), 12)
for idx in sl_indices:
    row = all_rows[idx]
    fid = row['FIX_ID']
    bugs = row['BUG_IDS'].split()
    if fid not in bugs:
        bugs.append(fid)
        row['BUG_IDS'] = " ".join(bugs)

# 2. Exact duplicate rows
dup_indices = random.sample(range(len(all_rows)), 18)
for idx in dup_indices:
    all_rows.append(dict(all_rows[idx]))

# 3. Some rows triplicated
extra_dup_indices = random.sample(dup_indices[:8], 4)
for idx in extra_dup_indices:
    all_rows.append(dict(all_rows[idx]))

# Shuffle deterministically
random.shuffle(all_rows)

# ============================================================
# Collect all unique bug IDs for metadata generation
# ============================================================
all_bug_ids = set()
for row in all_rows:
    all_bug_ids.add(int(row['FIX_ID']))
    for b in row['BUG_IDS'].split():
        if b.strip():
            all_bug_ids.add(int(b))

# ============================================================
# Generate patch_metadata.jsonl
# ============================================================
components = ["Layout", "JavaScript", "Networking", "DOM", "CSS",
              "Security", "Graphics", "Media"]
bug_id_list = sorted(all_bug_ids)
random.shuffle(bug_id_list)
metadata_bugs = bug_id_list[:int(len(bug_id_list) * 0.65)]
metadata_entries = []
for bid in sorted(metadata_bugs):
    comp = random.choice(components)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    metadata_entries.append({
        "bug_id": bid,
        "patch_count": random.randint(1, 8),
        "first_seen": f"2022-{month:02d}-{day:02d}",
        "component": comp
    })

# ============================================================
# Write files
# ============================================================
os.makedirs('/app', exist_ok=True)

# CSV with quality issues
with open('/app/regression_export.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(all_rows)

# JSONL metadata
with open('/app/patch_metadata.jsonl', 'w') as f:
    for entry in metadata_entries:
        f.write(json.dumps(entry) + '\n')

# Output schema
schema = {
    "_doc": "Schema for /app/results.json. String values describe expected type/format. "
            "Keys prefixed with _ are documentation only — exclude them from output.",
    "data_quality": {
        "total_raw_rows": "int: total data rows in CSV excluding header",
        "unique_rows": "int: rows after removing exact duplicates (all fields identical)",
        "self_loop_edges": "int: among unique rows, count of bug_id entries in the "
                          "space-separated BUG_IDS column that equal the same row's FIX_ID",
        "clean_edge_count": "int: unique directed edges after dedup and self-loop exclusion"
    },
    "graph_topology": {
        "_graph_construction": "From unique rows only: nodes = all unique integers appearing "
                               "in FIX_ID or within BUG_IDS (space-separated). Directed edge: "
                               "each bug_id -> FIX_ID, excluding self-loops, no duplicate edges.",
        "num_nodes": "int",
        "num_edges": "int",
        "num_weakly_connected_components": "int",
        "largest_wcc_size": "int: node count",
        "num_nontrivial_sccs": "int: SCCs with > 1 node",
        "largest_scc_size": "int: 0 if none exist; ties by SCC whose smallest member is smallest",
        "condensation_longest_path": "int: edge count of longest path in SCC-contracted DAG",
        "num_sources": "int: in-degree 0",
        "num_sinks": "int: out-degree 0",
        "max_out_degree": "int",
        "max_out_degree_node": "int: ties by smallest ID",
        "max_in_degree": "int",
        "max_in_degree_node": "int: ties by smallest ID"
    },
    "cascade_analysis": {
        "_forward_reach_def": "forward_reach(v) = count of distinct nodes reachable from v "
                              "following directed edges, excluding v itself.",
        "total_cascade_impact": "int: sum of forward_reach over all nodes",
        "max_forward_reach": "int",
        "top_10_cascade_sources": "list of {bug_id: int, forward_reach: int}; "
                                  "ranked by forward_reach DESC then bug_id ASC"
    },
    "greedy_prevention": {
        "_algorithm": "Repeat: (1) compute forward_reach for every remaining node, "
                      "(2) select node with max forward_reach (ties: smallest ID), "
                      "(3) record its forward_reach, (4) delete the node and all its edges. "
                      "Stop when cumulative recorded reach >= 50% of original "
                      "total_cascade_impact, or when max remaining forward_reach is 0.",
        "prevention_sequence": "list of int: ordered bug_ids removed",
        "steps_required": "int",
        "cumulative_reach_removed": "int",
        "remaining_total_impact": "int: sum of forward_reach in surviving graph"
    },
    "component_risk": {
        "_mapping_rule": "Map each graph node to its 'component' field from the JSONL metadata "
                         "file. Nodes absent from metadata get component 'unknown'. Use "
                         "forward_reach from the ORIGINAL cleaned graph (before greedy removals).",
        "top_5_components": "list of {component: str, total_forward_reach: int, bug_count: int}; "
                            "ranked by total_forward_reach DESC then component name ASC"
    }
}

with open('/app/output_schema.json', 'w') as f:
    json.dump(schema, f, indent=2)

# README
with open('/app/README.txt', 'w') as f:
    f.write("Bug regression dependency data — unprocessed export.\n\n")
    f.write("Files:\n")
    f.write("  regression_export.csv  — regression chain records\n")
    f.write("  patch_metadata.jsonl   — supplementary bug metadata\n")
    f.write("  output_schema.json     — required output specification\n\n")
    f.write("Task: produce /app/results.json as specified in output_schema.json.\n")

print(f"Generated {len(all_rows)} rows in regression_export.csv")
print(f"Generated {len(metadata_entries)} entries in patch_metadata.jsonl")
