#!/usr/bin/env python3
"""
etcd Watch Guarantee Validator

Validates recorded etcd watch streams against 8 correctness guarantees
using the operation history as ground truth.

"""

import json
import os


def load_scenario(scenario_dir):
    with open(os.path.join(scenario_dir, "operations.json")) as f:
        ops_data = json.load(f)
    with open(os.path.join(scenario_dir, "watch.json")) as f:
        watch_data = json.load(f)
    return ops_data, watch_data


def matches_watch(key, watch_key, is_prefix):
    if is_prefix:
        if watch_key == "":
            return True
        return key.startswith(watch_key)
    return key == watch_key


def get_all_events(watch_data):
    events = []
    for resp in watch_data["responses"]:
        if resp.get("is_progress_notify", False):
            continue
        for event in resp.get("events", []):
            events.append(event)
    return events


def build_key_state_at_revision(ops_data, target_rev):
    """Build the state of all keys immediately before target_rev.

    Returns dict: key -> {"value": ..., "mod_revision": ...}
    Keys not in the dict do not exist at that point.
    """
    state = {}
    for op in ops_data["operations"]:
        if op["revision"] >= target_rev:
            break
        if op["type"] == "put":
            state[op["key"]] = {"value": op["value"], "mod_revision": op["revision"]}
        elif op["type"] == "delete":
            state.pop(op["key"], None)
        elif op["type"] == "txn":
            for sub_op in op["ops"]:
                if sub_op["type"] == "put":
                    state[sub_op["key"]] = {
                        "value": sub_op["value"],
                        "mod_revision": op["revision"],
                    }
                elif sub_op["type"] == "delete":
                    state.pop(sub_op["key"], None)
    return state


def get_expected_events(ops_data, watch_key, is_prefix, start_rev, end_rev):
    """Get all events that should exist for watched key(s) between start_rev and end_rev inclusive."""
    events = []
    for op in ops_data["operations"]:
        rev = op["revision"]
        if rev < start_rev or rev > end_rev:
            continue
        if op["type"] == "put":
            if matches_watch(op["key"], watch_key, is_prefix):
                events.append(("PUT", op["key"], rev))
        elif op["type"] == "delete":
            if matches_watch(op["key"], watch_key, is_prefix):
                events.append(("DELETE", op["key"], rev))
        elif op["type"] == "txn":
            for sub_op in op["ops"]:
                if matches_watch(sub_op["key"], watch_key, is_prefix):
                    events.append((sub_op["type"].upper(), sub_op["key"], rev))
    return events


# ---------------------------------------------------------------------------
# Guarantee validators
# ---------------------------------------------------------------------------

def validate_ordered(watch_data):
    max_rev = -1
    for resp in watch_data["responses"]:
        if resp.get("is_progress_notify", False):
            continue
        for event in resp.get("events", []):
            if event["revision"] < max_rev:
                return False
            max_rev = event["revision"]
    return True


def validate_unique(watch_data):
    seen = set()
    for resp in watch_data["responses"]:
        if resp.get("is_progress_notify", False):
            continue
        for event in resp.get("events", []):
            key_rev = (event["key"], event["revision"])
            if key_rev in seen:
                return False
            seen.add(key_rev)
    return True


def validate_atomic(watch_data):
    revision_resp_idx = {}
    for i, resp in enumerate(watch_data["responses"]):
        if resp.get("is_progress_notify", False):
            continue
        for event in resp.get("events", []):
            rev = event["revision"]
            if rev in revision_resp_idx and revision_resp_idx[rev] != i:
                return False
            revision_resp_idx[rev] = i
    return True


def validate_reliable(ops_data, watch_data):
    events = get_all_events(watch_data)
    if len(events) < 2:
        return True

    first_rev = events[0]["revision"]
    last_rev = events[-1]["revision"]

    watch_key = watch_data["request"]["key"]
    is_prefix = watch_data["request"].get("prefix", False)

    expected = get_expected_events(ops_data, watch_key, is_prefix, first_rev, last_rev)

    received_set = set()
    for e in events:
        received_set.add((e["type"], e["key"], e["revision"]))

    for exp_type, exp_key, exp_rev in expected:
        if (exp_type, exp_key, exp_rev) not in received_set:
            return False

    return True


def validate_resumable(ops_data, watch_data):
    events = get_all_events(watch_data)
    if not events:
        return True

    start_rev = watch_data["request"]["start_revision"]
    watch_key = watch_data["request"]["key"]
    is_prefix = watch_data["request"].get("prefix", False)

    expected_at_start = get_expected_events(ops_data, watch_key, is_prefix, start_rev, start_rev)

    if expected_at_start and events[0]["revision"] != start_rev:
        return False

    return True


def validate_bookmarkable(watch_data):
    max_event_rev = -1
    for resp in watch_data["responses"]:
        if resp.get("is_progress_notify", False):
            notify_rev = resp["watch_revision"]
            if notify_rev < max_event_rev:
                return False
        else:
            for event in resp.get("events", []):
                if event["revision"] > max_event_rev:
                    max_event_rev = event["revision"]
    return True


def validate_is_create(ops_data, watch_data):
    events = get_all_events(watch_data)
    for event in events:
        if event["type"] == "DELETE":
            if event.get("is_create", False):
                return False
            continue

        state = build_key_state_at_revision(ops_data, event["revision"])
        key_existed = event["key"] in state
        expected_is_create = not key_existed

        if event.get("is_create", False) != expected_is_create:
            return False

    return True


def validate_prev_kv(ops_data, watch_data):
    if not watch_data["request"].get("prev_kv", False):
        return True

    events = get_all_events(watch_data)
    for event in events:
        state = build_key_state_at_revision(ops_data, event["revision"])
        expected_prev = state.get(event["key"])

        actual_prev = event.get("prev_kv")

        if expected_prev is None:
            if actual_prev is not None:
                return False
        else:
            if actual_prev is None:
                return False
            if actual_prev.get("value") != expected_prev["value"]:
                return False
            if actual_prev.get("mod_revision") != expected_prev["mod_revision"]:
                return False

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def validate_scenario(scenario_dir):
    ops_data, watch_data = load_scenario(scenario_dir)
    return {
        "ordered": validate_ordered(watch_data),
        "unique": validate_unique(watch_data),
        "atomic": validate_atomic(watch_data),
        "reliable": validate_reliable(ops_data, watch_data),
        "resumable": validate_resumable(ops_data, watch_data),
        "bookmarkable": validate_bookmarkable(watch_data),
        "is_create": validate_is_create(ops_data, watch_data),
        "prev_kv": validate_prev_kv(ops_data, watch_data),
    }


def main():
    data_dir = "/app/data"
    results = {}

    for scenario_name in sorted(os.listdir(data_dir)):
        scenario_dir = os.path.join(data_dir, scenario_name)
        if not os.path.isdir(scenario_dir):
            continue
        results[scenario_name] = validate_scenario(scenario_dir)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
