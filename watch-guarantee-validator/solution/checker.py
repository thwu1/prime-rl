#!/usr/bin/env python3
"""
Non-deterministic linearizability checker for etcd operation histories.

Implements the etcd KV state machine and checks whether recorded operation
histories are linearizable, considering that error responses create
non-deterministic forks (the operation may or may not have been persisted).

"""

import json
import copy
import glob
import os


def make_state():
    """Create initial etcd state: revision=1, empty KV store."""
    return {"revision": 1, "kv": {}}


def apply_op(state, request):
    """
    Apply an operation to the state machine.
    Returns (new_state, expected_response).
    """
    state = copy.deepcopy(state)
    rtype = request["type"]

    if rtype == "put":
        state["revision"] += 1
        state["kv"][request["key"]] = {
            "value": request["value"],
            "mod_revision": state["revision"],
        }
        return state, {"type": "put", "revision": state["revision"]}

    elif rtype == "get":
        key = request["key"]
        if key in state["kv"]:
            return state, {
                "type": "get",
                "revision": state["revision"],
                "value": state["kv"][key]["value"],
                "count": 1,
            }
        else:
            return state, {
                "type": "get",
                "revision": state["revision"],
                "value": None,
                "count": 0,
            }

    elif rtype == "delete":
        key = request["key"]
        if key in state["kv"]:
            del state["kv"][key]
            state["revision"] += 1
            return state, {
                "type": "delete",
                "revision": state["revision"],
                "deleted": 1,
            }
        else:
            return state, {
                "type": "delete",
                "revision": state["revision"],
                "deleted": 0,
            }

    elif rtype == "txn":
        conditions = request.get("conditions", [])
        on_success = request.get("on_success", [])
        on_failure = request.get("on_failure", [])

        # Evaluate conditions
        succeeded = True
        for cond in conditions:
            key = cond["key"]
            expected_mod_rev = cond.get("expected_mod_revision", 0)
            actual_mod_rev = 0
            if key in state["kv"]:
                actual_mod_rev = state["kv"][key].get("mod_revision", 0)
            if actual_mod_rev != expected_mod_rev:
                succeeded = False
                break

        ops = on_success if succeeded else on_failure

        # Determine if any write will modify state
        will_increase = False
        for op in ops:
            if op["type"] == "put":
                will_increase = True
                break
            elif op["type"] == "delete" and op["key"] in state["kv"]:
                will_increase = True
                break

        if will_increase:
            state["revision"] += 1

        new_rev = state["revision"]
        results = []

        for op in ops:
            if op["type"] == "put":
                state["kv"][op["key"]] = {
                    "value": op["value"],
                    "mod_revision": new_rev,
                }
                results.append({"type": "put"})
            elif op["type"] == "get":
                key = op["key"]
                if key in state["kv"]:
                    results.append({
                        "type": "get",
                        "value": state["kv"][key]["value"],
                        "count": 1,
                    })
                else:
                    results.append({"type": "get", "value": None, "count": 0})
            elif op["type"] == "delete":
                key = op["key"]
                if key in state["kv"]:
                    del state["kv"][key]
                    results.append({"type": "delete", "deleted": 1})
                else:
                    results.append({"type": "delete", "deleted": 0})

        return state, {
            "type": "txn",
            "revision": new_rev,
            "succeeded": succeeded,
            "results": results,
        }

    raise ValueError(f"Unknown request type: {rtype}")


def response_matches(actual, expected):
    """Check if actual response matches expected model response."""
    if actual.get("type") != expected.get("type"):
        return False

    rtype = actual["type"]

    if rtype == "put":
        return actual.get("revision") == expected.get("revision")

    elif rtype == "get":
        return (
            actual.get("revision") == expected.get("revision")
            and actual.get("value") == expected.get("value")
            and actual.get("count") == expected.get("count")
        )

    elif rtype == "delete":
        return (
            actual.get("revision") == expected.get("revision")
            and actual.get("deleted") == expected.get("deleted")
        )

    elif rtype == "txn":
        if actual.get("revision") != expected.get("revision"):
            return False
        if actual.get("succeeded") != expected.get("succeeded"):
            return False
        actual_results = actual.get("results", [])
        expected_results = expected.get("results", [])
        if len(actual_results) != len(expected_results):
            return False
        for ar, er in zip(actual_results, expected_results):
            if ar.get("type") != er.get("type"):
                return False
            if ar.get("type") == "delete":
                if ar.get("deleted") != er.get("deleted"):
                    return False
            if ar.get("type") == "get":
                if ar.get("value") != er.get("value"):
                    return False
                if ar.get("count") != er.get("count"):
                    return False
        return True

    return False


