#!/usr/bin/env python3

"""Tests for the WAL crash recovery tool with multi-source data."""

import json
import os
import sqlite3
import struct
import subprocess
import tempfile

import pytest

SCHEMA_SQL = """
CREATE TABLE wal_records (
    lsn INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL,
    txn_id INTEGER,
    prev_lsn INTEGER,
    page_id INTEGER,
    undo_next_lsn INTEGER
);

CREATE TABLE crash_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE checkpoint_txn_snapshot (
    checkpoint_lsn INTEGER NOT NULL,
    txn_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_lsn INTEGER NOT NULL,
    PRIMARY KEY (checkpoint_lsn, txn_id)
);

CREATE TABLE checkpoint_dpt_snapshot (
    checkpoint_lsn INTEGER NOT NULL,
    page_id INTEGER NOT NULL,
    rec_lsn INTEGER NOT NULL,
    PRIMARY KEY (checkpoint_lsn, page_id)
);
"""

NULL_SENTINEL = 0xFFFFFFFF
RECORD_TYPE_CODES = {
    "UPDATE": 0x01,
    "COMMIT": 0x02,
    "ABORT": 0x03,
    "CLR": 0x04,
    "END": 0x05,
}


def create_page_state_file(path, flushed_page_lsns):
    """Create binary page state file in PGST format (big-endian)."""
    with open(path, "wb") as f:
        f.write(b"PGST")
        f.write(struct.pack(">I", len(flushed_page_lsns)))
        for page_id_str, lsn in flushed_page_lsns.items():
            f.write(struct.pack(">II", int(page_id_str), lsn))


def create_wal_suffix_file(path, records):
    """Create binary WAL suffix file in WAL1 format (big-endian, 24-byte records)."""
    with open(path, "wb") as f:
        f.write(b"WAL1")
        f.write(struct.pack(">I", len(records)))
        for r in records:
            lsn = r["lsn"]
            rtype = RECORD_TYPE_CODES[r["type"]]
            txn_id = r.get("txn_id")
            prev_lsn = r.get("prev_lsn")
            page_id = r.get("page_id")
            undo_next = r.get("undo_next_lsn")

            f.write(struct.pack(">I", lsn))
            f.write(struct.pack("B", rtype))
            f.write(b"\x00\x00\x00")  # 3 bytes padding
            f.write(struct.pack(">I", txn_id if txn_id is not None else NULL_SENTINEL))
            f.write(struct.pack(">I", prev_lsn if prev_lsn is not None else NULL_SENTINEL))
            f.write(struct.pack(">I", page_id if page_id is not None else NULL_SENTINEL))
            f.write(struct.pack(">I", undo_next if undo_next is not None else NULL_SENTINEL))


