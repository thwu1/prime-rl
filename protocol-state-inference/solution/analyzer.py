#!/usr/bin/env python3
"""
Protocol Fuzzing Campaign Forensic Analysis Tool.

Infers protocol behavioral models from fuzzing interaction traces,
computes minimal equivalent models, performs coverage analysis,
statistical fuzzer comparison, and anomaly detection.
"""
import json
import os
import glob
import subprocess
from collections import defaultdict


def load_traces(directory):
    """Load all JSON trace files from a directory, sorted by filename."""
    traces = []
    for filepath in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(filepath) as f:
            traces.append(json.load(f))
    return traces


def infer_state_machine(traces):
    """Infer protocol behavioral model from interaction traces."""
    states = set()
    states.add("INITIAL")
    transitions = set()

    for trace in traces:
        current_state = "INITIAL"
        for interaction in trace["interactions"]:
            req = interaction["request"]
            resp = str(interaction["response_code"])
            states.add(resp)
            transitions.add((current_state, req, resp))
            current_state = resp

    states_with_outgoing = set(t[0] for t in transitions)
    terminal_states = sorted(s for s in states if s not in states_with_outgoing)

    sorted_states = sorted(
        states,
        key=lambda s: (s != "INITIAL", s),
    )

    sorted_transitions = sorted(
        [{"from": f, "request": r, "to": t} for f, r, t in transitions],
        key=lambda x: (x["from"] != "INITIAL", x["from"], x["request"]),
    )

    return {
        "states": sorted_states,
        "initial_state": "INITIAL",
        "transitions": sorted_transitions,
        "terminal_states": terminal_states,
    }


def minimize_state_machine(sm):
    """Compute the minimal equivalent model by collapsing
    behaviorally indistinguishable states."""
    states = set(sm["states"])
    transitions = [(t["from"], t["request"], t["to"]) for t in sm["transitions"]]

    adj = defaultdict(set)
    for f, r, t in transitions:
        adj[f].add((r, t))

    def get_signature(state, state_to_group):
        return frozenset(
            (req, state_to_group.get(tgt, tgt))
            for req, tgt in adj[state]
        )

    sig_to_group = defaultdict(set)
    for s in states:
        sig = frozenset(adj[s])
        sig_to_group[sig].add(s)

    groups = list(sig_to_group.values())

    def build_mapping(groups):
        mapping = {}
        for group in groups:
            rep = min(group)
            for s in group:
                mapping[s] = rep
        return mapping

    for _ in range(100):
        mapping = build_mapping(groups)

        new_sig_to_group = defaultdict(set)
        for s in states:
            sig = get_signature(s, mapping)
            new_sig_to_group[sig].add(s)

        new_groups = list(new_sig_to_group.values())

        if len(new_groups) == len(groups):
            old_sets = {frozenset(g) for g in groups}
            new_sets = {frozenset(g) for g in new_groups}
            if old_sets == new_sets:
                break

        groups = new_groups

    mapping = build_mapping(groups)

    group_dict = defaultdict(set)
    for s in states:
        group_dict[mapping[s]].add(s)

    merge_groups = sorted(
        [
            {
                "representative": rep,
                "members": sorted(members),
            }
            for rep, members in group_dict.items()
        ],
        key=lambda g: g["representative"],
    )

    min_transitions = set()
    for f, r, t in transitions:
        min_f = mapping[f]
        min_t = mapping[t]
        min_transitions.add((min_f, r, min_t))

    sorted_min_transitions = sorted(
        [{"from": f, "request": r, "to": t} for f, r, t in min_transitions],
        key=lambda x: (x["from"] != "INITIAL", x["from"], x["request"]),
    )

    return {
        "num_states": len(groups),
        "num_transitions": len(min_transitions),
        "merge_groups": merge_groups,
        "transitions": sorted_min_transitions,
    }


def write_dot_file(minimized, filepath):
    """Write the minimized model as a Graphviz DOT digraph."""
    reps = sorted([g["representative"] for g in minimized["merge_groups"]])

    # Identify terminal states (no outgoing transitions)
    states_with_outgoing = set(t["from"] for t in minimized["transitions"])
    terminal = [s for s in reps if s not in states_with_outgoing]

    with open(filepath, 'w') as f:
        f.write("digraph minimized_protocol {\n")
        f.write("    rankdir=LR;\n")
        f.write("    node [shape=circle];\n")
        for s in terminal:
            f.write(f'    "{s}" [shape=doublecircle];\n')
        for s in reps:
            if s not in terminal:
                f.write(f'    "{s}";\n')
        for t in minimized["transitions"]:
            f.write(f'    "{t["from"]}" -> "{t["to"]}" [label="{t["request"]}"];\n')
        f.write("}\n")


def compute_session_metrics(trace, all_states, all_transitions):
    """Compute coverage metrics for a single session."""
    visited_states = set()
    visited_states.add("INITIAL")
    exercised_transitions = set()

    current_state = "INITIAL"
    for interaction in trace["interactions"]:
        req = interaction["request"]
        resp = str(interaction["response_code"])
        visited_states.add(resp)
        exercised_transitions.add((current_state, req, resp))
        current_state = resp

    num_states = len(all_states)
    num_transitions = len(all_transitions)

    return {
        "session_id": trace["session_id"],
        "fuzzer": trace.get("fuzzer", "unknown"),
        "states_visited": len(visited_states),
        "transitions_exercised": len(exercised_transitions),
        "state_coverage": round(len(visited_states) / num_states, 4),
        "transition_coverage": round(len(exercised_transitions) / num_transitions, 4),
    }


