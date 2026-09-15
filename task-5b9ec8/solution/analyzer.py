#!/usr/bin/env python3
"""
SysML v2 Conformance & Traceability Pipeline

Parses SysML v2 textual model files from /app/model/ and produces
conformance analysis at /app/results/conformance.json and
traceability graph at /app/results/traceability.dot.

"""

import json
import re
import os
import glob


def read_model_files(model_dir):
    content = ""
    for filepath in sorted(glob.glob(os.path.join(model_dir, "*.sysml"))):
        with open(filepath, "r") as f:
            content += f.read() + "\n"
    return content


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    return text


def find_block_end(text, start_after_brace):
    depth = 1
    pos = start_after_brace
    while pos < len(text) and depth > 0:
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
        pos += 1
    return pos


# ======= Type Hierarchy =======


def parse_type_hierarchy(text):
    pattern = r"(?:abstract\s+)?part\s+def\s+(\w+)\s*(?::>\s*(\w+))?\s*\{"
    hierarchy = {}
    for match in re.finditer(pattern, text):
        name = match.group(1)
        parent = match.group(2)
        hierarchy[name] = parent
    return hierarchy


def build_ancestor_chains(hierarchy):
    chains = {}
    for name in hierarchy:
        ancestors = []
        current = hierarchy.get(name)
        while current:
            ancestors.append(current)
            current = hierarchy.get(current)
        chains[name] = ancestors
    return chains


def find_instruments(ancestor_chains):
    instruments = []
    for name, ancestors in ancestor_chains.items():
        if "Instrument" in ancestors:
            instruments.append(name)
    return sorted(instruments)


# ======= Requirements =======


def extract_requirements(text):
    pattern = r"requirement\s+<'(REQ-[A-Z]+-\d+)'>\s+(\w+)"
    reqs = {}
    for req_id, name in re.findall(pattern, text):
        reqs[name] = req_id
    return reqs


def extract_requirement_types(text):
    pattern = r"requirement\s+<'REQ-[A-Z]+-\d+'>\s+(\w+)\s*:\s*(\w+)\s*\{"
    typed_reqs = {}
    for name, req_type in re.findall(pattern, text):
        typed_reqs[name] = req_type
    return typed_reqs


def extract_requirement_constraints(text):
    constraints = {}

    req_pattern = r"requirement\s+<'[^']*'>\s+(\w+)(?:\s*:\s*\w+)?\s*\{"
    for match in re.finditer(req_pattern, text):
        req_name = match.group(1)
        block_end = find_block_end(text, match.end())
        block = text[match.end():block_end - 1]

        redef_pattern = r"attribute\s+redefines\s+(\w+)\s*=\s*(-?[\d.]+)"
        redefined = {}
        for attr, val in re.findall(redef_pattern, block):
            redefined[attr] = float(val)

        constr_pattern = r"require\s+constraint\s*\{([^}]+)\}"
        exprs = []
        for cm in re.finditer(constr_pattern, block):
            exprs.append(cm.group(1).strip())

        constraints[req_name] = {"redefined": redefined, "constraint_exprs": exprs}

    return constraints


def extract_satisfied_requirement_names(text):
    pattern = r"satisfy\s+(\w+)\s+by\s+"
    return set(re.findall(pattern, text))


# ======= Verification Cases =======


