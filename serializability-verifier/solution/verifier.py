#!/usr/bin/env python3
"""
Oracle verifier for transaction consistency audit.
Connects to PostgreSQL, analyzes transaction history, detects consistency anomalies.
"""

import json
import sys
import psycopg2
from collections import defaultdict

sys.setrecursionlimit(10000)


def main():
    conn = psycopg2.connect(dbname="txstore", user="auditor")
    conn.set_session(autocommit=True)
    cur = conn.cursor()

    # === Diagnostic: verify data integrity ===
    cur.execute("SELECT COUNT(*) FROM operations")
    ops_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tx_outcomes")
    outcomes_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT tx_id) FROM operations")
    total_tx_count = cur.fetchone()[0]

    print(f"[diag] Operations: {ops_count}")
    print(f"[diag] TX outcomes: {outcomes_count}")
    print(f"[diag] Distinct TXs: {total_tx_count}")

    if outcomes_count == 0:
        print("FATAL: tx_outcomes table is empty!", file=sys.stderr)
        # Fallback: derive outcomes from operations table
        print("Attempting fallback: deriving outcomes from operations...",
              file=sys.stderr)
        cur.execute("""
            INSERT INTO tx_outcomes (tx_id, shard_id, outcome, hlc_physical, hlc_logical)
            SELECT tx_id, shard_id,
                   CASE op_type WHEN 'COMMIT' THEN 'committed'
                                WHEN 'ABORT' THEN 'aborted' END,
                   hlc_physical, hlc_logical
            FROM operations
            WHERE op_type IN ('COMMIT', 'ABORT')
        """)
        cur.execute("SELECT COUNT(*) FROM tx_outcomes")
        outcomes_count = cur.fetchone()[0]
        print(f"[diag] Recovered {outcomes_count} outcomes from operations",
              file=sys.stderr)

    # Direct SQL check for mixed-outcome transactions
    cur.execute("""
        SELECT tx_id, array_agg(outcome ORDER BY shard_id),
               array_agg(shard_id ORDER BY shard_id)
        FROM tx_outcomes
        GROUP BY tx_id
        HAVING COUNT(DISTINCT outcome) > 1
    """)
    mixed_rows = cur.fetchall()
    print(f"[diag] Mixed-outcome TXs (SQL): {len(mixed_rows)}")
    for row in mixed_rows:
        print(f"[diag]   {row[0]}: outcomes={row[1]}, shards={row[2]}")

    # Check aborted transactions
    cur.execute(
        "SELECT DISTINCT tx_id FROM tx_outcomes WHERE outcome = 'aborted'"
    )
    aborted_txs = {row[0] for row in cur.fetchall()}
    print(f"[diag] Aborted TXs: {len(aborted_txs)} -> {sorted(aborted_txs)}")

    # === Build transaction status map from tx_outcomes ===
    tx_status = {}
    tx_shard_status = defaultdict(dict)
    tx_commit_ts = {}

    cur.execute(
        "SELECT tx_id, shard_id, outcome, hlc_physical, hlc_logical "
        "FROM tx_outcomes"
    )
    for tx_id, shard_id, outcome, phys, log in cur.fetchall():
        tx_shard_status[tx_id][shard_id] = outcome

    for tx_id, shard_map in tx_shard_status.items():
        outcomes = set(shard_map.values())
        if outcomes == {"committed"}:
            tx_status[tx_id] = "committed"
        elif outcomes == {"aborted"}:
            tx_status[tx_id] = "aborted"
        elif "committed" in outcomes and "aborted" in outcomes:
            tx_status[tx_id] = "mixed"
        else:
            tx_status[tx_id] = "unknown"

    # Get commit timestamps
    cur.execute("""
        SELECT tx_id, MAX(hlc_physical), MAX(hlc_logical)
        FROM tx_outcomes
        WHERE outcome = 'committed'
        GROUP BY tx_id
    """)
    for tx_id, phys, log in cur.fetchall():
        tx_commit_ts[tx_id] = (phys, log)

    status_counts = defaultdict(int)
    for s in tx_status.values():
        status_counts[s] += 1
    print(f"[diag] Status distribution: {dict(status_counts)}")

    # === Load reads and writes ===
    tx_reads = defaultdict(list)
    tx_writes = defaultdict(list)
    tx_shards = defaultdict(set)

    cur.execute("""
        SELECT tx_id, shard_id, op_type, target_key, op_value
        FROM operations
        WHERE op_type IN ('R', 'W') AND target_key IS NOT NULL
        ORDER BY hlc_physical, hlc_logical, seq_num
    """)
    for tx_id, shard_id, op_type, key, value in cur.fetchall():
        tx_shards[tx_id].add(shard_id)
        if op_type == "R":
            tx_reads[tx_id].append((key, value))
        elif op_type == "W":
            tx_writes[tx_id].append((key, value, shard_id))

    # Get all shards per transaction (including non-R/W ops)
    cur.execute(
        "SELECT tx_id, array_agg(DISTINCT shard_id) FROM operations "
        "GROUP BY tx_id"
    )
    for tx_id, shards in cur.fetchall():
        tx_shards[tx_id] = set(shards)

    conn.close()

    # === Detect anomalies ===
    anomalies = []

    # 1. Atomicity violations
    for tx_id, status in tx_status.items():
        if status == "mixed":
            is_cross = (
                len(tx_shards.get(tx_id, set())) > 1
                or tx_id.startswith("X_")
            )
            if is_cross:
                anomalies.append({
                    "type": "atomicity_violation",
                    "transactions": [tx_id],
                    "description": (
                        f"Cross-shard transaction {tx_id} has mixed outcomes: "
                        f"{dict(tx_shard_status[tx_id])}"
                    ),
                })

    print(f"[diag] Atomicity violations found: {len(anomalies)}")

    # 2. Dirty reads
    write_map = {}
    for tx_id, writes in tx_writes.items():
        for key, value, shard in writes:
            write_map[(key, value)] = tx_id

    dirty_count = 0
    for tx_id, reads in tx_reads.items():
        if tx_status.get(tx_id) != "committed":
            continue
        for key, value in reads:
            writer = write_map.get((key, value))
            if (writer and writer != tx_id
                    and tx_status.get(writer) in ("aborted", "mixed")):
                anomalies.append({
                    "type": "dirty_read",
                    "transactions": [writer, tx_id],
                    "description": (
                        f"Committed TX {tx_id} read value '{value}' for "
                        f"key '{key}' written by aborted TX {writer}"
                    ),
                })
                dirty_count += 1

    print(f"[diag] Dirty reads found: {dirty_count}")

    # 3. Non-repeatable reads
    nr_count = 0
    for tx_id, reads in tx_reads.items():
        if tx_status.get(tx_id) != "committed":
            continue
        key_vals = defaultdict(list)
        for key, value in reads:
            key_vals[key].append(value)
        for key, values in key_vals.items():
            if len(set(values)) > 1:
                anomalies.append({
                    "type": "non_repeatable_read",
                    "transactions": [tx_id],
                    "description": (
                        f"TX {tx_id} read key '{key}' with different "
                        f"values: {list(set(values))}"
                    ),
                })
                nr_count += 1

    print(f"[diag] Non-repeatable reads found: {nr_count}")

    # 4. Serialization graph analysis
    committed_txs = {
        tx_id for tx_id, s in tx_status.items() if s == "committed"
    }

    key_versions = defaultdict(list)
    for tx_id in committed_txs:
        cts = tx_commit_ts.get(tx_id)
        if not cts:
            continue
        for key, value, shard in tx_writes.get(tx_id, []):
            key_versions[key].append((tx_id, value, cts))

    for key in key_versions:
        key_versions[key].sort(key=lambda x: x[2])

    read_idx = defaultdict(set)
    for tx_id in committed_txs:
        for key, value in tx_reads.get(tx_id, []):
            read_idx[(key, value)].add(tx_id)

    graph = defaultdict(set)
    edge_types = defaultdict(set)

    def add_edge(frm, to, etype):
        if frm != to and frm in committed_txs and to in committed_txs:
            graph[frm].add(to)
            edge_types[(frm, to)].add(etype)

    for key, versions in key_versions.items():
        written_vals = {v for _, v, _ in versions}

        for i in range(len(versions) - 1):
            add_edge(versions[i][0], versions[i + 1][0], "WW")

        for tx_id, value, _ in versions:
            for reader in read_idx.get((key, value), set()):
                add_edge(tx_id, reader, "WR")

        for i in range(len(versions) - 1):
            curr_val = versions[i][1]
            next_writer = versions[i + 1][0]
            for reader in read_idx.get((key, curr_val), set()):
                add_edge(reader, next_writer, "RW")

        for (rkey, rval), readers in read_idx.items():
            if rkey == key and rval not in written_vals and versions:
                for reader in readers:
                    add_edge(reader, versions[0][0], "RW")

    sccs = tarjan_scc(graph)
    print(f"[diag] SCCs with >1 node: {len(sccs)}")

    already_reported = set()
    for a in anomalies:
        already_reported.update(a.get("transactions", []))

    for scc in sccs:
        scc_set = set(scc)
        if scc_set.issubset(already_reported):
            continue

        cycle_type = classify_cycle(scc, edge_types, tx_reads, tx_writes)
        anomalies.append({
            "type": cycle_type,
            "transactions": sorted(scc),
            "description": (
                f"Serialization graph cycle among {sorted(scc)} "
                f"(classified as {cycle_type})"
            ),
        })

    cross_shard = sum(
        1 for tx_id in tx_shards
        if len(tx_shards[tx_id]) > 1 or tx_id.startswith("X_")
    )

    write_results(anomalies, total_tx_count, cross_shard)

    print(f"Verification complete: {len(anomalies)} anomalies found")
    print(f"Total transactions: {total_tx_count}, Cross-shard: {cross_shard}")
    for a in anomalies:
        print(f"  [{a['type']}] {a['transactions']}")


