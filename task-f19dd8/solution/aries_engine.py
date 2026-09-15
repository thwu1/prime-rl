#!/usr/bin/env python3

"""WAL crash recovery analysis tool — reads from SQLite + binary files."""

import heapq
import json
import os
import sqlite3
import struct
import sys

STATUS_ORDER = {
    "RUNNING": 0,
    "COMMITTING": 1,
    "ABORTING": 1,
    "COMPLETE": 2,
}

NULL_SENTINEL = 0xFFFFFFFF

BINARY_RECORD_TYPES = {
    0x01: "UPDATE",
    0x02: "COMMIT",
    0x03: "ABORT",
    0x04: "CLR",
    0x05: "END",
}


def parse_page_state(path):
    """Parse binary page state file (PGST format, big-endian)."""
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 8:
        return {}
    magic = data[0:4]
    if magic != b"PGST":
        raise ValueError(f"Invalid page state magic: {magic!r}")
    entry_count = struct.unpack(">I", data[4:8])[0]
    result = {}
    offset = 8
    for _ in range(entry_count):
        page_id, flushed_lsn = struct.unpack(">II", data[offset:offset + 8])
        result[page_id] = flushed_lsn
        offset += 8
    return result


def parse_wal_suffix(path):
    """Parse binary WAL suffix file (WAL1 format, big-endian, 24-byte records)."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 8:
        return []
    magic = data[0:4]
    if magic != b"WAL1":
        raise ValueError(f"Invalid WAL suffix magic: {magic!r}")
    record_count = struct.unpack(">I", data[4:8])[0]
    records = []
    offset = 8
    for _ in range(record_count):
        lsn = struct.unpack(">I", data[offset:offset + 4])[0]
        rtype_byte = data[offset + 4]
        # 3 bytes padding at offset+5..offset+7
        txn_id_raw = struct.unpack(">I", data[offset + 8:offset + 12])[0]
        prev_lsn_raw = struct.unpack(">I", data[offset + 12:offset + 16])[0]
        page_id_raw = struct.unpack(">I", data[offset + 16:offset + 20])[0]
        undo_next_raw = struct.unpack(">I", data[offset + 20:offset + 24])[0]

        record = {
            "lsn": lsn,
            "type": BINARY_RECORD_TYPES[rtype_byte],
        }

        # Decode fields, treating NULL_SENTINEL as None
        txn_id = txn_id_raw if txn_id_raw != NULL_SENTINEL else None
        prev_lsn = prev_lsn_raw if prev_lsn_raw != NULL_SENTINEL else None
        page_id = page_id_raw if page_id_raw != NULL_SENTINEL else None
        undo_next = undo_next_raw if undo_next_raw != NULL_SENTINEL else None

        rtype = record["type"]

        # Add fields based on record type (matching SQLite record structure)
        if rtype in ("UPDATE", "CLR", "COMMIT", "ABORT", "END"):
            record["txn_id"] = txn_id
            record["prev_lsn"] = prev_lsn

        if rtype in ("UPDATE", "CLR"):
            record["page_id"] = page_id

        if rtype == "CLR":
            record["undo_next_lsn"] = undo_next

        records.append(record)
        offset += 24

    return records


def load_scenario(db_path):
    """Load crash scenario from a SQLite database + companion binary files."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Master record LSN
    row = conn.execute(
        "SELECT value FROM crash_state WHERE key = 'master_record_lsn'"
    ).fetchone()
    master_lsn = int(row["value"])

    # WAL records from SQLite
    log = []
    for row in conn.execute("SELECT * FROM wal_records ORDER BY lsn"):
        record = {"lsn": row["lsn"], "type": row["record_type"]}
        rtype = row["record_type"]

        # Transaction-bearing records
        if rtype in ("UPDATE", "CLR", "COMMIT", "ABORT", "END"):
            record["txn_id"] = row["txn_id"]
            record["prev_lsn"] = row["prev_lsn"]

        # Page-modifying records
        if rtype in ("UPDATE", "CLR"):
            record["page_id"] = row["page_id"]

        # CLR-specific field
        if rtype == "CLR":
            record["undo_next_lsn"] = row["undo_next_lsn"]

        # Load checkpoint snapshot data
        if rtype == "END_CHECKPOINT":
            txn_table = {}
            for snap in conn.execute(
                "SELECT txn_id, status, last_lsn "
                "FROM checkpoint_txn_snapshot WHERE checkpoint_lsn = ?",
                (row["lsn"],),
            ):
                txn_table[str(snap["txn_id"])] = {
                    "status": snap["status"],
                    "last_lsn": snap["last_lsn"],
                }
            record["txn_table"] = txn_table

            dpt = {}
            for snap in conn.execute(
                "SELECT page_id, rec_lsn "
                "FROM checkpoint_dpt_snapshot WHERE checkpoint_lsn = ?",
                (row["lsn"],),
            ):
                dpt[str(snap["page_id"])] = snap["rec_lsn"]
            record["dirty_page_table"] = dpt

        log.append(record)

    conn.close()

    # Parse and merge binary WAL suffix
    wal_suffix_path = db_path + ".walsuffix"
    suffix_records = parse_wal_suffix(wal_suffix_path)
    if suffix_records:
        log.extend(suffix_records)
        log.sort(key=lambda r: r["lsn"])

    # Parse binary page state
    page_state_path = db_path + ".pgstate"
    flushed = parse_page_state(page_state_path)

    return master_lsn, flushed, log