def parse_verification_cases(text):
    verif_defs = {}
    verif_usages = {}

    def_pattern = r"verification\s+def\s+(\w+)\s*\{"
    for match in re.finditer(def_pattern, text):
        def_name = match.group(1)
        block_end = find_block_end(text, match.end())
        block = text[match.end():block_end - 1]

        verify_pattern = r"verify\s+(\w+)\s*;"
        verify_match = re.search(verify_pattern, block)
        verified_req = verify_match.group(1) if verify_match else None

        subject_pattern = r"subject\s+(\w+)\s*:\s*(\w+)\s*;"
        subject_match = re.search(subject_pattern, block)
        subject_name = subject_match.group(1) if subject_match else None
        subject_type = subject_match.group(2) if subject_match else None

        verif_defs[def_name] = {
            "verified_req": verified_req,
            "subject_name": subject_name,
            "subject_type": subject_type,
        }

    usage_pattern = r"verification\s+(\w+)\s*:\s*(\w+)\s*\{"
    for match in re.finditer(usage_pattern, text):
        usage_name = match.group(1)
        def_type = match.group(2)

        if usage_name in verif_defs:
            continue

        block_end = find_block_end(text, match.end())
        block = text[match.end():block_end - 1]

        subject_bind_pattern = r"subject\s+\w+\s*=\s*([^;]+)\s*;"
        subject_match = re.search(subject_bind_pattern, block)
        subject_binding = subject_match.group(1).strip() if subject_match else None

        verif_usages[usage_name] = {
            "def_type": def_type,
            "subject_binding": subject_binding,
        }

    return verif_defs, verif_usages


# ======= Architecture Parsing =======


def parse_architecture(text):
    match = re.search(r"part\s+sentinelSat\s*:\s*Subsystem\s*\{", text)
    if not match:
        return {}

    sat_end = find_block_end(text, match.end())
    sat_block = text[match.end():sat_end - 1]

    architecture = {"sentinelSat": {"children": {}, "attrs": {}}}

    attr_pattern = r"attribute\s+redefines\s+(\w+)\s*=\s*(-?[\d.]+)"

    for attr, val in re.findall(attr_pattern, sat_block):
        # Only capture top-level attrs (before first subsystem part)
        first_part = re.search(r"part\s+\w+\s*:", sat_block)
        if first_part:
            attr_pos = sat_block.find(f"attribute redefines {attr}")
            if attr_pos < first_part.start():
                architecture["sentinelSat"]["attrs"][attr] = float(val)

    ss_pattern = r"part\s+(\w+)\s*:\s*(\w+)\s*\{"
    for ss_match in re.finditer(ss_pattern, sat_block):
        ss_name = ss_match.group(1)
        ss_type = ss_match.group(2)
        ss_end = find_block_end(sat_block, ss_match.end())
        ss_block = sat_block[ss_match.end():ss_end - 1]

        subsystem = {"type": ss_type, "children": {}, "attrs": {}}

        # Parse subsystem-level redefined attributes (before first child part)
        first_child = re.search(r"part\s+redefines\s+\w+\s*\{", ss_block)
        for a_match in re.finditer(attr_pattern, ss_block):
            if first_child is None or a_match.start() < first_child.start():
                subsystem["attrs"][a_match.group(1)] = float(a_match.group(2))

        child_pattern = r"part\s+redefines\s+(\w+)\s*\{"
        for child_match in re.finditer(child_pattern, ss_block):
            child_name = child_match.group(1)
            c_end = find_block_end(ss_block, child_match.end())
            c_block = ss_block[child_match.end():c_end - 1]

            child_attrs = {}
            for attr, val in re.findall(attr_pattern, c_block):
                child_attrs[attr] = float(val)

            subsystem["children"][child_name] = child_attrs

        architecture["sentinelSat"]["children"][ss_name] = subsystem

    return architecture


# ======= Attribute Resolution =======


def find_attr_in_subject(architecture, subject_path, attr_name):
    parts = subject_path.split(".")
    if parts[0] != "sentinelSat":
        return None

    node = architecture.get("sentinelSat")
    if node is None:
        return None

    for part in parts[1:]:
        children = node.get("children", {})
        if part in children:
            node = children[part]
        else:
            return None

    # Check node's own attrs
    if isinstance(node, dict):
        if attr_name in node.get("attrs", {}):
            return node["attrs"][attr_name]

        # Search children recursively
        for child_name, child_data in node.get("children", {}).items():
            if isinstance(child_data, dict):
                if attr_name in child_data:
                    return child_data[attr_name]

    return None


