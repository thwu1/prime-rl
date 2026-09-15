#!/usr/bin/env python3
"""
OpenSearch ISM (Index State Management) Policy Simulator.

Reads ISM policy definitions and a simulation timeline, then produces a
state report showing the final state of all indices after processing.

"""

import json
import os
import re
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_duration(duration_str):
    """Parse a duration string like '1d', '12h' into a timedelta."""
    match = re.match(r'^(\d+)(h|d)$', duration_str)
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)


def parse_timestamp(ts):
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    ts = ts.replace('Z', '+00:00')
    return datetime.fromisoformat(ts)


def format_timestamp(dt):
    """Format a datetime to ISO 8601 with Z suffix."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def increment_index_name(name):
    """Increment the numeric suffix of an index name.

    E.g. 'logs-000001' -> 'logs-000002'
    """
    match = re.match(r'^(.*-)(\d+)$', name)
    if not match:
        raise ValueError(f"Cannot increment index name: {name}")
    prefix = match.group(1)
    num = int(match.group(2))
    width = len(match.group(2))
    return f"{prefix}{num + 1:0{width}d}"


class Index:
    """Represents a single index being tracked by the simulator."""

    def __init__(self, name, created_at, policy_id, write_alias=None):
        self.name = name
        self.created_at = created_at
        self.policy_id = policy_id
        self.state = None  # Set after policy lookup
        self.doc_count = 0
        self.size_bytes = 0
        self.rollover_done = False
        self.rollover_at = None
        self.replicas = 1  # OpenSearch default
        self.read_only = False
        self.write_alias = write_alias

    def age_at(self, current_time):
        """Return the age of this index at the given time."""
        return current_time - self.created_at

    def to_dict(self):
        """Serialize to a dictionary for the report."""
        return {
            "created_at": format_timestamp(self.created_at),
            "policy_id": self.policy_id,
            "state": self.state,
            "doc_count": self.doc_count,
            "size_bytes": self.size_bytes,
            "replicas": self.replicas,
            "read_only": self.read_only,
            "rollover_at": format_timestamp(self.rollover_at) if self.rollover_at else None,
        }


class ISMSimulator:
    """Simulates OpenSearch Index State Management policies."""

    def __init__(self):
        self.policies = {}
        self.indices = OrderedDict()  # name -> Index, maintains insertion order
        self.aliases = {}  # alias_name -> index_name
        self.deleted_indices = []

    def load_policies(self, policies_dir):
        """Load all ISM policy JSON files from a directory."""
        policies_path = Path(policies_dir)
        for policy_file in sorted(policies_path.glob("*.json")):
            with open(policy_file) as f:
                data = json.load(f)
            policy = data["policy"]
            self.policies[policy["policy_id"]] = policy

    def get_state_def(self, policy_id, state_name):
        """Look up a state definition within a policy."""
        policy = self.policies[policy_id]
        for state in policy["states"]:
            if state["name"] == state_name:
                return state
        raise ValueError(f"State '{state_name}' not found in policy '{policy_id}'")

    def create_index(self, name, policy_id, write_alias, current_time):
        """Create a new index and register it."""
        policy = self.policies[policy_id]
        idx = Index(name, current_time, policy_id, write_alias)
        idx.state = policy["default_state"]
        self.indices[name] = idx
        if write_alias:
            self.aliases[write_alias] = name

    def ingest(self, target_alias, doc_count, size_bytes):
        """Ingest documents into the index currently pointed to by an alias."""
        if target_alias not in self.aliases:
            raise ValueError(f"Unknown alias: {target_alias}")
        target_index = self.aliases[target_alias]
        if target_index not in self.indices:
            raise ValueError(f"Alias '{target_alias}' points to deleted index '{target_index}'")
        idx = self.indices[target_index]
        idx.doc_count += doc_count
        idx.size_bytes += size_bytes

    def execute_state_actions(self, idx, state_def, exclude_rollover=True):
        """Execute non-rollover actions for a state."""
        for action in state_def.get("actions", []):
            if "rollover" in action and exclude_rollover:
                continue
            if "replica_count" in action:
                idx.replicas = action["replica_count"]["number_of_replicas"]
            elif "read_only" in action:
                idx.read_only = True
            elif "delete" in action:
                return "delete"
        return None

    def evaluate_ism(self, current_time):
        """Evaluate ISM policies for all indices at the current time."""
        # Take a snapshot of index names to iterate (new indices from rollover
        # are appended to self.indices but we skip them via the newly_created set)
        index_names_snapshot = list(self.indices.keys())
        newly_created = set()

        for idx_name in index_names_snapshot:
            if idx_name in newly_created:
                continue
            if idx_name not in self.indices:
                continue  # Deleted during this tick

            idx = self.indices[idx_name]
            state_def = self.get_state_def(idx.policy_id, idx.state)
            index_age = idx.age_at(current_time)

            # Step 1: Check rollover if present and not yet done
            has_rollover_action = False
            for action in state_def.get("actions", []):
                if "rollover" in action:
                    has_rollover_action = True
                    if not idx.rollover_done:
                        rollover_cfg = action["rollover"]
                        triggered = False

                        if "min_doc_count" in rollover_cfg:
                            if idx.doc_count >= rollover_cfg["min_doc_count"]:
                                triggered = True
                        if "min_index_age" in rollover_cfg:
                            if index_age >= parse_duration(rollover_cfg["min_index_age"]):
                                triggered = True

                        if triggered:
                            new_name = increment_index_name(idx.name)
                            alias = idx.write_alias

                            idx.rollover_done = True
                            idx.rollover_at = current_time
                            idx.write_alias = None

                            self.create_index(new_name, idx.policy_id, alias, current_time)
                            newly_created.add(new_name)
                    break  # Only one rollover action per state

            # Step 2: If rollover action exists but hasn't completed, skip transitions
            if has_rollover_action and not idx.rollover_done:
                continue

            # Step 3: Evaluate transitions (first matching wins)
            for transition in state_def.get("transitions", []):
                conditions = transition.get("conditions", {})
                conditions_met = True

                if "min_index_age" in conditions:
                    required_age = parse_duration(conditions["min_index_age"])
                    if index_age < required_age:
                        conditions_met = False

                if conditions_met:
                    new_state_name = transition["state_name"]
                    idx.state = new_state_name

                    new_state_def = self.get_state_def(idx.policy_id, new_state_name)
                    result = self.execute_state_actions(idx, new_state_def)

                    if result == "delete":
                        del self.indices[idx_name]
                        self.deleted_indices.append(idx_name)

                    break  # Only first matching transition

    def run_simulation(self, simulation_path, output_path):
        """Run the full simulation and write the report."""
        with open(simulation_path) as f:
            sim = json.load(f)

        # Group events by timestamp
        events_by_time = {}
        for event in sim["events"]:
            t = event["time"]
            if t not in events_by_time:
                events_by_time[t] = []
            events_by_time[t].append(event)

        # Process each timestamp in order
        for time_str in sorted(events_by_time.keys()):
            current_time = parse_timestamp(time_str)

            # Process all events at this timestamp
            for event in events_by_time[time_str]:
                if event["type"] == "create_index":
                    self.create_index(
                        event["index"],
                        event["policy_id"],
                        event.get("write_alias"),
                        current_time,
                    )
                elif event["type"] == "ingest":
                    self.ingest(
                        event["target_alias"],
                        event["doc_count"],
                        event["size_bytes"],
                    )

            # Evaluate ISM for all indices
            self.evaluate_ism(current_time)

        # Build report
        report = {
            "indices": {},
            "deleted_indices": self.deleted_indices,
            "aliases": dict(self.aliases),
        }

        for name, idx in self.indices.items():
            report["indices"][name] = idx.to_dict()

        # Write output
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        return report


def main():
    simulator = ISMSimulator()
    simulator.load_policies("/app/policies")
    report = simulator.run_simulation("/app/simulation.json", "/app/output/report.json")

    # Summary
    print(f"Simulation complete.")
    print(f"  Existing indices: {len(report['indices'])}")
    print(f"  Deleted indices: {len(report['deleted_indices'])}")
    print(f"  Aliases: {report['aliases']}")


if __name__ == "__main__":
    main()
