#!/usr/bin/env python3
"""
OSmosis-model security analyzer for seL4 Microkit system descriptions.
Extended with BLP/Biba MLS analysis, architecture refinement, and attack surface.

"""
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict


def parse_system(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    pds = {}
    memory_regions = {}
    channels = []

    for mr in root.findall("memory_region"):
        memory_regions[mr.get("name")] = {"size": mr.get("size")}

    for pd in root.findall("protection_domain"):
        pd_name = pd.get("name")
        maps = []
        irqs = []
        for m in pd.findall("map"):
            maps.append({"mr": m.get("mr"), "perms": m.get("perms", "r")})
        for irq_el in pd.findall("irq"):
            irqs.append(int(irq_el.get("irq")))
        pds[pd_name] = {
            "priority": int(pd.get("priority", "0")),
            "maps": maps,
            "irqs": irqs,
        }

    for ch in root.findall("channel"):
        ends = ch.findall("end")
        if len(ends) == 2:
            channels.append((ends[0].get("pd"), ends[1].get("pd")))

    return pds, memory_regions, channels


def build_graph(pds, memory_regions, channels):
    resource_access = defaultdict(list)

    for pd_name, info in pds.items():
        for m in info["maps"]:
            resource_access[m["mr"]].append((pd_name, m["perms"]))

    for pd1, pd2 in channels:
        ch_name = "channel_" + "_".join(sorted([pd1, pd2]))
        resource_access[ch_name].append((pd1, "rw"))
        resource_access[ch_name].append((pd2, "rw"))

    direct_flows = defaultdict(set)
    flow_resources = defaultdict(set)
    for resource, accessors in resource_access.items():
        writers = [pd for pd, perms in accessors if "w" in perms]
        readers = [pd for pd, perms in accessors if "r" in perms]
        for w in writers:
            for r in readers:
                if w != r:
                    direct_flows[w].add(r)
                    flow_resources[(w, r)].add(resource)

    pd_resources = defaultdict(set)
    pd_resource_perms = defaultdict(dict)
    for resource, accessors in resource_access.items():
        for pd, perms in accessors:
            pd_resources[pd].add(resource)
            if resource in pd_resource_perms[pd]:
                existing = pd_resource_perms[pd][resource]
                combined = set(existing) | set(perms)
                pd_resource_perms[pd][resource] = "".join(sorted(combined))
            else:
                pd_resource_perms[pd][resource] = perms

    return direct_flows, pd_resources, flow_resources, pd_resource_perms


def compute_tcb(pds, direct_flows):
    reverse_flows = defaultdict(set)
    for src, targets in direct_flows.items():
        for tgt in targets:
            reverse_flows[tgt].add(src)

    tcb = {}
    for pd in pds:
        visited = set()
        queue = []
        for neighbor in reverse_flows.get(pd, set()):
            if neighbor != pd:
                visited.add(neighbor)
                queue.append(neighbor)
        idx = 0
        while idx < len(queue):
            current = queue[idx]
            idx += 1
            for nxt in reverse_flows.get(current, set()):
                if nxt != pd and nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        tcb[pd] = sorted(visited)
    return tcb


def compute_ib(pds, direct_flows):
    ib = {}
    for pd in pds:
        visited = set()
        queue = []
        for neighbor in direct_flows.get(pd, set()):
            if neighbor != pd:
                visited.add(neighbor)
                queue.append(neighbor)
        idx = 0
        while idx < len(queue):
            current = queue[idx]
            idx += 1
            for nxt in direct_flows.get(current, set()):
                if nxt != pd and nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        ib[pd] = sorted(visited)
    return ib


def compute_isolation(pds, pd_resources):
    isolation = {}
    pd_names = sorted(pds.keys())
    for i in range(len(pd_names)):
        for j in range(i + 1, len(pd_names)):
            a, b = pd_names[i], pd_names[j]
            shared = pd_resources[a] & pd_resources[b]
            isolation[f"{a},{b}"] = len(shared)
    return isolation


def compute_mls(pds, direct_flows, flow_resources, labels):
    levels = labels["levels"]
    declassifiers = labels.get("declassifiers", {})

    blp_violations = []
    biba_violations = []

    for src, targets in direct_flows.items():
        for dst in targets:
            resources = sorted(flow_resources[(src, dst)])
            src_sec = levels[src]["secrecy"]
            dst_sec = levels[dst]["secrecy"]
            src_int = levels[src]["integrity"]
            dst_int = levels[dst]["integrity"]

            if src_sec > dst_sec:
                decl_resources = set(declassifiers.get(src, []))
                mediating = set(flow_resources[(src, dst)])
                is_declassified = (
                    src in declassifiers
                    and len(mediating) > 0
                    and mediating.issubset(decl_resources)
                )
                blp_violations.append({
                    "from": src,
                    "to": dst,
                    "resources": resources,
                    "declassified": is_declassified,
                })

            if src_int < dst_int:
                biba_violations.append({
                    "from": src,
                    "to": dst,
                    "resources": resources,
                })

    blp_violations.sort(key=lambda v: (v["from"], v["to"]))
    biba_violations.sort(key=lambda v: (v["from"], v["to"]))

    purged_flows = defaultdict(set)
    declassified_edges = set()
    for v in blp_violations:
        if v["declassified"]:
            declassified_edges.add((v["from"], v["to"]))

    for src, targets in direct_flows.items():
        for dst in targets:
            if (src, dst) not in declassified_edges:
                purged_flows[src].add(dst)

    residual_leakage = []
    pd_names = sorted(pds.keys())
    for src_pd in pd_names:
        src_sec = levels[src_pd]["secrecy"]
        visited = set()
        queue = []
        for neighbor in purged_flows.get(src_pd, set()):
            if neighbor != src_pd and neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
        idx = 0
        while idx < len(queue):
            current = queue[idx]
            idx += 1
            for nxt in purged_flows.get(current, set()):
                if nxt != src_pd and nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        for dst_pd in sorted(visited):
            dst_sec = levels[dst_pd]["secrecy"]
            if src_sec > dst_sec:
                residual_leakage.append([src_pd, dst_pd])

    return {
        "blp_violations": blp_violations,
        "biba_violations": biba_violations,
        "residual_leakage": residual_leakage,
    }


def compute_refinement(pds, direct_flows, labels, architecture):
    domains = labels["domains"]
    allowed = set()
    for pair in architecture["allowed_flows"]:
        allowed.add((pair[0], pair[1]))

    violations = []
    for src, targets in direct_flows.items():
        for dst in targets:
            src_dom = domains[src]
            dst_dom = domains[dst]
            if src_dom != dst_dom and (src_dom, dst_dom) not in allowed:
                violations.append({
                    "from": src,
                    "to": dst,
                    "from_domain": src_dom,
                    "to_domain": dst_dom,
                })

    violations.sort(key=lambda v: (v["from"], v["to"]))
    return violations


def compute_attack_surface(pds, pd_resources, pd_resource_perms, tcb):
    scores = {}
    for pd in pds:
        weight_sum = 0
        for resource in pd_resources[pd]:
            if resource.startswith("channel_"):
                weight_sum += 3
            else:
                perms = pd_resource_perms[pd].get(resource, "")
                if "r" in perms and "w" in perms:
                    weight_sum += 2
                else:
                    weight_sum += 1
        scores[pd] = weight_sum * (len(tcb[pd]) + 1)
    return scores


def check_policies(policy_path, tcb, isolation, direct_flows,
                   flow_resources, labels, architecture):
    with open(policy_path) as f:
        policies = json.load(f)

    levels = labels["levels"]
    declassifiers = labels.get("declassifiers", {})
    domains = labels["domains"]
    allowed_flows = set()
    for pair in architecture["allowed_flows"]:
        allowed_flows.add((pair[0], pair[1]))

    results = []
    for policy in policies:
        ptype = policy["type"]

        if ptype == "max_tcb_size":
            domain = policy["domain"]
            max_size = policy["max_size"]
            results.append("pass" if len(tcb.get(domain, [])) <= max_size else "fail")

        elif ptype == "no_flow":
            src, dst = policy["from"], policy["to"]
            visited = {src}
            queue = [src]
            found = False
            while queue:
                current = queue.pop(0)
                if current == dst:
                    found = True
                    break
                for nxt in direct_flows.get(current, set()):
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            results.append("fail" if found else "pass")

        elif ptype == "required_isolation":
            a, b = policy["domain_a"], policy["domain_b"]
            key = ",".join(sorted([a, b]))
            results.append("pass" if isolation.get(key, 0) == 0 else "fail")

        elif ptype == "blp_compliant":
            pd = policy["domain"]
            has_violation = False
            for src, targets in direct_flows.items():
                if pd in targets:
                    if levels[src]["secrecy"] > levels[pd]["secrecy"]:
                        mediating = set(flow_resources[(src, pd)])
                        decl_set = set(declassifiers.get(src, []))
                        if not (src in declassifiers and mediating.issubset(decl_set)):
                            has_violation = True
                            break
            results.append("fail" if has_violation else "pass")

        elif ptype == "biba_compliant":
            pd = policy["domain"]
            has_violation = False
            for src, targets in direct_flows.items():
                if pd in targets:
                    if levels[src]["integrity"] < levels[pd]["integrity"]:
                        has_violation = True
                        break
            results.append("fail" if has_violation else "pass")

        elif ptype == "arch_compliant":
            pd = policy["domain"]
            pd_dom = domains[pd]
            has_violation = False
            for src, targets in direct_flows.items():
                for dst in targets:
                    if src == pd or dst == pd:
                        src_dom = domains[src]
                        dst_dom = domains[dst]
                        if src_dom != dst_dom and (src_dom, dst_dom) not in allowed_flows:
                            has_violation = True
                            break
                if has_violation:
                    break
            results.append("fail" if has_violation else "pass")

    return results


def generate_dot(system_name, pds, flow_resources):
    lines = [f"digraph {system_name} {{"]
    lines.append("    rankdir=LR;")
    lines.append("    node [shape=box];")
    for pd in sorted(pds):
        lines.append(f"    {pd};")
    for (src, dst) in sorted(flow_resources.keys()):
        resources = ", ".join(sorted(flow_resources[(src, dst)]))
        lines.append(f'    {src} -> {dst} [label="{resources}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def analyze_system(system_xml, policy_json, labels_json, arch_json):
    pds, memory_regions, channels = parse_system(system_xml)
    direct_flows, pd_resources, flow_resources, pd_resource_perms = build_graph(
        pds, memory_regions, channels
    )

    with open(labels_json) as f:
        labels = json.load(f)
    with open(arch_json) as f:
        architecture = json.load(f)

    tcb = compute_tcb(pds, direct_flows)
    ib = compute_ib(pds, direct_flows)
    isolation = compute_isolation(pds, pd_resources)
    mls = compute_mls(pds, direct_flows, flow_resources, labels)
    refinement = compute_refinement(pds, direct_flows, labels, architecture)
    attack_surface = compute_attack_surface(pds, pd_resources, pd_resource_perms, tcb)
    policy_results = check_policies(
        policy_json, tcb, isolation, direct_flows,
        flow_resources, labels, architecture
    )

    analysis = {
        "tcb": tcb,
        "impact_boundary": ib,
        "isolation_degree": isolation,
        "mls": mls,
        "refinement_violations": refinement,
        "attack_surface": attack_surface,
        "policy_results": policy_results,
    }
    return analysis, pds, flow_resources


def main():
    systems_dir = "/app/systems"
    policies_dir = "/app/policies"
    labels_dir = "/app/labels"
    arch_dir = "/app/architectures"
    output_dir = "/app/output"
    output_path = os.path.join(output_dir, "analysis.json")

    os.makedirs(output_dir, exist_ok=True)

    results = {}
    for xml_file in sorted(os.listdir(systems_dir)):
        if xml_file.endswith(".xml"):
            name = xml_file[:-4]
            policy_path = os.path.join(policies_dir, f"{name}_policy.json")
            labels_path = os.path.join(labels_dir, f"{name}_labels.json")
            arch_path = os.path.join(arch_dir, f"{name}_arch.json")
            if all(os.path.exists(p) for p in [policy_path, labels_path, arch_path]):
                analysis, pds, flow_resources = analyze_system(
                    os.path.join(systems_dir, xml_file),
                    policy_path, labels_path, arch_path
                )
                results[name] = analysis

                dot_content = generate_dot(name, pds, flow_resources)
                dot_path = os.path.join(output_dir, f"{name}_flow.dot")
                with open(dot_path, "w") as f:
                    f.write(dot_content)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