def analysis(log, master_lsn):
    """Forward scan: reconstruct transaction table and dirty page table."""
    txn_table = {}
    dpt = {}
    ended_txns = set()

    # Find scan start position
    start_idx = 0
    for i, r in enumerate(log):
        if r["lsn"] == master_lsn:
            start_idx = i
            break

    for r in log[start_idx:]:
        rtype = r["type"]

        # Any record with a txn_id: ensure transaction is in the table
        if "txn_id" in r and r["txn_id"] is not None:
            tid = r["txn_id"]
            if tid not in txn_table and tid not in ended_txns:
                txn_table[tid] = {"status": "RUNNING", "last_lsn": r["lsn"]}
            if tid in txn_table:
                txn_table[tid]["last_lsn"] = r["lsn"]

        # Page-modifying records update the DPT
        if rtype in ("UPDATE", "CLR"):
            pid = r["page_id"]
            if pid not in dpt:
                dpt[pid] = r["lsn"]

        # Status transitions
        if rtype == "COMMIT":
            tid = r["txn_id"]
            if tid in txn_table:
                txn_table[tid]["status"] = "COMMITTING"
        elif rtype == "ABORT":
            tid = r["txn_id"]
            if tid in txn_table:
                txn_table[tid]["status"] = "ABORTING"
        elif rtype == "END":
            tid = r["txn_id"]
            if tid in txn_table:
                del txn_table[tid]
            ended_txns.add(tid)

        # Checkpoint merge
        elif rtype == "END_CHECKPOINT":
            # Merge DPT — checkpoint values take precedence for shared pages
            ckpt_dpt = r.get("dirty_page_table", {})
            for pid_str, rec_lsn in ckpt_dpt.items():
                dpt[int(pid_str)] = rec_lsn

            # Merge transaction table
            ckpt_txn = r.get("txn_table", {})
            for tid_str, info in ckpt_txn.items():
                tid = int(tid_str)
                if tid in ended_txns:
                    continue
                if tid not in txn_table:
                    txn_table[tid] = {
                        "status": info["status"],
                        "last_lsn": info["last_lsn"],
                    }
                else:
                    # Keep more advanced status
                    our_order = STATUS_ORDER.get(txn_table[tid]["status"], 0)
                    ckpt_order = STATUS_ORDER.get(info["status"], 0)
                    if ckpt_order > our_order:
                        txn_table[tid]["status"] = info["status"]
                    # Keep higher last_lsn
                    if info["last_lsn"] > txn_table[tid]["last_lsn"]:
                        txn_table[tid]["last_lsn"] = info["last_lsn"]

    return txn_table, dpt


