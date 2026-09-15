#!/usr/bin/env python3

"""
seL4 Access Control Authority Graph Analyzer

Implements the seL4 capability-based access control semantics from the formal
specification (Access.thy in the l4v repository) to compute the complete
authority graph from a system state description.
"""

import json
import os
from collections import defaultdict

ALL_AUTH = frozenset([
    "Reset", "Receive", "SyncSend", "Notify", "Grant",
    "Call", "Reply", "Control", "DeleteDerived", "Write"
])


def cap_rights_to_auth(rights, is_sync):
    result = {"Reset"}
    if "AllowRead" in rights:
        result.add("Receive")
    if "AllowWrite" in rights:
        result.add("SyncSend" if is_sync else "Notify")
    if "AllowGrant" in rights:
        result = set(ALL_AUTH)
    if "AllowGrantReply" in rights and "AllowWrite" in rights:
        result.add("Call")
    return result


def reply_cap_rights_to_auth(is_master, rights):
    if "AllowGrant" in rights or is_master:
        return set(ALL_AUTH)
    else:
        return {"Reply"}


def cap_auth_conferred(cap):
    cap_type = cap["type"]
    if cap_type == "NullCap":
        return set()
    elif cap_type == "EndpointCap":
        return cap_rights_to_auth(cap["rights"], is_sync=True)
    elif cap_type == "NotificationCap":
        stripped_rights = [r for r in cap["rights"]
                          if r not in ("AllowGrant", "AllowGrantReply")]
        return cap_rights_to_auth(stripped_rights, is_sync=False)
    elif cap_type == "ReplyCap":
        return reply_cap_rights_to_auth(cap["master"], cap["rights"])
    elif cap_type in ("CNodeCap", "ThreadCap", "UntypedCap",
                       "DomainCap", "IRQControlCap", "IRQHandlerCap", "Zombie"):
        return {"Control"}
    else:
        return set()


def obj_refs_ac(cap):
    cap_type = cap["type"]
    if cap_type in ("EndpointCap", "NotificationCap", "ReplyCap",
                     "CNodeCap", "ThreadCap", "Zombie"):
        return {cap["object"]}
    elif cap_type == "UntypedCap":
        return set()
    elif cap_type in ("NullCap", "IRQControlCap", "IRQHandlerCap"):
        return set()
    elif cap_type == "DomainCap":
        return "UNIV"
    else:
        return set()


def tcb_st_to_auth(thread_state):
    state = thread_state["state"]
    if state == "BlockedOnNotification":
        ntfn = thread_state["notification"]
        return {(ntfn, "Receive")}
    elif state == "BlockedOnSend":
        ep = thread_state["endpoint"]
        result = {(ep, "SyncSend")}
        if thread_state.get("can_grant", False):
            result.add((ep, "Grant"))
            result.add((ep, "Call"))
        if thread_state.get("can_grant_reply", False):
            result.add((ep, "Call"))
        return result
    elif state == "BlockedOnReceive":
        ep = thread_state["endpoint"]
        result = {(ep, "Receive")}
        if thread_state.get("can_grant", False):
            result.add((ep, "Grant"))
        return result
    else:
        return set()


def is_transferable(cap):
    if cap is None:
        return True
    cap_type = cap["type"]
    if cap_type == "NullCap":
        return True
    if cap_type == "ReplyCap" and not cap.get("master", False):
        return True
    return False


def find_cap_at_slot(capabilities, obj_name, slot_idx):
    for cap_entry in capabilities:
        if cap_entry["holder"] == obj_name and cap_entry["slot"] == slot_idx:
            return cap_entry["cap"]
    return None


