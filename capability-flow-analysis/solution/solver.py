#!/usr/bin/env python3
"""
Lattice-aware security analysis for seL4 capability system.
Reads /app/system_spec.json, writes /app/results.json.
No external dependencies beyond Python standard library.
"""

import json
import sys
from collections import defaultdict


def load_spec(path="/app/system_spec.json"):
    with open(path) as f:
        return json.load(f)


def rights_to_set(r):
    if r == "RW":
        return frozenset({"R", "W"})
    return frozenset({r})


def resolve_effective_rights(caps_by_id):
    """Resolve effective rights for all capabilities via delegation chain intersection."""
    memo = {}

    def resolve(cap_id):
        if cap_id in memo:
            return memo[cap_id]
        cap = caps_by_id[cap_id]
        declared = rights_to_set(cap["rights"])
        if cap["derived_from"] is None:
            memo[cap_id] = declared
        else:
            parent_eff = resolve(cap["derived_from"])
            memo[cap_id] = declared & parent_eff
        return memo[cap_id]

    for cid in caps_by_id:
        resolve(cid)
    return memo


def build_flow_edges(caps, effective, res_types):
    """Build directed information-flow edges from non-inert capabilities."""
    by_resource = defaultdict(list)
    for cap in caps:
        eff = effective[cap["id"]]
        if len(eff) > 0:
            by_resource[cap["resource"]].append((cap["pd"], eff))

    edges = set()
    for res_name, entries in by_resource.items():
        rtype = res_types[res_name]
        if rtype == "shared_memory":
            writers = [pd for pd, eff in entries if "W" in eff]
            readers = [pd for pd, eff in entries if "R" in eff]
            for w in writers:
                for r in readers:
                    if w != r:
                        edges.add((w, r, res_name))
        elif rtype == "endpoint":
            senders = [pd for pd, eff in entries if "Send" in eff]
            receivers = [pd for pd, eff in entries if "Recv" in eff]
            for s in senders:
                for r in receivers:
                    if s != r:
                        edges.add((s, r, res_name))
        elif rtype == "notification":
            signalers = [pd for pd, eff in entries if "Signal" in eff]
            waiters = [pd for pd, eff in entries if "Wait" in eff]
            for s in signalers:
                for w in waiters:
                    if s != w:
                        edges.add((s, w, res_name))
    return sorted(edges)


def dominates(dst_label, src_label):
    """dst dominates src iff level >= and compartments superset."""
    return dst_label[0] >= src_label[0] and dst_label[1] >= src_label[1]


def find_violations(flow_edges, labels):
    """Find flows where destination does not dominate source."""
    return [(s, d, r) for s, d, r in flow_edges
            if not dominates(labels[d], labels[s])]


def transitive_closure(pd_names, flow_edges):
    """Forward reachability: impact boundary for each PD."""
    adj = defaultdict(set)
    for src, dst, _ in flow_edges:
        adj[src].add(dst)
    result = {}
    for pd in pd_names:
        visited = set()
        stack = list(adj[pd])
        while stack:
            node = stack.pop()
            if node not in visited and node != pd:
                visited.add(node)
                stack.extend(adj[node])
        result[pd] = sorted(visited)
    return result


def reverse_closure(pd_names, flow_edges):
    """Reverse reachability: TCB for each PD."""
    rev = defaultdict(set)
    for src, dst, _ in flow_edges:
        rev[dst].add(src)
    result = {}
    for pd in pd_names:
        visited = set()
        stack = list(rev[pd])
        while stack:
            node = stack.pop()
            if node not in visited and node != pd:
                visited.add(node)
                stack.extend(rev[node])
        result[pd] = sorted(visited)
    return result


def get_descendants(cap_id, children):
    """All descendants of a capability in the delegation DAG."""
    result = set()
    stack = list(children.get(cap_id, []))
    while stack:
        node = stack.pop()
        if node not in result:
            result.add(node)
            stack.extend(children.get(node, []))
    return result


