#!/usr/bin/env python3
"""Creates normalized SQLite coverage databases for packet_router regressions."""

import sqlite3
import os
import json

DB_DIR = "/data/coverage_dbs"

SCHEMA = """
CREATE TABLE run_metadata (
    run_id INTEGER PRIMARY KEY,
    test_name TEXT NOT NULL,
    seed INTEGER,
    timestamp TEXT,
    simulator TEXT,
    sim_version TEXT,
    status TEXT NOT NULL
);
CREATE TABLE line_hits (line_no INTEGER NOT NULL, hit INTEGER NOT NULL);
CREATE TABLE branch_hits (branch_id TEXT NOT NULL, hit INTEGER NOT NULL);
CREATE TABLE toggle_hits (
    signal_name TEXT NOT NULL,
    bit_idx INTEGER NOT NULL,
    direction INTEGER NOT NULL,
    hit INTEGER NOT NULL
);
CREATE TABLE cg_inst (cg_id INTEGER PRIMARY KEY, cg_name TEXT NOT NULL);
CREATE TABLE cp_defs (
    cp_id INTEGER PRIMARY KEY,
    cg_id INTEGER NOT NULL,
    cp_name TEXT NOT NULL,
    is_cross INTEGER NOT NULL DEFAULT 0,
    threshold INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE bin_defs (
    bin_id INTEGER PRIMARY KEY,
    cp_id INTEGER NOT NULL,
    bin_label TEXT NOT NULL
);
CREATE TABLE cross_refs (
    cross_cp_id INTEGER NOT NULL,
    member_cp_id INTEGER NOT NULL,
    axis_order INTEGER NOT NULL
);
CREATE TABLE func_hits (bin_id INTEGER NOT NULL, hit_count INTEGER NOT NULL);
CREATE TABLE cross_bin_hits (
    cp_id INTEGER NOT NULL,
    bin_label TEXT NOT NULL,
    hit_count INTEGER NOT NULL
);
CREATE TABLE fsm_state_defs (
    state_id INTEGER PRIMARY KEY,
    fsm_name TEXT NOT NULL,
    state_name TEXT NOT NULL,
    encoding INTEGER NOT NULL
);
CREATE TABLE fsm_trans_defs (
    trans_id INTEGER PRIMARY KEY,
    fsm_name TEXT NOT NULL,
    src_state_id INTEGER NOT NULL,
    dst_state_id INTEGER NOT NULL
);
CREATE TABLE fsm_state_hits (state_id INTEGER NOT NULL, hit INTEGER NOT NULL);
CREATE TABLE fsm_trans_hits (trans_id INTEGER NOT NULL, hit INTEGER NOT NULL);
CREATE TABLE exclusion_rules (
    rule_id INTEGER PRIMARY KEY,
    category INTEGER NOT NULL,
    target_json TEXT NOT NULL,
    cascade INTEGER NOT NULL DEFAULT 0,
    reason TEXT
);
CREATE TABLE assertion_results (
    assertion_id INTEGER NOT NULL,
    assertion_name TEXT NOT NULL,
    check_type TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    passes INTEGER NOT NULL,
    failures INTEGER NOT NULL
);
CREATE TABLE condition_expr (
    expr_id INTEGER NOT NULL,
    expr_text TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    hit INTEGER NOT NULL
);
"""

SIGNALS = [("pkt_data", 8), ("route_ctrl", 4), ("status", 3)]
ALL_BRANCHES = [f"B{i}" for i in range(1, 17)]

FSM_STATES = [
    (1, "router_fsm", "IDLE", 0),
    (2, "router_fsm", "PARSE_HDR", 1),
    (3, "router_fsm", "ROUTE", 2),
    (4, "router_fsm", "FORWARD", 3),
    (5, "router_fsm", "DROP", 4),
    (6, "router_fsm", "ERROR", 5),
    (7, "router_fsm", "RETRY", 6),
]

FSM_TRANSITIONS = [
    (1, "router_fsm", 1, 2),
    (2, "router_fsm", 2, 3),
    (3, "router_fsm", 2, 5),
    (4, "router_fsm", 3, 4),
    (5, "router_fsm", 3, 5),
    (6, "router_fsm", 4, 1),
    (7, "router_fsm", 5, 1),
    (8, "router_fsm", 3, 6),
    (9, "router_fsm", 6, 7),
    (10, "router_fsm", 7, 2),
    (11, "router_fsm", 7, 5),
    (12, "router_fsm", 6, 1),
    (13, "router_fsm", 4, 6),
    (14, "router_fsm", 2, 6),
]