def compute_total_mass(architecture, subject_path):
    parts = subject_path.split(".")
    node = architecture.get("sentinelSat")
    if node is None:
        return 0.0

    if len(parts) == 1:
        # Sum all subsystems' children masses
        total = 0.0
        for ss_name, ss_data in node.get("children", {}).items():
            for child_name, child_attrs in ss_data.get("children", {}).items():
                total += child_attrs.get("mass", 0)
        return total
    else:
        for part in parts[1:]:
            children = node.get("children", {})
            if part in children:
                node = children[part]
            else:
                return 0.0

        total = 0.0
        for child_name, child_attrs in node.get("children", {}).items():
            total += child_attrs.get("mass", 0)
        return total


# ======= Actions =======


def extract_mission_actions(text):
    match = re.search(r"action\s+performMission\s*:\s*PerformMission\s*\{", text)
    if not match:
        return {}

    block_end = find_block_end(text, match.end())
    block = text[match.end():block_end - 1]

    pattern = r"(?:then\s+)?action\s+(\w+)\s*:\s*(\w+)\s*;"
    actions = {}
    for usage_name, def_name in re.findall(pattern, block):
        actions[usage_name] = def_name

    return actions


def extract_allocated_action_usages(text):
    pattern = r"allocate\s+performMission\.(\w+)\s+to\s+"
    return set(re.findall(pattern, text))


# ======= Traceability DOT Graph =======


def generate_dot(requirements, satisfied_names, verif_defs, verif_usages,
                 req_name_to_id, actions, allocated_usages,
                 satisfy_targets, allocate_targets):
    lines = [
        "digraph traceability {",
        "    rankdir=LR;",
        "    node [fontsize=10];",
        "",
        "    // Requirements",
    ]

    for req_name, req_id in sorted(req_name_to_id.items(), key=lambda x: x[1]):
        lines.append(f'    "{req_id}" [shape=note, label="{req_id}"];')

    lines.append("")
    lines.append("    // Parts/Subsystems")
    part_nodes = set()
    for target in satisfy_targets.values():
        part_nodes.add(target.split(".")[-1])
    for target in allocate_targets.values():
        part_nodes.add(target.split(".")[-1])

    for part in sorted(part_nodes):
        lines.append(f'    "{part}" [shape=box3d, label="{part}"];')

    lines.append("")
    lines.append("    // Verification Cases")
    for vname in sorted(verif_usages.keys()):
        lines.append(f'    "{vname}" [shape=diamond, label="{vname}"];')

    lines.append("")
    lines.append("    // Satisfy edges (blue)")
    for req_name in sorted(satisfied_names):
        if req_name in req_name_to_id and req_name in satisfy_targets:
            req_id = req_name_to_id[req_name]
            target = satisfy_targets[req_name].split(".")[-1]
            lines.append(f'    "{req_id}" -> "{target}" [color=blue];')

    lines.append("")
    lines.append("    // Verify edges (green)")
    for vname, vdata in sorted(verif_usages.items()):
        def_type = vdata["def_type"]
        if def_type in verif_defs:
            verified_req = verif_defs[def_type]["verified_req"]
            if verified_req in req_name_to_id:
                req_id = req_name_to_id[verified_req]
                lines.append(f'    "{vname}" -> "{req_id}" [color=green];')

    lines.append("")
    lines.append("    // Allocate edges (orange)")
    for usage_name in sorted(allocated_usages):
        if usage_name in actions and usage_name in allocate_targets:
            def_name = actions[usage_name]
            target = allocate_targets[usage_name].split(".")[-1]
            lines.append(f'    "{def_name}" -> "{target}" [color=orange];')

    lines.append("}")
    return "\n".join(lines)


# ======= Main =======