def create_crash_db(scenario, db_path):
    """Create a SQLite crash database from a scenario dict."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)

    conn.execute(
        "INSERT INTO crash_state VALUES ('master_record_lsn', ?)",
        (str(scenario["master_record_lsn"]),),
    )

    for r in scenario["log"]:
        conn.execute(
            "INSERT INTO wal_records VALUES (?, ?, ?, ?, ?, ?)",
            (
                r["lsn"],
                r["type"],
                r.get("txn_id"),
                r.get("prev_lsn"),
                r.get("page_id"),
                r.get("undo_next_lsn"),
            ),
        )

        if r["type"] == "END_CHECKPOINT":
            for tid_str, info in r.get("txn_table", {}).items():
                conn.execute(
                    "INSERT INTO checkpoint_txn_snapshot VALUES (?, ?, ?, ?)",
                    (r["lsn"], int(tid_str), info["status"], info["last_lsn"]),
                )
            for pid_str, rlsn in r.get("dirty_page_table", {}).items():
                conn.execute(
                    "INSERT INTO checkpoint_dpt_snapshot VALUES (?, ?, ?)",
                    (r["lsn"], int(pid_str), rlsn),
                )

    conn.commit()
    conn.close()


def run_recovery(scenario):
    """Create crash db + binary files, run recovery tool, return parsed output."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db", dir="/tmp")
    os.close(db_fd)
    output_path = db_path.replace(".db", "_out.json")
    pgstate_path = db_path + ".pgstate"
    walsuffix_path = db_path + ".walsuffix"

    try:
        create_crash_db(scenario, db_path)
        create_page_state_file(pgstate_path, scenario.get("flushed_page_lsns", {}))

        wal_suffix = scenario.get("wal_suffix", [])
        if wal_suffix:
            create_wal_suffix_file(walsuffix_path, wal_suffix)

        result = subprocess.run(
            ["/app/recover", db_path, output_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Tool exited with code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert os.path.exists(output_path), "Output file was not created"

        with open(output_path) as f:
            return json.load(f)
    finally:
        for p in (db_path, output_path, pgstate_path, walsuffix_path):
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# Scenario 1: Basic recovery — two transactions, one committed, one active
# All data in SQLite + binary page state (empty). No WAL suffix.
# ---------------------------------------------------------------------------

def test_basic_recovery():
    """Two transactions: T1 commits before crash, T2 is active.
    Empty checkpoint at start. No pages flushed (empty PGST file)."""
    scenario = {
        "master_record_lsn": 0,
        "flushed_page_lsns": {},
        "log": [
            {"lsn": 0, "type": "BEGIN_CHECKPOINT"},
            {"lsn": 1, "type": "END_CHECKPOINT",
             "txn_table": {}, "dirty_page_table": {}},
            {"lsn": 2, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 3, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 2, "page_id": 20},
            {"lsn": 4, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 5, "type": "COMMIT", "txn_id": 1, "prev_lsn": 3},
            {"lsn": 6, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 4, "page_id": 30},
        ],
    }
    result = run_recovery(scenario)

    # --- Analysis ---
    assert result["analysis"]["transaction_table"] == {
        "1": {"status": "COMMITTING", "last_lsn": 5},
        "2": {"status": "RUNNING", "last_lsn": 6},
    }, "Basic: analysis transaction table mismatch"

    assert result["analysis"]["dirty_page_table"] == {
        "10": 2, "20": 3, "30": 6,
    }, "Basic: analysis DPT mismatch"

    # --- Redo (all pages unflushed → redo all updates) ---
    assert result["redo"] == [2, 3, 4, 6], "Basic: redo set mismatch"

    # --- Undo (T2 active → undo LSNs 6, 4) ---
    assert result["undo"]["clrs"] == [
        {"undone_lsn": 6, "txn_id": 2, "page_id": 30, "undo_next_lsn": 4},
        {"undone_lsn": 4, "txn_id": 2, "page_id": 10, "undo_next_lsn": None},
    ], "Basic: undo CLRs mismatch"

    assert result["undo"]["ended_txns"] == [2], "Basic: ended txns mismatch"


# ---------------------------------------------------------------------------
# Scenario 2: Fuzzy checkpoint + WAL suffix with COMMIT/END records
# Tests binary WAL suffix parsing and checkpoint merge with stale snapshots.
# ---------------------------------------------------------------------------

def test_fuzzy_checkpoint_with_wal_suffix():
    """Checkpoint taken between LSN 3-6. T1 commits within checkpoint window.
    T2's COMMIT and END records are in the binary WAL suffix (not SQLite).
    T3 starts after checkpoint and is active at crash.
    Page state in binary PGST format with partial flushes."""
    scenario = {
        "master_record_lsn": 3,
        "flushed_page_lsns": {"10": 2, "20": 1},
        "log": [
            {"lsn": 0, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 1, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": None, "page_id": 20},
            {"lsn": 2, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 0, "page_id": 30},
            {"lsn": 3, "type": "BEGIN_CHECKPOINT"},
            {"lsn": 4, "type": "COMMIT", "txn_id": 1, "prev_lsn": 2},
            {"lsn": 5, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 1, "page_id": 40},
            {"lsn": 6, "type": "END_CHECKPOINT",
             "txn_table": {
                 "1": {"status": "RUNNING", "last_lsn": 2},
                 "2": {"status": "RUNNING", "last_lsn": 1},
             },
             "dirty_page_table": {"10": 0, "20": 1, "30": 2}},
            {"lsn": 7, "type": "UPDATE", "txn_id": 3,
             "prev_lsn": None, "page_id": 10},
        ],
        # These records are in the binary WAL suffix, not SQLite
        "wal_suffix": [
            {"lsn": 8, "type": "COMMIT", "txn_id": 2, "prev_lsn": 5},
            {"lsn": 9, "type": "END", "txn_id": 2, "prev_lsn": 8},
        ],
    }
    result = run_recovery(scenario)

    # --- Analysis ---
    assert result["analysis"]["transaction_table"] == {
        "1": {"status": "COMMITTING", "last_lsn": 4},
        "3": {"status": "RUNNING", "last_lsn": 7},
    }, "Fuzzy: analysis transaction table mismatch"

    assert result["analysis"]["dirty_page_table"] == {
        "10": 0, "20": 1, "30": 2, "40": 5,
    }, "Fuzzy: analysis DPT mismatch"

    # --- Redo ---
    assert result["redo"] == [2, 5, 7], "Fuzzy: redo set mismatch"

    # --- Undo (only T3 needs undo) ---
    assert result["undo"]["clrs"] == [
        {"undone_lsn": 7, "txn_id": 3, "page_id": 10, "undo_next_lsn": None},
    ], "Fuzzy: undo CLRs mismatch"

    assert result["undo"]["ended_txns"] == [3], "Fuzzy: ended txns mismatch"


# ---------------------------------------------------------------------------
# Scenario 3: CLR chains from interrupted prior recovery
# Tests CLR undo_next_lsn traversal. No WAL suffix.
# ---------------------------------------------------------------------------

def test_clr_chains():
    """First crash after two active transactions. Prior recovery wrote
    ABORT records and some CLRs before a second crash. The engine must
    follow CLR undo_next_lsn chains to skip already-undone records."""
    scenario = {
        "master_record_lsn": 0,
        "flushed_page_lsns": {},
        "log": [
            {"lsn": 0, "type": "BEGIN_CHECKPOINT"},
            {"lsn": 1, "type": "END_CHECKPOINT",
             "txn_table": {}, "dirty_page_table": {}},
            {"lsn": 2, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 3, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 2, "page_id": 20},
            {"lsn": 4, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 3, "page_id": 30},
            {"lsn": 5, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": None, "page_id": 40},
            {"lsn": 6, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 5, "page_id": 50},
            # --- First crash, recovery starts ---
            {"lsn": 7, "type": "ABORT", "txn_id": 1, "prev_lsn": 4},
            {"lsn": 8, "type": "ABORT", "txn_id": 2, "prev_lsn": 6},
            {"lsn": 9, "type": "CLR", "txn_id": 1, "prev_lsn": 7,
             "page_id": 30, "undo_next_lsn": 3},
            {"lsn": 10, "type": "CLR", "txn_id": 2, "prev_lsn": 8,
             "page_id": 50, "undo_next_lsn": 5},
            {"lsn": 11, "type": "CLR", "txn_id": 1, "prev_lsn": 9,
             "page_id": 20, "undo_next_lsn": 2},
            # --- Second crash during recovery ---
        ],
    }
    result = run_recovery(scenario)

    # --- Analysis ---
    assert result["analysis"]["transaction_table"] == {
        "1": {"status": "ABORTING", "last_lsn": 11},
        "2": {"status": "ABORTING", "last_lsn": 10},
    }, "CLR: analysis transaction table mismatch"

    assert result["analysis"]["dirty_page_table"] == {
        "10": 2, "20": 3, "30": 4, "40": 5, "50": 6,
    }, "CLR: analysis DPT mismatch"

    # --- Redo (all unflushed → redo all UPDATE and CLR records) ---
    assert result["redo"] == [2, 3, 4, 5, 6, 9, 10, 11], \
        "CLR: redo set mismatch"

    # --- Undo ---
    # T1@11: CLR → follow undo_next=2 → T1@2: UPDATE → CLR
    # T2@10: CLR → follow undo_next=5 → T2@5: UPDATE → CLR
    assert result["undo"]["clrs"] == [
        {"undone_lsn": 5, "txn_id": 2, "page_id": 40, "undo_next_lsn": None},
        {"undone_lsn": 2, "txn_id": 1, "page_id": 10, "undo_next_lsn": None},
    ], "CLR: undo CLRs mismatch"

    assert result["undo"]["ended_txns"] == [2, 1], \
        "CLR: ended txns order mismatch"


# ---------------------------------------------------------------------------
# Scenario 4: Selective redo — binary PGST with partially flushed pages
# Tests redo filtering based on binary-encoded on-disk page state. No undo.
# ---------------------------------------------------------------------------

def test_selective_redo():
    """All transactions committed. Pages partially flushed to disk
    (encoded in PGST binary format). Tests that redo correctly filters
    based on binary-derived page state. No undo needed."""
    scenario = {
        "master_record_lsn": 0,
        "flushed_page_lsns": {"10": 5, "20": 3, "30": 0},
        "log": [
            {"lsn": 0, "type": "BEGIN_CHECKPOINT"},
            {"lsn": 1, "type": "END_CHECKPOINT",
             "txn_table": {}, "dirty_page_table": {}},
            {"lsn": 2, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 3, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 2, "page_id": 20},
            {"lsn": 4, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": None, "page_id": 30},
            {"lsn": 5, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 3, "page_id": 10},
            {"lsn": 6, "type": "COMMIT", "txn_id": 1, "prev_lsn": 5},
            {"lsn": 7, "type": "END", "txn_id": 1, "prev_lsn": 6},
            {"lsn": 8, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 4, "page_id": 20},
            {"lsn": 9, "type": "COMMIT", "txn_id": 2, "prev_lsn": 8},
        ],
    }
    result = run_recovery(scenario)

    # --- Analysis ---
    assert result["analysis"]["transaction_table"] == {
        "2": {"status": "COMMITTING", "last_lsn": 9},
    }, "Selective: analysis transaction table mismatch"

    assert result["analysis"]["dirty_page_table"] == {
        "10": 2, "20": 3, "30": 4,
    }, "Selective: analysis DPT mismatch"

    # --- Redo ---
    assert result["redo"] == [4, 8], "Selective: redo set mismatch"

    # --- Undo (all committed → nothing to undo) ---
    assert result["undo"]["clrs"] == [], "Selective: should have no CLRs"
    assert result["undo"]["ended_txns"] == [], \
        "Selective: should have no ended txns"


# ---------------------------------------------------------------------------
# Scenario 5: Complex multi-txn with CLR + WAL suffix containing CLR/UPDATE
# Tests all phases under complex interleaving with binary WAL suffix records.
# ---------------------------------------------------------------------------

def test_complex_multi_txn_with_wal_suffix():
    """Four transactions with interleaved operations. Fuzzy checkpoint.
    T3 commits and ends. T1 aborts and partially undone (CLR at LSN 12
    is in the binary WAL suffix). T2 and T4 active at crash, with T4's
    last UPDATE (LSN 13) also in the WAL suffix.
    Tests all phases with data split across SQLite and binary WAL suffix."""
    scenario = {
        "master_record_lsn": 4,
        "flushed_page_lsns": {"10": 6, "30": 5, "40": 0},
        "log": [
            {"lsn": 0, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": None, "page_id": 10},
            {"lsn": 1, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": None, "page_id": 20},
            {"lsn": 2, "type": "UPDATE", "txn_id": 3,
             "prev_lsn": None, "page_id": 30},
            {"lsn": 3, "type": "UPDATE", "txn_id": 1,
             "prev_lsn": 0, "page_id": 40},
            {"lsn": 4, "type": "BEGIN_CHECKPOINT"},
            {"lsn": 5, "type": "COMMIT", "txn_id": 3, "prev_lsn": 2},
            {"lsn": 6, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 1, "page_id": 10},
            {"lsn": 7, "type": "END_CHECKPOINT",
             "txn_table": {
                 "1": {"status": "RUNNING", "last_lsn": 3},
                 "2": {"status": "RUNNING", "last_lsn": 1},
                 "3": {"status": "RUNNING", "last_lsn": 2},
             },
             "dirty_page_table": {
                 "10": 0, "20": 1, "30": 2, "40": 3,
             }},
            {"lsn": 8, "type": "END", "txn_id": 3, "prev_lsn": 5},
            {"lsn": 9, "type": "UPDATE", "txn_id": 4,
             "prev_lsn": None, "page_id": 50},
            {"lsn": 10, "type": "ABORT", "txn_id": 1, "prev_lsn": 3},
            {"lsn": 11, "type": "UPDATE", "txn_id": 2,
             "prev_lsn": 6, "page_id": 60},
        ],
        # CLR and UPDATE records in binary WAL suffix
        "wal_suffix": [
            {"lsn": 12, "type": "CLR", "txn_id": 1, "prev_lsn": 10,
             "page_id": 40, "undo_next_lsn": 0},
            {"lsn": 13, "type": "UPDATE", "txn_id": 4,
             "prev_lsn": 9, "page_id": 10},
        ],
    }
    result = run_recovery(scenario)

    # --- Analysis ---
    assert result["analysis"]["transaction_table"] == {
        "1": {"status": "ABORTING", "last_lsn": 12},
        "2": {"status": "RUNNING", "last_lsn": 11},
        "4": {"status": "RUNNING", "last_lsn": 13},
    }, "Complex: analysis transaction table mismatch"

    assert result["analysis"]["dirty_page_table"] == {
        "10": 0, "20": 1, "30": 2, "40": 3, "50": 9, "60": 11,
    }, "Complex: analysis DPT mismatch"

    # --- Redo ---
    assert result["redo"] == [1, 3, 9, 11, 12, 13], \
        "Complex: redo set mismatch"

    # --- Undo ---
    assert result["undo"]["clrs"] == [
        {"undone_lsn": 13, "txn_id": 4, "page_id": 10, "undo_next_lsn": 9},
        {"undone_lsn": 11, "txn_id": 2, "page_id": 60, "undo_next_lsn": 6},
        {"undone_lsn": 9, "txn_id": 4, "page_id": 50, "undo_next_lsn": None},
        {"undone_lsn": 6, "txn_id": 2, "page_id": 10, "undo_next_lsn": 1},
        {"undone_lsn": 1, "txn_id": 2, "page_id": 20, "undo_next_lsn": None},
        {"undone_lsn": 0, "txn_id": 1, "page_id": 10, "undo_next_lsn": None},
    ], "Complex: undo CLRs mismatch"

    assert result["undo"]["ended_txns"] == [4, 2, 1], \
        "Complex: ended txns order mismatch"