CG_DEFS = [(1, "cg_packet_type"), (2, "cg_priority")]

CP_DEFS = [
    (1, 1, "cp_pkt_type", 0, 1),
    (2, 1, "cp_pkt_size", 0, 1),
    (3, 1, "cx_type_x_size", 1, 1),
    (4, 2, "cp_priority", 0, 1),
    (5, 2, "cp_qos", 0, 1),
    (6, 2, "cx_priority_x_qos", 1, 1),
]

BIN_DEFS = [
    (1, 1, "DATA"), (2, 1, "CTRL"), (3, 1, "MGMT"), (4, 1, "ERR"),
    (5, 1, "SYNC"), (6, 1, "ACK"), (7, 1, "NACK"), (8, 1, "RESET"),
    (9, 2, "SMALL"), (10, 2, "MEDIUM"), (11, 2, "LARGE"), (12, 2, "JUMBO"),
    (13, 4, "LOW"), (14, 4, "MEDIUM"), (15, 4, "HIGH"), (16, 4, "CRITICAL"),
    (17, 5, "BEST_EFFORT"), (18, 5, "ASSURED"),
    (19, 5, "EXPEDITED"), (20, 5, "CONTROL"),
]

CROSS_REFS = [
    (3, 1, 0), (3, 2, 1),
    (6, 4, 0), (6, 5, 1),
]

EXCLUSION_RULES = [
    (1, 0, json.dumps({"signal": "status", "bit": 2, "dir": 1}), 0,
     "Signal stuck-at-0 by design (tied to ground in packet_router)"),
    (2, 1,
     json.dumps({"cg": "cg_packet_type", "cross": "cx_type_x_size",
                 "bin": "ERR:JUMBO"}),
     0, "Hardware limitation: error packets cannot be jumbo-sized"),
    (3, 2, json.dumps({"fsm": "router_fsm", "state": "ERROR"}), 1,
     "Error recovery logic verified separately via formal methods"),
]

ASSERTIONS = [
    (1, "pkt_valid_check", "assert", 1000, 998, 2),
    (2, "route_stable_check", "assume", 500, 500, 0),
    (3, "fifo_overflow_check", "cover", 200, 45, 0),
    (4, "clk_glitch_check", "assert", 750, 750, 0),
]

COND_EXPRS = [
    (1, "pkt_data[7:0] == 8'hFF", 0, 1),
    (1, "pkt_data[7:0] == 8'hFF", 1, 0),
    (2, "route_ctrl[3:0] != 4'b0", 0, 1),
    (2, "route_ctrl[3:0] != 4'b0", 1, 1),
    (3, "(status[1] & ~status[0])", 0, 1),
    (3, "(status[1] & ~status[0])", 1, 0),
    (3, "(status[1] & ~status[0])", 2, 1),
    (3, "(status[1] & ~status[0])", 3, 0),
]