def write_results(anomalies, total_tx, cross_shard):
    results = {
        "anomalies": anomalies,
        "total_transactions": total_tx,
        "cross_shard_transactions": cross_shard,
        "anomaly_count": len(anomalies),
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


def tarjan_scc(graph):
    """Tarjan's algorithm - returns list of SCCs with >1 node."""
    idx = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = idx[0]
        lowlink[v] = idx[0]
        idx[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                result.append(sorted(scc))

    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    for v in sorted(all_nodes):
        if v not in index:
            strongconnect(v)

    return result


def classify_cycle(scc, edge_types, tx_reads, tx_writes):
    """Classify a serialization graph cycle type."""
    scc_set = set(scc)

    all_etypes = set()
    for a in scc:
        for b in scc:
            if a != b and (a, b) in edge_types:
                all_etypes.update(edge_types[(a, b)])

    write_keys = defaultdict(set)
    read_keys = defaultdict(set)
    for tid in scc_set:
        for k, v, s in tx_writes.get(tid, []):
            write_keys[k].add(tid)
        for k, v in tx_reads.get(tid, []):
            read_keys[k].add(tid)

    for k in write_keys:
        writers_in_scc = write_keys[k] & scc_set
        readers_in_scc = read_keys.get(k, set()) & scc_set
        if len(writers_in_scc) >= 2 and writers_in_scc.issubset(readers_in_scc):
            return "lost_update"

    if len(scc_set) == 2 and all_etypes <= {"RW", "WR"}:
        tx_wkeys = {}
        for tid in scc_set:
            tx_wkeys[tid] = {k for k, v, s in tx_writes.get(tid, [])}

        keys_list = list(tx_wkeys.values())
        if (len(keys_list) == 2
                and all(len(ks) > 0 for ks in keys_list)
                and not (keys_list[0] & keys_list[1])):
            return "write_skew"

    return "serializability_cycle"


if __name__ == "__main__":
    main()