def is_error_response(response):
    """Check if response is an error (unknown outcome)."""
    return bool(response.get("error"))


def check_linearizable(operations):
    """
    Check if operations form a linearizable history under the non-deterministic model.

    Returns (is_linearizable, final_state_or_None).
    Uses backtracking search over all valid orderings and error-branch combinations.
    """
    n = len(operations)
    final_states = []

    def can_place(i, placed_set):
        """Check if all real-time predecessors of op i are already placed."""
        for j in range(n):
            if j == i or j in placed_set:
                continue
            # j must precede i (j completes before i starts) but isn't placed yet
            if operations[j]["return_ns"] <= operations[i]["call_ns"]:
                return False
        return True

    def backtrack(placed_set, state):
        if len(placed_set) == n:
            final_states.append(copy.deepcopy(state))
            return True

        for i in range(n):
            if i in placed_set:
                continue
            if not can_place(i, placed_set):
                continue

            op = operations[i]
            resp = op["response"]
            new_placed = placed_set | frozenset([i])

            if is_error_response(resp):
                # Branch A: operation was persisted (applied)
                new_state, _ = apply_op(state, op["request"])
                if backtrack(new_placed, new_state):
                    return True
                # Branch B: operation was lost (not applied)
                if backtrack(new_placed, copy.deepcopy(state)):
                    return True
            else:
                # Deterministic: response must match model
                new_state, expected = apply_op(state, op["request"])
                if response_matches(resp, expected):
                    if backtrack(new_placed, new_state):
                        return True

        return False

    result = backtrack(frozenset(), make_state())
    if result and final_states:
        return True, final_states[0]
    return False, None


def find_violating_index(operations):
    """
    Find the 0-based index of the first operation that makes the history
    non-linearizable. Uses incremental prefix checking.
    """
    for end in range(len(operations)):
        prefix = operations[: end + 1]
        is_lin, _ = check_linearizable(prefix)
        if not is_lin:
            return end
    return -1


def analyze_history(filepath):
    """Analyze a single history file."""
    with open(filepath) as f:
        data = json.load(f)

    operations = data["operations"]
    is_lin, final_state = check_linearizable(operations)

    if is_lin:
        final_kv = {}
        if final_state:
            for k, v in final_state["kv"].items():
                final_kv[k] = v["value"]
        return {
            "linearizable": True,
            "violating_op_index": -1,
            "final_kv": final_kv,
        }
    else:
        violating = find_violating_index(operations)
        return {
            "linearizable": False,
            "violating_op_index": violating,
            "final_kv": None,
        }


def main():
    data_dir = "/app/data"
    history_files = sorted(glob.glob(os.path.join(data_dir, "*.json")))

    results = {}
    groundtruth = {}

    for filepath in history_files:
        name = os.path.splitext(os.path.basename(filepath))[0]
        analysis = analyze_history(filepath)

        results[name] = {
            "linearizable": analysis["linearizable"],
            "violating_op_index": analysis["violating_op_index"],
        }

        if analysis["linearizable"] and analysis["final_kv"]:
            groundtruth[name] = analysis["final_kv"]

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Save groundtruth for replay.py to use
    with open("/tmp/groundtruth_kv.json", "w") as f:
        json.dump(groundtruth, f, indent=2)

    print("Linearizability analysis complete.")
    for name, r in sorted(results.items()):
        status = "LINEARIZABLE" if r["linearizable"] else f"VIOLATION at op {r['violating_op_index']}"
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