# direction encoding: 0 = rising (0->1), 1 = falling (1->0)
RUNS = [
    {
        "metadata": (1, "basic_forwarding_test", 12345,
                     "2024-01-15T10:30:00Z", "xcelium", "23.09", "PASSED"),
        "hit_lines": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 16, 17, 18, 20],
        "hit_branches": ["B1", "B2", "B3", "B5", "B7", "B9", "B11"],
        "hit_toggles": {
            ("pkt_data", 0, 0), ("pkt_data", 0, 1),
            ("pkt_data", 1, 0),
            ("pkt_data", 2, 0), ("pkt_data", 2, 1),
            ("pkt_data", 3, 0),
            ("pkt_data", 5, 0),
            ("route_ctrl", 0, 0), ("route_ctrl", 0, 1),
            ("route_ctrl", 1, 0),
            ("status", 0, 0),
        },
        "cp_hits": {
            1: {1: 15, 2: 8, 3: 3},
            2: {9: 10, 10: 12},
            4: {13: 20, 14: 15},
            5: {17: 8, 18: 12},
        },
        "cx_hits": {
            3: {"DATA:SMALL": 5, "DATA:MEDIUM": 3, "CTRL:SMALL": 2,
                "CTRL:MEDIUM": 4, "MGMT:SMALL": 1, "MGMT:MEDIUM": 2},
            6: {"LOW:BEST_EFFORT": 5, "LOW:ASSURED": 8,
                "MEDIUM:BEST_EFFORT": 3, "MEDIUM:ASSURED": 7},
        },
        "hit_states": {1, 2, 3, 4},
        "hit_transitions": {1, 2, 4, 6},
    },
    {
        "metadata": (2, "error_handling_test", 67890,
                     "2024-01-15T11:45:00Z", "xcelium", "23.09", "PASSED"),
        "hit_lines": [5, 6, 7, 8, 11, 12, 13, 14, 15, 19, 20, 21, 22],
        "hit_branches": ["B2", "B4", "B6", "B8", "B10", "B12"],
        "hit_toggles": {
            ("pkt_data", 1, 1),
            ("pkt_data", 3, 1),
            ("pkt_data", 4, 0), ("pkt_data", 4, 1),
            ("pkt_data", 6, 0),
            ("route_ctrl", 1, 1),
            ("route_ctrl", 2, 0), ("route_ctrl", 2, 1),
            ("status", 0, 1),
            ("status", 1, 0),
        },
        "cp_hits": {
            1: {1: 5, 4: 12, 5: 6, 6: 4},
            2: {10: 8, 11: 7},
            4: {14: 10, 15: 8},
            5: {18: 6, 19: 9},
        },
        "cx_hits": {
            3: {"DATA:MEDIUM": 2, "DATA:LARGE": 3, "ERR:MEDIUM": 4,
                "ERR:LARGE": 2, "SYNC:MEDIUM": 3, "SYNC:LARGE": 1,
                "ACK:MEDIUM": 2, "ACK:LARGE": 1},
            6: {"MEDIUM:ASSURED": 3, "MEDIUM:EXPEDITED": 5,
                "HIGH:ASSURED": 4, "HIGH:EXPEDITED": 3},
        },
        "hit_states": {1, 2, 3, 4, 5},
        "hit_transitions": {1, 2, 3, 5, 7},
    },
    {
        "metadata": (3, "retry_stress_test", 24680,
                     "2024-01-15T14:20:00Z", "xcelium", "23.09", "PASSED"),
        "hit_lines": [1, 2, 3, 9, 10, 16, 17, 18, 23, 24, 25, 26],
        "hit_branches": ["B1", "B3", "B5", "B7", "B13", "B14"],
        "hit_toggles": {
            ("pkt_data", 5, 1),
            ("pkt_data", 6, 1),
            ("pkt_data", 7, 0),
            ("route_ctrl", 3, 0),
            ("status", 1, 1),
            ("status", 2, 0),
        },
        "cp_hits": {
            1: {2: 6, 3: 4, 7: 7},
            2: {9: 5, 11: 8, 12: 3},
            4: {15: 5, 16: 11},
            5: {17: 4, 20: 7},
        },
        "cx_hits": {
            3: {"CTRL:SMALL": 2, "CTRL:LARGE": 3, "CTRL:JUMBO": 1,
                "MGMT:LARGE": 4, "MGMT:JUMBO": 2,
                "NACK:SMALL": 3, "NACK:LARGE": 2, "NACK:JUMBO": 1},
            6: {"HIGH:CONTROL": 3,
                "CRITICAL:BEST_EFFORT": 5, "CRITICAL:CONTROL": 4},
        },
        "hit_states": {1, 2, 3, 4, 7},
        "hit_transitions": {1, 2, 4, 6, 8, 9, 10},
    },
    {
        "metadata": (4, "edge_case_test", 13579,
                     "2024-01-15T16:05:00Z", "xcelium", "23.09", "PASSED"),
        "hit_lines": [4, 11, 12, 13, 14, 19, 21, 22, 27, 28],
        "hit_branches": ["B4", "B6", "B8", "B9", "B10", "B15"],
        "hit_toggles": {
            ("route_ctrl", 3, 1),
        },
        "cp_hits": {
            1: {1: 3, 5: 2, 6: 5, 8: 8},
            2: {10: 6, 12: 4},
            4: {13: 7, 16: 3},
            5: {19: 5, 20: 8},
        },
        "cx_hits": {
            3: {"DATA:MEDIUM": 1, "DATA:JUMBO": 2,
                "SYNC:MEDIUM": 1, "SYNC:JUMBO": 3,
                "ACK:MEDIUM": 2, "ACK:JUMBO": 1,
                "RESET:MEDIUM": 4, "RESET:JUMBO": 1},
            6: {"LOW:EXPEDITED": 3, "LOW:CONTROL": 4,
                "CRITICAL:EXPEDITED": 2, "CRITICAL:CONTROL": 1},
        },
        "hit_states": {1, 2, 3, 4, 6},
        "hit_transitions": {1, 2, 4, 8, 12, 13},
    },
    {
        "metadata": (5, "power_stress_test", 99999,
                     "2024-01-15T17:30:00Z", "xcelium", "23.09", "INCOMPLETE"),
        "hit_lines": [1, 2, 3, 4, 5, 29],
        "hit_branches": ["B1", "B2", "B16"],
        "hit_toggles": {
            ("pkt_data", 0, 0),
            ("pkt_data", 7, 1),
        },
        "cp_hits": {
            1: {1: 2, 7: 1},
            2: {9: 1},
            4: {13: 1},
            5: {17: 1},
        },
        "cx_hits": {
            3: {"DATA:SMALL": 1, "NACK:SMALL": 1},
            6: {"LOW:BEST_EFFORT": 1},
        },
        "hit_states": {1, 2, 3},
        "hit_transitions": {1, 2},
    },
]