def main():
    model_dir = "/app/model"
    raw_text = read_model_files(model_dir)
    text = strip_comments(raw_text)

    os.makedirs("/app/results", exist_ok=True)

    # --- Type Hierarchy ---
    hierarchy = parse_type_hierarchy(text)
    ancestor_chains = build_ancestor_chains(hierarchy)
    instruments = find_instruments(ancestor_chains)

    # --- Requirements ---
    requirements = extract_requirements(text)
    req_name_to_id = dict(requirements)
    requirement_types = extract_requirement_types(text)
    req_constraints = extract_requirement_constraints(text)
    satisfied_names = extract_satisfied_requirement_names(text)

    orphan_names = set(requirements.keys()) - satisfied_names
    orphan_ids = sorted([requirements[name] for name in orphan_names])

    total_reqs = len(requirements)
    satisfied_count = total_reqs - len(orphan_ids)
    coverage_pct = (
        round(100.0 * satisfied_count / total_reqs, 2) if total_reqs > 0 else 0.0
    )

    # --- Satisfy targets ---
    satisfy_targets = {}
    for m in re.finditer(r"satisfy\s+(\w+)\s+by\s+([^;]+)\s*;", text):
        satisfy_targets[m.group(1)] = m.group(2).strip()

    # --- Verification ---
    verif_defs, verif_usages = parse_verification_cases(text)

    verified_req_names = set()
    for vdef in verif_defs.values():
        if vdef["verified_req"]:
            verified_req_names.add(vdef["verified_req"])

    verified_req_ids = sorted(
        [req_name_to_id[name] for name in verified_req_names if name in req_name_to_id]
    )
    unverified_ids = sorted(
        [rid for rid in req_name_to_id.values() if rid not in verified_req_ids]
    )

    verif_coverage_pct = (
        round(100.0 * len(verified_req_ids) / total_reqs, 2)
        if total_reqs > 0
        else 0.0
    )

    # --- Architecture ---
    architecture = parse_architecture(text)

    # --- Constraint Evaluation ---
    verification_verdicts = []
    for vname in sorted(verif_usages.keys()):
        vusage = verif_usages[vname]
        def_type = vusage["def_type"]
        subject_binding = vusage["subject_binding"]

        if def_type not in verif_defs:
            continue

        vdef = verif_defs[def_type]
        verified_req_name = vdef["verified_req"]

        if not verified_req_name or verified_req_name not in req_name_to_id:
            continue

        req_id = req_name_to_id[verified_req_name]
        req_type = requirement_types.get(verified_req_name)

        verdict = "pass"

        if req_type == "MassRequirement":
            mass_actual = compute_total_mass(architecture, subject_binding)
            mass_limit = None
            if verified_req_name in req_constraints:
                mass_limit = req_constraints[verified_req_name].get(
                    "redefined", {}
                ).get("massLimit")

            if mass_limit is not None and mass_actual > mass_limit:
                verdict = "fail"

        elif req_type == "PowerRequirement":
            power_output = find_attr_in_subject(
                architecture, subject_binding, "powerOutput"
            )
            power_minimum = None
            if verified_req_name in req_constraints:
                power_minimum = req_constraints[verified_req_name].get(
                    "redefined", {}
                ).get("powerMinimum")

            if (
                power_minimum is not None
                and power_output is not None
                and power_output < power_minimum
            ):
                verdict = "fail"

        else:
            # Untyped requirement: evaluate constraint expressions
            req_info = req_constraints.get(verified_req_name, {})
            exprs = req_info.get("constraint_exprs", [])

            for expr in exprs:
                match = re.match(r"(\w+)\s*(<=|>=|==|<|>)\s*(-?[\d.]+)", expr)
                if match:
                    attr_name = match.group(1)
                    operator = match.group(2)
                    threshold = float(match.group(3))

                    actual = find_attr_in_subject(
                        architecture, subject_binding, attr_name
                    )

                    if actual is not None:
                        if operator == "<=" and actual > threshold:
                            verdict = "fail"
                        elif operator == ">=" and actual < threshold:
                            verdict = "fail"
                        elif operator == "==" and actual != threshold:
                            verdict = "fail"
                        elif operator == "<" and actual >= threshold:
                            verdict = "fail"
                        elif operator == ">" and actual <= threshold:
                            verdict = "fail"

        verification_verdicts.append(
            {"case": vname, "requirement_id": req_id, "verdict": verdict}
        )

    # --- Actions ---
    mission_actions = extract_mission_actions(text)
    allocated_usages = extract_allocated_action_usages(text)

    allocate_targets = {}
    for m in re.finditer(r"allocate\s+performMission\.(\w+)\s+to\s+([^;]+)\s*;", text):
        allocate_targets[m.group(1)] = m.group(2).strip()

    unallocated_usage_names = set(mission_actions.keys()) - allocated_usages
    unallocated_def_names = sorted(
        [mission_actions[u] for u in unallocated_usage_names]
    )

    total_actions = len(mission_actions)
    allocated_count = total_actions - len(unallocated_def_names)

    # --- Mass Analysis ---
    arch = architecture.get("sentinelSat", {})
    subsystem_masses = {}
    mass_violations = []

    for ss_name in sorted(arch.get("children", {}).keys()):
        ss = arch["children"][ss_name]
        computed_mass = sum(
            attrs.get("mass", 0) for attrs in ss.get("children", {}).values()
        )
        subsystem_masses[ss_name] = computed_mass

        mass_budget = ss.get("attrs", {}).get("massBudget", 0)
        if computed_mass > mass_budget:
            mass_violations.append(
                {
                    "subsystem": ss_name,
                    "computed_mass": computed_mass,
                    "budget": mass_budget,
                    "overrun": round(computed_mass - mass_budget, 2),
                }
            )

    total_mass = sum(subsystem_masses.values())

    # --- Power Analysis ---
    subsystem_power = {}
    power_violations = []
    total_consumption = 0.0
    total_generation = 0.0

    for ss_name in sorted(arch.get("children", {}).keys()):
        ss = arch["children"][ss_name]
        computed_power = sum(
            attrs.get("powerConsumption", 0)
            for attrs in ss.get("children", {}).values()
        )
        subsystem_power[ss_name] = computed_power
        total_consumption += computed_power

        for child_attrs in ss.get("children", {}).values():
            if "powerOutput" in child_attrs:
                total_generation += child_attrs["powerOutput"]

        power_budget = ss.get("attrs", {}).get("powerBudget", 0)
        if computed_power > power_budget:
            power_violations.append(
                {
                    "subsystem": ss_name,
                    "computed_power": computed_power,
                    "budget": power_budget,
                    "overrun": round(computed_power - power_budget, 2),
                }
            )

    margin = total_generation - total_consumption
    margin_percent = (
        round(100.0 * margin / total_generation, 2) if total_generation > 0 else 0.0
    )

    # --- Build Conformance JSON ---
    conformance = {
        "type_hierarchy": ancestor_chains,
        "instruments": instruments,
        "verification_verdicts": verification_verdicts,
        "orphan_requirements": orphan_ids,
        "unverified_requirements": unverified_ids,
        "mass_analysis": {
            "subsystem_masses": subsystem_masses,
            "total_mass": total_mass,
            "violations": mass_violations,
        },
        "power_analysis": {
            "total_generation": total_generation,
            "total_consumption": total_consumption,
            "margin": margin,
            "margin_percent": margin_percent,
            "subsystem_power": subsystem_power,
            "power_violations": power_violations,
        },
        "requirement_coverage": {
            "total": total_reqs,
            "satisfied": satisfied_count,
            "coverage_percent": coverage_pct,
        },
        "verification_coverage": {
            "total": total_reqs,
            "verified": len(verified_req_ids),
            "coverage_percent": verif_coverage_pct,
        },
        "unallocated_actions": unallocated_def_names,
        "action_allocation": {"total": total_actions, "allocated": allocated_count},
    }

    with open("/app/results/conformance.json", "w") as f:
        json.dump(conformance, f, indent=2)

    # --- Generate Traceability DOT ---
    dot_content = generate_dot(
        requirements,
        satisfied_names,
        verif_defs,
        verif_usages,
        req_name_to_id,
        mission_actions,
        allocated_usages,
        satisfy_targets,
        allocate_targets,
    )

    with open("/app/results/traceability.dot", "w") as f:
        f.write(dot_content)

    print("Conformance analysis complete. Results in /app/results/")


if __name__ == "__main__":
    main()