def compute_state_objs_to_policy(state):
    object_labels = state["object_labels"]
    capabilities = state["capabilities"]
    thread_states = state["thread_states"]
    bound_ntfns = state.get("bound_notifications", {})
    cdt = state.get("cdt", [])

    policy = defaultdict(lambda: defaultdict(set))

    # sbta_caps
    for cap_entry in capabilities:
        holder = cap_entry["holder"]
        cap = cap_entry["cap"]
        holder_label = object_labels[holder]
        refs = obj_refs_ac(cap)
        auths = cap_auth_conferred(cap)
        if refs == "UNIV":
            for label in set(object_labels.values()):
                for auth in auths:
                    policy[holder_label][label].add(auth)
        else:
            for ref in refs:
                ref_label = object_labels[ref]
                for auth in auths:
                    policy[holder_label][ref_label].add(auth)

    # sbta_ts
    for tcb_name, ts in thread_states.items():
        tcb_label = object_labels[tcb_name]
        for obj_ref, auth in tcb_st_to_auth(ts):
            ref_label = object_labels[obj_ref]
            policy[tcb_label][ref_label].add(auth)

    # sbta_bounds
    for tcb_name, ntfn_name in bound_ntfns.items():
        tcb_label = object_labels[tcb_name]
        ntfn_label = object_labels[ntfn_name]
        policy[tcb_label][ntfn_label].add("Receive")
        policy[tcb_label][ntfn_label].add("Reset")

    # sbta_cdt and sbta_cdt_transferable
    for cdt_entry in cdt:
        parent_obj = cdt_entry["parent"]["object"]
        child_obj = cdt_entry["child"]["object"]
        child_slot = cdt_entry["child"]["slot"]

        parent_label = object_labels[parent_obj]
        child_label = object_labels[child_obj]

        child_cap = find_cap_at_slot(capabilities, child_obj, child_slot)

        policy[parent_label][child_label].add("DeleteDerived")

        if not is_transferable(child_cap):
            policy[parent_label][child_label].add("Control")

    return policy


def apply_wellformedness_closure(policy, pas_subject, may_send_irqs, irq_labels):
    all_labels = set()
    for src in list(policy.keys()):
        all_labels.add(src)
        for dst in list(policy[src].keys()):
            all_labels.add(dst)
    all_labels.add(pas_subject)

    for auth in ALL_AUTH:
        policy[pas_subject][pas_subject].add(auth)

    changed = True
    while changed:
        changed = False

        for ep in list(all_labels):
            granters = [s for s in all_labels if "Grant" in policy[s].get(ep, set())]
            receivers = [r for r in all_labels if "Receive" in policy[r].get(ep, set())]
            for s in granters:
                for r in receivers:
                    if "Control" not in policy[s].get(r, set()):
                        policy[s][r].add("Control")
                        changed = True
                    if "Control" not in policy[r].get(s, set()):
                        policy[r][s].add("Control")
                        changed = True

        for s in list(all_labels):
            for ep in list(all_labels):
                if "Call" in policy[s].get(ep, set()):
                    if "SyncSend" not in policy[s].get(ep, set()):
                        policy[s][ep].add("SyncSend")
                        changed = True

        for ep in list(all_labels):
            callers = [s for s in all_labels if "Call" in policy[s].get(ep, set())]
            receivers = [r for r in all_labels if "Receive" in policy[r].get(ep, set())]
            for s in callers:
                for r in receivers:
                    if "Reply" not in policy[r].get(s, set()):
                        policy[r][s].add("Reply")
                        changed = True

        for s in list(all_labels):
            for r in list(all_labels):
                if "Reply" in policy[s].get(r, set()):
                    if "DeleteDerived" not in policy[r].get(s, set()):
                        policy[r][s].add("DeleteDerived")
                        changed = True

        for l1 in list(all_labels):
            dd_targets = [l2 for l2 in all_labels
                          if "DeleteDerived" in policy[l1].get(l2, set())]
            for l2 in dd_targets:
                dd_targets2 = [l3 for l3 in all_labels
                               if "DeleteDerived" in policy[l2].get(l3, set())]
                for l3 in dd_targets2:
                    if "DeleteDerived" not in policy[l1].get(l3, set()):
                        policy[l1][l3].add("DeleteDerived")
                        changed = True

        for ep in list(all_labels):
            callers = [s for s in all_labels if "Call" in policy[s].get(ep, set())]
            recv_grant = [r for r in all_labels
                          if "Receive" in policy[r].get(ep, set())
                          and "Grant" in policy[r].get(ep, set())]
            for s in callers:
                for r in recv_grant:
                    if "Control" not in policy[s].get(r, set()):
                        policy[s][r].add("Control")
                        changed = True
                    if "Control" not in policy[r].get(s, set()):
                        policy[r][s].add("Control")
                        changed = True

    return policy