def redo_phase(log, dpt, flushed_page_lsns):
    """Determine which records need replay for durability."""
    if not dpt:
        return []

    min_rec_lsn = min(dpt.values())
    redo_lsns = []

    for r in log:
        if r["lsn"] < min_rec_lsn:
            continue

        rtype = r["type"]
        if rtype not in ("UPDATE", "CLR"):
            continue

        pid = r["page_id"]

        # Page must be in DPT
        if pid not in dpt:
            continue

        # Record LSN must be >= page's recLSN
        if r["lsn"] < dpt[pid]:
            continue

        # On-disk page LSN must be < record LSN
        page_lsn = flushed_page_lsns.get(pid, -1)
        if page_lsn >= r["lsn"]:
            continue

        redo_lsns.append(r["lsn"])

    return redo_lsns


def undo_phase(txn_table, lsn_to_record):
    """Reverse incomplete transactions via max-LSN interleaved processing."""
    # Max-heap by LSN (negate for Python's min-heap)
    heap = []
    for tid, info in txn_table.items():
        if info["status"] == "RECOVERY_ABORTING":
            heapq.heappush(heap, (-info["last_lsn"], tid))

    clrs = []
    ended = []

    while heap:
        neg_lsn, tid = heapq.heappop(heap)
        lsn = -neg_lsn

        record = lsn_to_record.get(lsn)
        if record is None:
            ended.append(tid)
            continue

        rtype = record["type"]

        if rtype == "UPDATE":
            # Undoable: generate a CLR
            undo_next = record.get("prev_lsn")
            clrs.append({
                "undone_lsn": lsn,
                "txn_id": tid,
                "page_id": record["page_id"],
                "undo_next_lsn": undo_next,
            })
            next_lsn = undo_next
        elif rtype == "CLR":
            # Not undoable: follow the CLR's undo_next chain
            next_lsn = record.get("undo_next_lsn")
        else:
            # ABORT or other non-undoable record: follow prev_lsn
            next_lsn = record.get("prev_lsn")

        if next_lsn is None:
            ended.append(tid)
        else:
            heapq.heappush(heap, (-next_lsn, tid))

    return clrs, ended


def recover(db_path):
    """Run full recovery analysis on a crash database."""
    master_lsn, flushed, log = load_scenario(db_path)
    lsn_to_record = {r["lsn"]: r for r in log}

    # --- Analysis ---
    txn_table, dpt = analysis(log, master_lsn)

    # Snapshot analysis results (before post-analysis cleanup)
    analysis_txn = {
        str(tid): {"status": info["status"], "last_lsn": info["last_lsn"]}
        for tid, info in sorted(txn_table.items())
    }
    analysis_dpt = {
        str(pid): rlsn for pid, rlsn in sorted(dpt.items())
    }

    # --- Post-analysis cleanup ---
    to_remove = []
    for tid, info in txn_table.items():
        if info["status"] == "COMMITTING":
            to_remove.append(tid)
        elif info["status"] in ("RUNNING", "ABORTING"):
            info["status"] = "RECOVERY_ABORTING"
    for tid in to_remove:
        del txn_table[tid]

    # --- Redo ---
    redo_lsns = redo_phase(log, dpt, flushed)

    # --- Undo ---
    clrs, ended = undo_phase(txn_table, lsn_to_record)

    return {
        "analysis": {
            "transaction_table": analysis_txn,
            "dirty_page_table": analysis_dpt,
        },
        "redo": redo_lsns,
        "undo": {
            "clrs": clrs,
            "ended_txns": ended,
        },
    }


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: recover <crash.db> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    result = recover(sys.argv[1])

    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
