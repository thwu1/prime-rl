#!/usr/bin/env python3
"""
Solver for OSPF Remediation Plan Evaluation.
Evaluates two proposed remediation plans, identifies their strengths and
flaws (including issues beyond what the automated validator catches),
creates correct configurations, and writes evaluation and diagnosis reports.
"""

import ipaddress
import json
import os
import re
import sys

sys.path.insert(0, "/app")
from validate import FRRConfigParser, load_topology, validate_configs


def read_file(path):
    with open(path) as f:
        return f.read()


def load_configs(config_dir, topology):
    """Load config files from a directory."""
    configs = {}
    config_texts = {}
    for router_name in topology["routers"]:
        path = os.path.join(config_dir, f"{router_name}.conf")
        text = read_file(path)
        config_texts[router_name] = text
        configs[router_name] = FRRConfigParser(text)
    return configs, config_texts


def check_bogon_filter_present(config_text):
    """Check if BOGON_FILTER prefix-list definition is present."""
    return bool(re.search(
        r"ip prefix-list\s+BOGON_FILTER\s+seq", config_text
    ))


def evaluate_proposal(proposal_dir, orig_configs, orig_texts, topology):
    """Evaluate a proposal by comparing it against originals and checking
    for correctness, completeness, and regressions."""
    configs, texts = load_configs(proposal_dir, topology)

    # Run the automated validator first
    validator_errors = validate_configs(proposal_dir, topology)

    faults_fixed = []
    faults_missed = []
    regressions = []

    protected_subnets = list(topology.get("host_subnets", []))
    if "server_subnet" in topology:
        protected_subnets.append(topology["server_subnet"])

    for router_name in topology["routers"]:
        router_info = topology["routers"][router_name]

        # --- Passive-interface analysis ---
        for iface_name, iface_info in router_info["interfaces"].items():
            if iface_info.get("type") != "transit":
                continue
            orig_passive = orig_configs[router_name].is_interface_passive(
                iface_name
            )
            prop_passive = configs[router_name].is_interface_passive(
                iface_name
            )
            peer = iface_info.get("peer", "unknown")

            if orig_passive and not prop_passive:
                faults_fixed.append(
                    f"{router_name}: Fixed passive-interface on transit link "
                    f"{iface_name} (peer: {peer}) — OSPF adjacency can now form"
                )
            elif not orig_passive and prop_passive:
                regressions.append(
                    f"{router_name}: Transit interface {iface_name} made "
                    f"passive, breaking OSPF adjacency with {peer}"
                )
            elif orig_passive and prop_passive:
                faults_missed.append(
                    f"{router_name}: Transit interface {iface_name} still "
                    f"passive — no OSPF adjacency with {peer}"
                )

        # --- OSPF network statement coverage ---
        for iface_name, iface_info in router_info["interfaces"].items():
            if iface_info.get("type") == "loopback":
                continue
            iface_addr = iface_info.get("address")
            if not iface_addr:
                continue
            orig_covered = orig_configs[router_name].is_address_in_ospf(
                iface_addr
            )
            prop_covered = configs[router_name].is_address_in_ospf(iface_addr)

            if not orig_covered and prop_covered:
                faults_fixed.append(
                    f"{router_name}: Fixed OSPF network statement to cover "
                    f"{iface_name} ({iface_addr})"
                )
            elif not orig_covered and not prop_covered:
                faults_missed.append(
                    f"{router_name}: Interface {iface_name} ({iface_addr}) "
                    f"still not covered by OSPF network statements"
                )

        # --- Distribute-list analysis ---
        for subnet in protected_subnets:
            orig_blocked = orig_configs[router_name].does_distribute_list_block(
                subnet
            )
            prop_blocked = configs[router_name].does_distribute_list_block(
                subnet
            )
            if orig_blocked and not prop_blocked:
                faults_fixed.append(
                    f"{router_name}: Fixed distribute-list that was blocking "
                    f"{subnet}"
                )
            elif orig_blocked and prop_blocked:
                faults_missed.append(
                    f"{router_name}: Distribute-list still blocks {subnet}"
                )

        # --- Security regression: BOGON_FILTER removal ---
        if check_bogon_filter_present(orig_texts[router_name]):
            if not check_bogon_filter_present(texts[router_name]):
                regressions.append(
                    f"{router_name}: BOGON_FILTER prefix-list removed — this "
                    f"is a security filter preventing bogon route injection "
                    f"and should be preserved (defense-in-depth)"
                )

        # --- Best-practice: overly broad network statements ---
        for net in configs[router_name].ospf["networks"]:
            try:
                ospf_net = ipaddress.ip_network(net["prefix"], strict=False)
                if ospf_net.prefixlen < 16:
                    regressions.append(
                        f"{router_name}: Overly broad OSPF network statement "
                        f"{net['prefix']} (/{ospf_net.prefixlen}) violates "
                        f"principle of least privilege — should use specific "
                        f"subnet matching"
                    )
            except ValueError:
                continue

    # Determine recommendation
    if regressions:
        recommendation = "reject"
    elif faults_missed:
        recommendation = "accept_with_changes"
    else:
        recommendation = "accept"

    return {
        "faults_correctly_fixed": faults_fixed,
        "faults_missed": faults_missed,
        "regressions_introduced": regressions,
        "recommendation": recommendation,
    }