def vargha_delaney_a12(x, y):
    """Compute A12 effect size: probability that a random observation
    from x exceeds one from y (ties count 0.5)."""
    u = 0.0
    for xi in x:
        for yj in y:
            if xi > yj:
                u += 1.0
            elif xi == yj:
                u += 0.5
    return u / (len(x) * len(y))


def compare_fuzzers(per_session, fuzzer_a, fuzzer_b):
    """Statistical comparison of two fuzzers' coverage distributions."""
    from scipy.stats import mannwhitneyu

    a_state = [s["state_coverage"] for s in per_session if s["fuzzer"] == fuzzer_a]
    b_state = [s["state_coverage"] for s in per_session if s["fuzzer"] == fuzzer_b]
    a_trans = [s["transition_coverage"] for s in per_session if s["fuzzer"] == fuzzer_a]
    b_trans = [s["transition_coverage"] for s in per_session if s["fuzzer"] == fuzzer_b]

    u_state, p_state = mannwhitneyu(a_state, b_state, alternative="two-sided")
    a12_state = vargha_delaney_a12(a_state, b_state)

    sorted_a = sorted(a_state)
    sorted_b = sorted(b_state)
    med_a = (sorted_a[len(sorted_a) // 2 - 1] + sorted_a[len(sorted_a) // 2]) / 2
    med_b = (sorted_b[len(sorted_b) // 2 - 1] + sorted_b[len(sorted_b) // 2]) / 2
    superior_state = fuzzer_a if med_a >= med_b else fuzzer_b

    u_trans, p_trans = mannwhitneyu(a_trans, b_trans, alternative="two-sided")
    a12_trans = vargha_delaney_a12(a_trans, b_trans)

    sorted_at = sorted(a_trans)
    sorted_bt = sorted(b_trans)
    med_at = (sorted_at[len(sorted_at) // 2 - 1] + sorted_at[len(sorted_at) // 2]) / 2
    med_bt = (sorted_bt[len(sorted_bt) // 2 - 1] + sorted_bt[len(sorted_bt) // 2]) / 2
    superior_trans = fuzzer_a if med_at >= med_bt else fuzzer_b

    return {
        "state_coverage": {
            "mann_whitney_u": float(u_state),
            "p_value": float(p_state),
            "a12_effect_size": float(round(a12_state, 4)),
            "superior_fuzzer": superior_state,
        },
        "transition_coverage": {
            "mann_whitney_u": float(u_trans),
            "p_value": float(p_trans),
            "a12_effect_size": float(round(a12_trans, 4)),
            "superior_fuzzer": superior_trans,
        },
    }


def detect_anomalies(test_traces, transition_set):
    """Classify test sessions against the inferred model."""
    valid_transitions = set()
    for f, r, t in transition_set:
        valid_transitions.add((f, r))

    results = []
    for trace in test_traces:
        test_id = trace["session_id"]
        current_state = "INITIAL"
        conforming = True
        anomaly_info = {}

        for i, interaction in enumerate(trace["interactions"]):
            req = interaction["request"]
            resp = str(interaction["response_code"])

            if (current_state, req) not in valid_transitions:
                conforming = False
                anomaly_info = {
                    "first_anomaly_index": i,
                    "anomalous_transition": {
                        "from": current_state,
                        "request": req,
                    },
                }
                break
            current_state = resp

        result = {"test_id": test_id, "conforming": conforming}
        if not conforming:
            result.update(anomaly_info)
        results.append(result)

    return results


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    training_traces = load_traces("/app/traces/training")
    test_traces = load_traces("/app/traces/test")

    sm = infer_state_machine(training_traces)
    minimized = minimize_state_machine(sm)

    all_states = set(sm["states"])
    all_transitions = set(
        (t["from"], t["request"], t["to"]) for t in sm["transitions"]
    )

    per_session = [
        compute_session_metrics(t, all_states, all_transitions)
        for t in training_traces
    ]

    metrics = {
        "num_states": len(all_states),
        "num_transitions": len(all_transitions),
        "num_terminal_states": len(sm["terminal_states"]),
        "per_session": per_session,
    }

    fuzzers = config["fuzzers"]
    comparison = compare_fuzzers(per_session, fuzzers[0], fuzzers[1])
    anomalies = detect_anomalies(test_traces, all_transitions)

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/state_machine.json", "w") as f:
        json.dump(sm, f, indent=2)

    with open("/app/output/minimized_machine.json", "w") as f:
        json.dump(minimized, f, indent=2)

    write_dot_file(minimized, "/app/output/minimized.dot")
    subprocess.run(
        ["dot", "-Tsvg", "/app/output/minimized.dot", "-o", "/app/output/minimized.svg"],
        check=True,
    )

    with open("/app/output/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    with open("/app/output/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)

    with open("/app/output/anomalies.json", "w") as f:
        json.dump(anomalies, f, indent=2)


if __name__ == "__main__":
    main()