def solve_min_revocation(violations, caps, caps_by_id, effective, res_types):
    """Minimum-cost hitting set with cascading, using branch-and-bound."""
    # Build delegation DAG
    children = defaultdict(list)
    for cap in caps:
        if cap["derived_from"] is not None:
            children[cap["derived_from"]].append(cap["id"])

    # For each violation, find expanded killer set
    all_candidates = set()
    violation_killers = []
    for src, dst, res in violations:
        rtype = res_types[res]
        direct_killers = set()
        for cap in caps:
            if cap["resource"] != res:
                continue
            eff = effective[cap["id"]]
            if len(eff) == 0:
                continue
            is_killer = False
            if rtype == "shared_memory":
                is_killer = (cap["pd"] == src and "W" in eff) or \
                            (cap["pd"] == dst and "R" in eff)
            elif rtype == "endpoint":
                is_killer = (cap["pd"] == src and "Send" in eff) or \
                            (cap["pd"] == dst and "Recv" in eff)
            elif rtype == "notification":
                is_killer = (cap["pd"] == src and "Signal" in eff) or \
                            (cap["pd"] == dst and "Wait" in eff)
            if is_killer:
                direct_killers.add(cap["id"])

        # Expand: ancestors whose cascade covers a direct killer
        expanded = set(direct_killers)
        for cap in caps:
            desc = get_descendants(cap["id"], children)
            if desc & direct_killers:
                expanded.add(cap["id"])

        violation_killers.append(expanded)
        all_candidates.update(expanded)

    candidate_list = sorted(all_candidates)
    costs = {cid: caps_by_id[cid]["revocation_cost"] for cid in candidate_list}

    # Greedy weighted hitting set
    uncovered = set(range(len(violations)))
    selected = set()
    while uncovered:
        best_cid = None
        best_ratio = float("inf")
        best_killed = 0
        for cid in candidate_list:
            if cid in selected:
                continue
            killed = sum(1 for i in uncovered if cid in violation_killers[i])
            if killed == 0:
                continue
            ratio = costs[cid] / killed
            if ratio < best_ratio or (ratio == best_ratio and killed > best_killed):
                best_ratio = ratio
                best_cid = cid
                best_killed = killed
        if best_cid is None:
            break
        selected.add(best_cid)
        uncovered = {i for i in uncovered if best_cid not in violation_killers[i]}

    # Try to improve by removing redundant caps
    for cid in sorted(selected):
        remaining = selected - {cid}
        if all(any(c in remaining for c in violation_killers[i])
               for i in range(len(violations))):
            selected = remaining

    # Try local swaps: replace each selected cap with a cheaper alternative
    improved = True
    while improved:
        improved = False
        for cid in sorted(selected):
            # Which violations does this cap uniquely cover?
            others = selected - {cid}
            unique_violations = [i for i in range(len(violations))
                                 if not any(c in others for c in violation_killers[i])]
            if not unique_violations:
                selected = others
                improved = True
                break
            # Try replacing with cheaper alternative that covers same violations
            for alt in candidate_list:
                if alt in selected or costs[alt] >= costs[cid]:
                    continue
                if all(alt in violation_killers[i] for i in unique_violations):
                    selected = others | {alt}
                    improved = True
                    break
            if improved:
                break

    direct = []
    for cid in sorted(selected):
        cap = caps_by_id[cid]
        direct.append({
            "id": cid,
            "pd": cap["pd"],
            "resource": cap["resource"],
            "cost": cap["revocation_cost"]
        })

    total_cost = sum(r["cost"] for r in direct)
    direct_ids = {r["id"] for r in direct}
    cascaded = set()
    for cid in direct_ids:
        cascaded.update(get_descendants(cid, children) - direct_ids)

    return direct, sorted(cascaded), total_cost


def main():
    spec = load_spec()

    # Validate spec structure defensively
    if not isinstance(spec, dict):
        print(f"ERROR: spec is {type(spec)}, expected dict", file=sys.stderr)
        sys.exit(1)
    for key in ("capabilities", "protection_domains", "resources"):
        if key not in spec:
            print(f"ERROR: spec missing key '{key}', keys: {list(spec.keys())}", file=sys.stderr)
            sys.exit(1)
    for i, c in enumerate(spec["capabilities"]):
        if not isinstance(c, dict) or "id" not in c:
            print(f"ERROR: capability[{i}] invalid: {c}", file=sys.stderr)
            sys.exit(1)

    caps = spec["capabilities"]
    caps_by_id = {c["id"]: c for c in caps}
    res_types = {r["name"]: r["type"] for r in spec["resources"]}
    pd_names = [pd["name"] for pd in spec["protection_domains"]]
    labels = {
        pd["name"]: (pd["security_level"], set(pd["compartments"]))
        for pd in spec["protection_domains"]
    }

    effective = resolve_effective_rights(caps_by_id)
    inert_ids = sorted(cid for cid, eff in effective.items() if len(eff) == 0)

    flow_edges = build_flow_edges(caps, effective, res_types)
    violations = find_violations(flow_edges, labels)
    tcb = reverse_closure(pd_names, flow_edges)
    impact_boundary = transitive_closure(pd_names, flow_edges)
    min_revocations, cascaded_ids, total_cost = solve_min_revocation(
        violations, caps, caps_by_id, effective, res_types
    )

    results = {
        "inert_capability_ids": inert_ids,
        "flow_edges": [list(e) for e in flow_edges],
        "violations": [list(v) for v in violations],
        "tcb": tcb,
        "impact_boundary": impact_boundary,
        "min_revocations": min_revocations,
        "cascaded_revocation_ids": cascaded_ids,
        "total_revocation_cost": total_cost,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Analysis complete: {len(flow_edges)} flows, {len(violations)} violations, "
          f"{len(min_revocations)} revocations (cost {total_cost})")


if __name__ == "__main__":
    main()