def create_correct_configs(orig_texts, topology):
    """Create correct configs by applying minimal targeted fixes
    that resolve all faults without introducing regressions."""
    fixed_texts = dict(orig_texts)
    faults = []

    # Fix 1: dist_rtr2 — add 'no passive-interface eth0'
    text = fixed_texts["dist_rtr2"]
    lines = text.split("\n")
    result = []
    inserted = False
    for line in lines:
        result.append(line)
        if line.strip() == "passive-interface default" and not inserted:
            result.append(" no passive-interface eth0")
            inserted = True
    fixed_texts["dist_rtr2"] = "\n".join(result)
    faults.append({
        "device": "dist_rtr2",
        "root_cause": (
            "passive-interface default is set but 'no passive-interface eth0' "
            "is missing for the transit uplink to core_rtr, preventing OSPF "
            "adjacency formation — dist_rtr2 is completely isolated from the "
            "OSPF domain"
        ),
        "fix_applied": (
            "Added 'no passive-interface eth0' to router ospf section"
        ),
    })

    # Fix 2: core_rtr — remove stale distribute-list
    text = fixed_texts["core_rtr"]
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if re.match(
            r"distribute-list\s+prefix\s+MAINT_FILTER\s+in", stripped
        ):
            continue
        if "Apply maintenance window filter" in stripped:
            continue
        result.append(line)
    fixed_texts["core_rtr"] = "\n".join(result)
    faults.append({
        "device": "core_rtr",
        "root_cause": (
            "Stale distribute-list referencing prefix-list MAINT_FILTER from "
            "maintenance ticket NET-4471 (2026-04-15) was never removed after "
            "the maintenance window closed, causing it to deny the "
            "10.3.0.0/24 host subnet route from dist_rtr3"
        ),
        "fix_applied": (
            "Removed 'distribute-list prefix MAINT_FILTER in' from OSPF "
            "configuration while preserving BOGON_FILTER and other "
            "security-relevant prefix-lists"
        ),
    })

    # Fix 3: dist_rtr1 — correct network statement typo
    text = fixed_texts["dist_rtr1"]
    text = text.replace(
        "network 10.10.0.0/24 area 0", "network 10.1.0.0/24 area 0"
    )
    fixed_texts["dist_rtr1"] = text
    faults.append({
        "device": "dist_rtr1",
        "root_cause": (
            "OSPF network statement '10.10.0.0/24' is a typo — should be "
            "'10.1.0.0/24' to match eth1 (10.1.0.1/24). The host subnet "
            "10.1.0.0/24 is not advertised into OSPF, making host1 "
            "unreachable from other sites"
        ),
        "fix_applied": (
            "Changed OSPF network statement from '10.10.0.0/24' to "
            "'10.1.0.0/24'"
        ),
    })

    return fixed_texts, faults