def create_db(db_path, run_data):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    cur.execute("INSERT INTO run_metadata VALUES (?,?,?,?,?,?,?)",
                run_data["metadata"])

    hit_set = set(run_data["hit_lines"])
    for line in range(1, 31):
        cur.execute("INSERT INTO line_hits VALUES (?,?)",
                    (line, 1 if line in hit_set else 0))

    hit_set = set(run_data["hit_branches"])
    for b in ALL_BRANCHES:
        cur.execute("INSERT INTO branch_hits VALUES (?,?)",
                    (b, 1 if b in hit_set else 0))

    for sig_name, width in SIGNALS:
        for bit in range(width):
            for direction in [0, 1]:
                hit = 1 if (sig_name, bit, direction) in run_data[
                    "hit_toggles"] else 0
                cur.execute("INSERT INTO toggle_hits VALUES (?,?,?,?)",
                            (sig_name, bit, direction, hit))

    for cg_id, cg_name in CG_DEFS:
        cur.execute("INSERT INTO cg_inst VALUES (?,?)", (cg_id, cg_name))

    for cp_id, cg_id, cp_name, is_cross, threshold in CP_DEFS:
        cur.execute("INSERT INTO cp_defs VALUES (?,?,?,?,?)",
                    (cp_id, cg_id, cp_name, is_cross, threshold))

    for bin_id, cp_id, bin_label in BIN_DEFS:
        cur.execute("INSERT INTO bin_defs VALUES (?,?,?)",
                    (bin_id, cp_id, bin_label))

    for cross_cp_id, member_cp_id, axis_order in CROSS_REFS:
        cur.execute("INSERT INTO cross_refs VALUES (?,?,?)",
                    (cross_cp_id, member_cp_id, axis_order))

    for cp_id, bins in run_data["cp_hits"].items():
        for bin_id, hit_count in bins.items():
            cur.execute("INSERT INTO func_hits VALUES (?,?)",
                        (bin_id, hit_count))

    for cp_id, bins in run_data["cx_hits"].items():
        for bin_label, hit_count in bins.items():
            cur.execute("INSERT INTO cross_bin_hits VALUES (?,?,?)",
                        (cp_id, bin_label, hit_count))

    for state_id, fsm_name, state_name, encoding in FSM_STATES:
        cur.execute("INSERT INTO fsm_state_defs VALUES (?,?,?,?)",
                    (state_id, fsm_name, state_name, encoding))

    for trans_id, fsm_name, src_id, dst_id in FSM_TRANSITIONS:
        cur.execute("INSERT INTO fsm_trans_defs VALUES (?,?,?,?)",
                    (trans_id, fsm_name, src_id, dst_id))

    for state_id, _, _, _ in FSM_STATES:
        hit = 1 if state_id in run_data["hit_states"] else 0
        cur.execute("INSERT INTO fsm_state_hits VALUES (?,?)",
                    (state_id, hit))

    for trans_id, _, _, _ in FSM_TRANSITIONS:
        hit = 1 if trans_id in run_data["hit_transitions"] else 0
        cur.execute("INSERT INTO fsm_trans_hits VALUES (?,?)",
                    (trans_id, hit))

    for rule in EXCLUSION_RULES:
        cur.execute("INSERT INTO exclusion_rules VALUES (?,?,?,?,?)", rule)

    for assertion in ASSERTIONS:
        cur.execute(
            "INSERT INTO assertion_results VALUES (?,?,?,?,?,?)", assertion)

    for cond in COND_EXPRS:
        cur.execute("INSERT INTO condition_expr VALUES (?,?,?,?)", cond)

    conn.commit()
    conn.close()


def main():
    for i, run_data in enumerate(RUNS, 1):
        db_path = os.path.join(DB_DIR, f"run_{i:03d}.db")
        create_db(db_path, run_data)
        print(f"Created {db_path}")


if __name__ == "__main__":
    main()
