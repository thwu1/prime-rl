#!/usr/bin/env python3
"""
Cluster resource scheduler.

Reads cluster state from /app/cluster_state.json and writes scheduling
decisions to /app/schedule_output.json.

See /app/spec.md for the scheduling algorithm specification.
See /app/schema.md for input/output JSON format.

Anti-affinity constraints and scheduling policy parameters are stored
in /app/cluster_config.db (SQLite). Query them at runtime.
"""

import json
from datetime import datetime


def load_state(path="/app/cluster_state.json"):
    with open(path) as f:
        return json.load(f)


def write_output(output, path="/app/schedule_output.json"):
    with open(path, "w") as f:
        json.dump(output, f, indent=2)


def parse_time(ts):
    """Parse ISO 8601 timestamp string to datetime."""
    if ts is None:
        return datetime.min
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def schedule(state):
    """
    Implement the scheduling algorithm per /app/spec.md.
    Must dispatch to fair_share or priority mode based on state["scheduler_type"].

    Returns a dict with keys:
      - to_allocate: dict mapping task_id -> agent_id for newly allocated tasks
      - to_release: list of allocation_ids for tasks being released/preempted
      - group_offers: dict mapping group_id -> offered GPU slots (fair-share only)
    """
    raise NotImplementedError("Implement the scheduling algorithm per /app/spec.md")


def main():
    state = load_state()
    output = schedule(state)
    write_output(output)


if __name__ == "__main__":
    main()