def main():
    topology = load_topology()

    # Load original broken configs
    orig_configs, orig_texts = load_configs(
        "/app/network_state/configs", topology
    )

    # Evaluate both proposals
    print("Evaluating Plan A...")
    plan_a_eval = evaluate_proposal(
        "/app/proposals/plan_a", orig_configs, orig_texts, topology
    )

    print("Evaluating Plan B...")
    plan_b_eval = evaluate_proposal(
        "/app/proposals/plan_b", orig_configs, orig_texts, topology
    )

    # Create correct configs via targeted fixes
    print("Creating corrected configurations...")
    fixed_texts, faults = create_correct_configs(orig_texts, topology)

    # Verify our fix passes the validator
    os.makedirs("/app/fixed_configs", exist_ok=True)
    for router_name, text in fixed_texts.items():
        with open(f"/app/fixed_configs/{router_name}.conf", "w") as f:
            f.write(text)

    validation_errors = validate_configs("/app/fixed_configs", topology)
    if validation_errors:
        print(f"WARNING: Fixed configs have {len(validation_errors)} error(s):")
        for e in validation_errors:
            print(f"  - {e}")
    else:
        print("Fixed configs pass all validator checks.")

    # Write evaluation report
    evaluation = {
        "plan_a": plan_a_eval,
        "plan_b": plan_b_eval,
        "final_approach": (
            "Custom remediation applying minimal targeted fixes: "
            "(1) Added 'no passive-interface eth0' on dist_rtr2 to restore "
            "OSPF adjacency with core_rtr. "
            "(2) Removed only the stale distribute-list on core_rtr while "
            "preserving BOGON_FILTER and other security prefix-lists. "
            "(3) Corrected dist_rtr1 network statement from 10.10.0.0/24 to "
            "10.1.0.0/24 using the specific /24 subnet rather than an "
            "overly broad /8. "
            "This approach takes the correct elements from both proposals "
            "while avoiding Plan A's regressions (dist_rtr3 passive, bogon "
            "filter removal) and Plan B's issues (missed dist_rtr2 fault, "
            "overly broad network statement)."
        ),
    }
    with open("/app/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)

    # Write diagnosis report
    diagnosis = {"faults": faults}
    with open("/app/diagnosis.json", "w") as f:
        json.dump(diagnosis, f, indent=2)

    # Print summary
    print("\n=== Plan A Evaluation ===")
    print(f"  Correctly fixed: {len(plan_a_eval['faults_correctly_fixed'])}")
    print(f"  Missed: {len(plan_a_eval['faults_missed'])}")
    print(f"  Regressions: {len(plan_a_eval['regressions_introduced'])}")
    print(f"  Recommendation: {plan_a_eval['recommendation']}")
    for r in plan_a_eval["regressions_introduced"]:
        print(f"    REGRESSION: {r}")

    print("\n=== Plan B Evaluation ===")
    print(f"  Correctly fixed: {len(plan_b_eval['faults_correctly_fixed'])}")
    print(f"  Missed: {len(plan_b_eval['faults_missed'])}")
    print(f"  Regressions: {len(plan_b_eval['regressions_introduced'])}")
    print(f"  Recommendation: {plan_b_eval['recommendation']}")
    for m in plan_b_eval["faults_missed"]:
        print(f"    MISSED: {m}")
    for r in plan_b_eval["regressions_introduced"]:
        print(f"    REGRESSION: {r}")

    print(f"\n=== Corrected {len(faults)} fault(s) ===")
    for f in faults:
        print(f"  [{f['device']}] {f['root_cause'][:80]}...")


if __name__ == "__main__":
    main()
