#!/usr/bin/env python3
"""Generate protocol interaction traces for the state machine inference task.

Simulates a custom FTP-like protocol with states:
  INIT -> CONNECTED -> AWAITING_AUTH -> AUTHENTICATED -> TRANSFERRING -> CLOSED

Two fuzzers are simulated:
  - "aflnet" (state-aware, achieves better coverage)
  - "baseline" (less state-aware, worse coverage)
"""
import json
import os

# Training traces from "aflnet" fuzzer (state-aware, better coverage)
aflnet_traces = [
    # 1: Simple list
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("LIST", 150), ("QUIT", 221)],
    # 2: Full transfer cycle
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("DATA", 226), ("DONE", 250), ("QUIT", 221)],
    # 3: CWD + transfer with multiple DATA chunks
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("CWD", 250),
     ("LIST", 150), ("RETR", 125), ("DATA", 226), ("DATA", 226),
     ("DONE", 250), ("QUIT", 221)],
    # 4: Auth failure then success, repeated list
    [("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("USER", 331),
     ("PASS_OK", 230), ("LIST", 150), ("LIST", 150), ("QUIT", 221)],
    # 5: Transfer abort then list
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("ABOR", 426), ("LIST", 150), ("QUIT", 221)],
    # 6: Transfer abort after DATA, then new transfer
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("DATA", 226), ("ABOR", 426), ("RETR", 125), ("DONE", 250), ("QUIT", 221)],
    # 7: Multiple CWDs, transfer, then list
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("CWD", 250),
     ("CWD", 250), ("RETR", 125), ("DATA", 226), ("DONE", 250),
     ("LIST", 150), ("QUIT", 221)],
    # 8: Transfer, CWD, another transfer with many DATA chunks
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("DONE", 250), ("CWD", 250), ("RETR", 125), ("DATA", 226),
     ("DATA", 226), ("DATA", 226), ("DONE", 250), ("QUIT", 221)],
    # 9: List, CWD, list, transfer
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("LIST", 150),
     ("CWD", 250), ("LIST", 150), ("RETR", 125), ("DONE", 250), ("QUIT", 221)],
    # 10: Multiple auth failures then direct transfer quit
    [("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("USER", 331),
     ("PASS_FAIL", 530), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("QUIT", 221)],
]

# Training traces from "baseline" fuzzer (less state-aware, worse coverage)
baseline_traces = [
    # 11: Simple list
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("LIST", 150), ("QUIT", 221)],
    # 12: Login and immediate quit
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("QUIT", 221)],
    # 13: Repeated list only
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("LIST", 150),
     ("LIST", 150), ("LIST", 150), ("QUIT", 221)],
    # 14: Auth failure and quit
    [("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("QUIT", 221)],
    # 15: CWD and quit
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("CWD", 250), ("QUIT", 221)],
    # 16: Simple transfer
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("DATA", 226), ("DONE", 250), ("QUIT", 221)],
    # 17: Connect and quit without auth
    [("CONNECT", 220), ("QUIT", 221)],
    # 18: List then CWD
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("LIST", 150),
     ("CWD", 250), ("QUIT", 221)],
    # 19: Transfer without DATA
    [("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
     ("DONE", 250), ("QUIT", 221)],
    # 20: Auth failure, retry, list
    [("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("USER", 331),
     ("PASS_OK", 230), ("LIST", 150), ("QUIT", 221)],
]

# Test traces for anomaly detection
test_traces = [
    # T1: Normal - full transfer with CWD
    {"conforming": True, "interactions": [
        ("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("CWD", 250),
        ("RETR", 125), ("DATA", 226), ("DONE", 250), ("QUIT", 221)]},
    # T2: Normal - auth retry then CWD + list
    {"conforming": True, "interactions": [
        ("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("USER", 331),
        ("PASS_OK", 230), ("CWD", 250), ("LIST", 150), ("QUIT", 221)]},
    # T3: Normal - abort then new transfer
    {"conforming": True, "interactions": [
        ("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("RETR", 125),
        ("ABOR", 426), ("RETR", 125), ("DONE", 250), ("QUIT", 221)]},
    # T4: Anomalous - DATA from authenticated state (no RETR first)
    {"conforming": False, "anomaly_index": 3, "interactions": [
        ("CONNECT", 220), ("USER", 331), ("PASS_OK", 230), ("DATA", 226),
        ("QUIT", 221)]},
    # T5: Anomalous - LIST from failed auth state
    {"conforming": False, "anomaly_index": 3, "interactions": [
        ("CONNECT", 220), ("USER", 331), ("PASS_FAIL", 530), ("LIST", 150),
        ("QUIT", 221)]},
]


def make_session(trace, session_id, fuzzer):
    interactions = []
    ts = 0
    for req, resp in trace:
        interactions.append({
            "request": req,
            "response_code": resp,
            "timestamp_ms": ts
        })
        ts += 50 + ((hash((req, resp, session_id)) % 100 + 100) % 100)
    return {
        "session_id": "s{:03d}".format(session_id),
        "fuzzer": fuzzer,
        "interactions": interactions
    }


def main():
    os.makedirs("/app/traces/training", exist_ok=True)
    os.makedirs("/app/traces/test", exist_ok=True)
    os.makedirs("/app/output", exist_ok=True)

    # Write training traces - aflnet (sessions 1-10)
    for i, trace in enumerate(aflnet_traces, 1):
        session = make_session(trace, i, "aflnet")
        path = "/app/traces/training/session_{:03d}.json".format(i)
        with open(path, "w") as f:
            json.dump(session, f, indent=2)

    # Write training traces - baseline (sessions 11-20)
    for i, trace in enumerate(baseline_traces, 1):
        session = make_session(trace, 10 + i, "baseline")
        path = "/app/traces/training/session_{:03d}.json".format(10 + i)
        with open(path, "w") as f:
            json.dump(session, f, indent=2)

    # Write test traces
    for i, test in enumerate(test_traces, 1):
        session_data = {
            "session_id": "test_{:03d}".format(i),
            "interactions": [
                {"request": req, "response_code": resp}
                for req, resp in test["interactions"]
            ]
        }
        path = "/app/traces/test/test_{:03d}.json".format(i)
        with open(path, "w") as f:
            json.dump(session_data, f, indent=2)


if __name__ == "__main__":
    main()