def check_wellformed_rule1(policy, pas_subject):
    for dst, auths in policy.get(pas_subject, {}).items():
        if dst != pas_subject and "Control" in auths:
            return False
    return True


def dd_reachable(policy, src, dst):
    visited = set()
    queue = [src]
    while queue:
        current = queue.pop(0)
        if current == dst:
            return True
        if current in visited:
            continue
        visited.add(current)
        for target, auths in policy.get(current, {}).items():
            if "DeleteDerived" in auths and target not in visited:
                queue.append(target)
    return False


def answer_queries(policy, queries):
    results = {}
    for qid, query in queries.items():
        qtype = query["type"]
        if qtype == "authority_set":
            src = query["from"]
            dst = query["to"]
            auths = sorted(policy.get(src, {}).get(dst, set()))
            results[qid] = auths
        elif qtype == "who_has_auth":
            auth = query["auth"]
            target = query["to"]
            subjects = sorted([
                src for src in policy
                if auth in policy[src].get(target, set())
            ])
            results[qid] = subjects
        elif qtype == "wellformed_check":
            results[qid] = check_wellformed_rule1(
                policy, "subj_A"
            )
        elif qtype == "dd_reachable":
            results[qid] = dd_reachable(policy, query["from"], query["to"])
    return results


def format_authority_graph(policy):
    graph = {}
    for src in sorted(policy.keys()):
        src_edges = {}
        for dst in sorted(policy[src].keys()):
            auths = sorted(policy[src][dst])
            if auths:
                src_edges[dst] = auths
        if src_edges:
            graph[src] = src_edges
    return graph


def write_dot(graph, filepath):
    """Write authority graph as Graphviz DOT."""
    with open(filepath, "w") as f:
        f.write("digraph authority {\n")
        f.write("  rankdir=LR;\n")
        f.write("  node [shape=box, style=filled, fillcolor=lightblue];\n\n")

        nodes = set()
        for src in graph:
            nodes.add(src)
            for dst in graph[src]:
                nodes.add(dst)
        for node in sorted(nodes):
            f.write(f'  {node} [label="{node}"];\n')
        f.write("\n")

        for src in sorted(graph.keys()):
            for dst in sorted(graph[src].keys()):
                auths = graph[src][dst]
                if auths:
                    label = "\\n".join(auths)
                    f.write(f'  {src} -> {dst} [label="{label}"];\n')

        f.write("}\n")


def main():
    with open("/app/system_state.json") as f:
        state = json.load(f)

    pas_subject = state["pas_subject"]
    may_send_irqs = state.get("may_send_irqs", False)
    irq_labels = state.get("irq_labels", {})

    policy = compute_state_objs_to_policy(state)
    policy = apply_wellformedness_closure(
        policy, pas_subject, may_send_irqs, irq_labels
    )
    query_results = answer_queries(policy, state.get("queries", {}))

    graph = format_authority_graph(policy)
    output = {
        "authority_graph": graph,
        "query_results": query_results,
    }

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/authority_graph.json", "w") as f:
        json.dump(output, f, indent=2)

    write_dot(graph, "/app/output/authority.dot")

    print("Authority graph computed and written to /app/output/")


if __name__ == "__main__":
    main()
