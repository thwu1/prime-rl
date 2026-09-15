#!/usr/bin/env python3
"""Generate Jepsen-format EDN history files for the linearizability analyzer task."""

import os


def value_to_edn(val):
    """Convert a Python value to its EDN representation."""
    if val is None:
        return "nil"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(val)
    if isinstance(val, list):
        return "[" + " ".join(value_to_edn(v) for v in val) + "]"
    if isinstance(val, str):
        return '"' + val + '"'
    return str(val)


def event_to_edn(event):
    """Convert a Python event dict to an EDN map string."""
    parts = [
        f":index {event['index']}",
        f":process {event['process']}",
        f":type :{event['type']}",
        f":f :{event['f']}",
        f":value {value_to_edn(event.get('value'))}",
    ]
    return "{" + " ".join(parts) + "}"


def history_to_edn(history):
    """Convert a list of event dicts to an EDN vector string."""
    events = [event_to_edn(e) for e in history]
    return "[\n " + "\n ".join(events) + "\n]"


HISTORIES = {
    "h01_simple_linear.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 1},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 1},
        {"index": 2, "process": 1, "type": "invoke", "f": "read", "value": None},
        {"index": 3, "process": 1, "type": "ok", "f": "read", "value": 1},
    ],
    "h02_stale_read.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 1},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 1},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 2},
        {"index": 3, "process": 1, "type": "ok", "f": "write", "value": 2},
        {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 1},
    ],
    "h03_concurrent_writes.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 1},
        {"index": 1, "process": 1, "type": "invoke", "f": "write", "value": 2},
        {"index": 2, "process": 0, "type": "ok", "f": "write", "value": 1},
        {"index": 3, "process": 1, "type": "ok", "f": "write", "value": 2},
        {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 1},
    ],
    "h04_impossible_value.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 1},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 1},
        {"index": 2, "process": 1, "type": "invoke", "f": "read", "value": None},
        {"index": 3, "process": 1, "type": "ok", "f": "read", "value": 3},
    ],
    "h05_info_linearizable.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 5},
        {"index": 3, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 4, "process": 1, "type": "info", "f": "write", "value": 5},
        {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 5},
    ],
    "h06_cas_conflict.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "cas", "value": [0, 1]},
        {"index": 3, "process": 2, "type": "invoke", "f": "cas", "value": [0, 2]},
        {"index": 4, "process": 1, "type": "ok", "f": "cas", "value": [0, 1]},
        {"index": 5, "process": 2, "type": "ok", "f": "cas", "value": [0, 2]},
    ],
    "h07_cas_with_fail.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "cas", "value": [0, 1]},
        {"index": 3, "process": 2, "type": "invoke", "f": "cas", "value": [0, 2]},
        {"index": 4, "process": 1, "type": "ok", "f": "cas", "value": [0, 1]},
        {"index": 5, "process": 2, "type": "fail", "f": "cas", "value": [0, 2]},
        {"index": 6, "process": 3, "type": "invoke", "f": "read", "value": None},
        {"index": 7, "process": 3, "type": "ok", "f": "read", "value": 1},
    ],
    "h08_complex_nonlinear.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 1},
        {"index": 3, "process": 1, "type": "ok", "f": "write", "value": 1},
        {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 5, "process": 3, "type": "invoke", "f": "write", "value": 2},
        {"index": 6, "process": 2, "type": "ok", "f": "read", "value": 0},
        {"index": 7, "process": 3, "type": "ok", "f": "write", "value": 2},
    ],
    "h09_cas_chain.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "cas", "value": [0, 1]},
        {"index": 3, "process": 1, "type": "ok", "f": "cas", "value": [0, 1]},
        {"index": 4, "process": 2, "type": "invoke", "f": "cas", "value": [1, 2]},
        {"index": 5, "process": 3, "type": "invoke", "f": "read", "value": None},
        {"index": 6, "process": 2, "type": "ok", "f": "cas", "value": [1, 2]},
        {"index": 7, "process": 3, "type": "ok", "f": "read", "value": 2},
        {"index": 8, "process": 4, "type": "invoke", "f": "cas", "value": [2, 3]},
        {"index": 9, "process": 4, "type": "ok", "f": "cas", "value": [2, 3]},
        {"index": 10, "process": 0, "type": "invoke", "f": "read", "value": None},
        {"index": 11, "process": 0, "type": "ok", "f": "read", "value": 3},
    ],
    "h10_info_contradiction.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 5},
        {"index": 3, "process": 1, "type": "info", "f": "write", "value": 5},
        {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 5},
        {"index": 6, "process": 3, "type": "invoke", "f": "read", "value": None},
        {"index": 7, "process": 3, "type": "ok", "f": "read", "value": 0},
    ],
    "h11_stress.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 10},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 10},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 20},
        {"index": 3, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 4, "process": 1, "type": "ok", "f": "write", "value": 20},
        {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 10},
        {"index": 6, "process": 3, "type": "invoke", "f": "cas", "value": [20, 30]},
        {"index": 7, "process": 3, "type": "ok", "f": "cas", "value": [20, 30]},
        {"index": 8, "process": 4, "type": "invoke", "f": "read", "value": None},
        {"index": 9, "process": 0, "type": "invoke", "f": "write", "value": 40},
        {"index": 10, "process": 4, "type": "ok", "f": "read", "value": 30},
        {"index": 11, "process": 0, "type": "ok", "f": "write", "value": 40},
        {"index": 12, "process": 1, "type": "invoke", "f": "read", "value": None},
        {"index": 13, "process": 1, "type": "ok", "f": "read", "value": 40},
        {"index": 14, "process": 2, "type": "invoke", "f": "cas", "value": [40, 50]},
        {"index": 15, "process": 3, "type": "invoke", "f": "cas", "value": [40, 60]},
        {"index": 16, "process": 2, "type": "ok", "f": "cas", "value": [40, 50]},
        {"index": 17, "process": 3, "type": "fail", "f": "cas", "value": [40, 60]},
        {"index": 18, "process": 4, "type": "invoke", "f": "read", "value": None},
        {"index": 19, "process": 4, "type": "ok", "f": "read", "value": 50},
    ],
    "h12_floating_info.edn": [
        {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
        {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
        {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 5},
        {"index": 3, "process": 1, "type": "info", "f": "write", "value": 5},
        {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
        {"index": 5, "process": 3, "type": "invoke", "f": "read", "value": None},
        {"index": 6, "process": 2, "type": "ok", "f": "read", "value": 5},
        {"index": 7, "process": 3, "type": "ok", "f": "read", "value": 0},
    ],
}


def generate(output_dir="/app/histories"):
    """Generate all EDN history files."""
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith((".edn", ".json")):
                os.remove(os.path.join(output_dir, f))
    os.makedirs(output_dir, exist_ok=True)
    for filename, history in HISTORIES.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            f.write(history_to_edn(history))


if __name__ == "__main__":
    generate()
