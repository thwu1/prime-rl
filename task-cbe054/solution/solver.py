#!/usr/bin/env python3
"""
OSPF Neighbor FSM Conformance Test Suite Generator.

Corrects the FSM model against RFC 2328 Section 10.3, parses FRRouting
configs to build a topology model, generates a Graphviz state diagram,
analyzes test coverage, and generates topology-aware test cases.
"""

import glob
import ipaddress
import json
import os
import re
import subprocess


STATES = [
    "Down", "Attempt", "Init", "TwoWay",
    "ExStart", "Exchange", "Loading", "Full",
]

EVENTS = [
    "HelloReceived", "Start", "TwoWayReceived", "NegotiationDone",
    "ExchangeDone", "BadLSReq", "LoadingDone", "AdjOK",
    "SeqNumberMismatch", "OneWay", "KillNbr", "InactivityTimer", "LLDown",
]

# Correct transition templates derived from RFC 2328 Section 10.3
CORRECT_TRANSITIONS = [
    # Down
    {"from": "Down", "event": "HelloReceived", "to": "Init"},
    {"from": "Down", "event": "Start", "to": "Attempt"},
    # Attempt
    {"from": "Attempt", "event": "HelloReceived", "to": "Init"},
    # Init
    {"from": "Init", "event": "TwoWayReceived", "to": "TwoWay",
     "condition": "no_adjacency_needed"},
    {"from": "Init", "event": "TwoWayReceived", "to": "ExStart",
     "condition": "adjacency_needed"},
    # TwoWay
    {"from": "TwoWay", "event": "AdjOK", "to": "ExStart",
     "condition": "adjacency_needed"},
    # ExStart
    {"from": "ExStart", "event": "NegotiationDone", "to": "Exchange"},
    # Exchange
    {"from": "Exchange", "event": "ExchangeDone", "to": "Loading",
     "condition": "ls_request_list_nonempty"},
    {"from": "Exchange", "event": "ExchangeDone", "to": "Full",
     "condition": "ls_request_list_empty"},
    # Loading
    {"from": "Loading", "event": "LoadingDone", "to": "Full"},
    # SeqNumberMismatch from Exchange, Loading, Full
    {"from": "Exchange", "event": "SeqNumberMismatch", "to": "ExStart"},
    {"from": "Loading", "event": "SeqNumberMismatch", "to": "ExStart"},
    {"from": "Full", "event": "SeqNumberMismatch", "to": "ExStart"},
    # BadLSReq from Exchange, Loading, Full
    {"from": "Exchange", "event": "BadLSReq", "to": "ExStart"},
    {"from": "Loading", "event": "BadLSReq", "to": "ExStart"},
    {"from": "Full", "event": "BadLSReq", "to": "ExStart"},
    # OneWay from TwoWay, ExStart, Exchange, Loading, Full
    {"from": "TwoWay", "event": "OneWay", "to": "Init"},
    {"from": "ExStart", "event": "OneWay", "to": "Init"},
    {"from": "Exchange", "event": "OneWay", "to": "Init"},
    {"from": "Loading", "event": "OneWay", "to": "Init"},
    {"from": "Full", "event": "OneWay", "to": "Init"},
    # Wildcard reset events expanded to all states
    {"from": "*", "event": "KillNbr", "to": "Down"},
    {"from": "*", "event": "LLDown", "to": "Down"},
    {"from": "*", "event": "InactivityTimer", "to": "Down"},
    # AdjOK demotion from ExStart, Exchange, Loading, Full
    {"from": "ExStart", "event": "AdjOK", "to": "TwoWay",
     "condition": "no_adjacency_needed"},
    {"from": "Exchange", "event": "AdjOK", "to": "TwoWay",
     "condition": "no_adjacency_needed"},
    {"from": "Loading", "event": "AdjOK", "to": "TwoWay",
     "condition": "no_adjacency_needed"},
    {"from": "Full", "event": "AdjOK", "to": "TwoWay",
     "condition": "no_adjacency_needed"},
]


def expand_wildcards(transitions, states):
    """Expand transitions with from='*' into one entry per state."""
    expanded = []
    for t in transitions:
        if t["from"] == "*":
            for state in states:
                new_t = {k: v for k, v in t.items()}
                new_t["from"] = state
                expanded.append(new_t)
        else:
            expanded.append({k: v for k, v in t.items()})
    return expanded


def transition_key(t):
    """Hashable key for a transition."""
    return (t["from"], t["event"], t["to"], t.get("condition", ""))


def analyze_coverage(transitions, test_cases):
    """Compute which transitions are covered by test cases."""
    all_keys = set()
    for t in transitions:
        all_keys.add(transition_key(t))

    covered_map = {}
    for tc in test_cases:
        for ft in tc.get("fsm_transitions", []):
            key = transition_key(ft)
            if key in all_keys:
                if key not in covered_map:
                    covered_map[key] = []
                if tc["id"] not in covered_map[key]:
                    covered_map[key].append(tc["id"])

    covered_transitions = []
    uncovered_transitions = []
    for t in transitions:
        key = transition_key(t)
        if key in covered_map:
            ct = {k: v for k, v in t.items()}
            ct["covered_by"] = covered_map[key]
            covered_transitions.append(ct)
        else:
            uncovered_transitions.append({k: v for k, v in t.items()})

    total = len(transitions)
    pct = len(covered_transitions) / total * 100 if total > 0 else 0.0
    return {
        "total_transitions": total,
        "covered_transitions": covered_transitions,
        "uncovered_transitions": uncovered_transitions,
        "coverage_percentage": round(pct, 2),
    }


# --- FRRouting Config Parsing ---

def parse_frr_config(filepath):
    """Parse a single FRRouting configuration file."""
    with open(filepath) as f:
        content = f.read()

    result = {
        "hostname": None,
        "router_id": None,
        "interfaces": {},
        "networks": [],
        "passive_interfaces": [],
    }

    lines = content.split("\n")
    current_section = None
    current_iface = None

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped == "!":
            if current_section == "interface":
                pass  # interfaces span until next section
            else:
                current_section = None
            continue

        if stripped.startswith("hostname "):
            result["hostname"] = stripped.split(None, 1)[1]
            continue

        m = re.match(r"^interface\s+(\S+)", stripped)
        if m:
            current_iface = m.group(1)
            current_section = "interface"
            if current_iface not in result["interfaces"]:
                result["interfaces"][current_iface] = {}
            continue

        if stripped == "router ospf":
            current_section = "router_ospf"
            current_iface = None
            continue

        if stripped.startswith("line "):
            current_section = None
            current_iface = None
            continue

        if current_section == "interface" and current_iface:
            iface = result["interfaces"][current_iface]
            m = re.match(r"ip address\s+(\S+)", stripped)
            if m:
                iface["ip_address"] = m.group(1)
            m = re.match(r"ip ospf network\s+(\S+)", stripped)
            if m:
                iface["network_type"] = m.group(1)
            m = re.match(r"ip ospf hello-interval\s+(\d+)", stripped)
            if m:
                iface["hello_interval"] = int(m.group(1))
            m = re.match(r"ip ospf dead-interval\s+(\d+)", stripped)
            if m:
                iface["dead_interval"] = int(m.group(1))
            m = re.match(r"ip ospf priority\s+(\d+)", stripped)
            if m:
                iface["priority"] = int(m.group(1))
            m = re.match(r"ip ospf cost\s+(\d+)", stripped)
            if m:
                iface["cost"] = int(m.group(1))

        if current_section == "router_ospf":
            m = re.match(r"ospf router-id\s+(\S+)", stripped)
            if m:
                result["router_id"] = m.group(1)
            m = re.match(r"network\s+(\S+)\s+area\s+(\S+)", stripped)
            if m:
                result["networks"].append({
                    "network": m.group(1),
                    "area": m.group(2),
                })
            m = re.match(r"passive-interface\s+(\S+)", stripped)
            if m:
                result["passive_interfaces"].append(m.group(1))

    return result


def build_topology(parsed_configs):
    """Build topology JSON from parsed FRRouting configurations."""
    routers = []
    network_routers = {}

    for cfg in parsed_configs:
        router = {
            "router_id": cfg["router_id"],
            "hostname": cfg["hostname"],
            "interfaces": [],
        }

        for iface_name, iface_data in cfg["interfaces"].items():
            if iface_name in cfg["passive_interfaces"]:
                continue
            if "ip_address" not in iface_data:
                continue
            if "network_type" not in iface_data:
                continue

            ip_str = iface_data["ip_address"].split("/")[0]
            ip_addr = ipaddress.ip_address(ip_str)

            matched_network = None
            matched_area = None
            for net in cfg["networks"]:
                net_obj = ipaddress.ip_network(net["network"], strict=False)
                if ip_addr in net_obj:
                    matched_network = str(net_obj)
                    matched_area = net["area"]
                    break

            if matched_network is None:
                continue

            iface_entry = {
                "name": iface_name,
                "network": matched_network,
                "area": matched_area,
                "network_type": iface_data["network_type"],
            }
            for opt in ("hello_interval", "dead_interval", "priority", "cost"):
                if opt in iface_data:
                    iface_entry[opt] = iface_data[opt]

            router["interfaces"].append(iface_entry)

            key = matched_network
            if key not in network_routers:
                network_routers[key] = []
            network_routers[key].append({
                "router_id": cfg["router_id"],
                "network_type": iface_data["network_type"],
                "area": matched_area,
            })

        routers.append(router)

    links = []
    for network, participants in sorted(network_routers.items()):
        if len(participants) >= 2:
            links.append({
                "network": network,
                "routers": sorted([p["router_id"] for p in participants]),
                "network_type": participants[0]["network_type"],
                "area": participants[0]["area"],
            })

    return {"routers": routers, "links": links}


# --- Graphviz Diagram ---

def generate_dot(fsm):
    """Generate Graphviz DOT source for the FSM."""
    lines = [
        "digraph OSPF_Neighbor_FSM {",
        "  rankdir=LR;",
        '  node [shape=ellipse, style=filled, fillcolor="#E8F4FD", '
        'fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=9];',
        "",
    ]

    for state in fsm["states"]:
        lines.append(f'  "{state}";')

    lines.append("")

    edge_labels = {}
    for t in fsm["transitions"]:
        key = (t["from"], t["to"])
        label = t["event"]
        if "condition" in t:
            label += f" [{t['condition']}]"
        if key not in edge_labels:
            edge_labels[key] = []
        edge_labels[key].append(label)

    for (src, dst), labels in sorted(edge_labels.items()):
        label_str = "\\n".join(labels)
        lines.append(f'  "{src}" -> "{dst}" [label="{label_str}"];')

    lines.append("}")
    return "\n".join(lines)


def render_diagram(dot_source, output_path):
    """Render DOT to SVG via graphviz dot command."""
    result = subprocess.run(
        ["dot", "-Tsvg", "-o", output_path],
        input=dot_source.encode(),
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Graphviz error: {result.stderr.decode()}")


# --- Topology-Aware Test Generation ---

PATH_TO_STATE = {
    "Down": [],
    "Attempt": [
        {"from": "Down", "event": "Start", "to": "Attempt"},
    ],
    "Init": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
    ],
    "TwoWay": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
        {"from": "Init", "event": "TwoWayReceived", "to": "TwoWay",
         "condition": "no_adjacency_needed"},
    ],
    "ExStart": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
        {"from": "Init", "event": "TwoWayReceived", "to": "ExStart",
         "condition": "adjacency_needed"},
    ],
    "Exchange": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
        {"from": "Init", "event": "TwoWayReceived", "to": "ExStart",
         "condition": "adjacency_needed"},
        {"from": "ExStart", "event": "NegotiationDone", "to": "Exchange"},
    ],
    "Loading": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
        {"from": "Init", "event": "TwoWayReceived", "to": "ExStart",
         "condition": "adjacency_needed"},
        {"from": "ExStart", "event": "NegotiationDone", "to": "Exchange"},
        {"from": "Exchange", "event": "ExchangeDone", "to": "Loading",
         "condition": "ls_request_list_nonempty"},
    ],
    "Full": [
        {"from": "Down", "event": "HelloReceived", "to": "Init"},
        {"from": "Init", "event": "TwoWayReceived", "to": "ExStart",
         "condition": "adjacency_needed"},
        {"from": "ExStart", "event": "NegotiationDone", "to": "Exchange"},
        {"from": "Exchange", "event": "ExchangeDone", "to": "Loading",
         "condition": "ls_request_list_nonempty"},
        {"from": "Loading", "event": "LoadingDone", "to": "Full"},
    ],
}

EVENT_TRIGGERS = {
    "HelloReceived": "Send a Hello packet from the tester that includes "
                     "the DUT Router ID in the neighbor list.",
    "Start": "Configure a static NBMA neighbor entry to trigger the "
             "Start event.",
    "TwoWayReceived": "Send a Hello packet containing the DUT Router ID "
                      "in the neighbor list to establish bidirectional "
                      "communication.",
    "NegotiationDone": "Complete master/slave negotiation by exchanging "
                       "DD packets with correct flags and sequence numbers.",
    "ExchangeDone": "Complete Database Description exchange by sending "
                    "and receiving all DD packets.",
    "BadLSReq": "Send an LS Request for an LSA that does not exist in "
                "the neighbor database.",
    "LoadingDone": "Complete all outstanding LS Request/Update exchanges.",
    "AdjOK": "Trigger AdjOK? decision event by changing DR/BDR election "
             "outcome or interface parameters.",
    "SeqNumberMismatch": "Send a DD packet with an unexpected sequence "
                         "number or inconsistent Init/More/Master flags.",
    "OneWay": "Send a Hello packet from the neighbor that does NOT "
              "include the DUT Router ID in the neighbor list.",
    "KillNbr": "Issue a manual clear/kill command for the neighbor.",
    "InactivityTimer": "Block Hello packets from the neighbor and wait "
                       "for the DeadInterval to expire.",
    "LLDown": "Simulate a link-layer failure by shutting down the "
              "interface.",
}


def generate_test_case(transition, tc_id, topology):
    """Generate a topology-aware test case for an FSM transition."""
    from_state = transition["from"]
    event = transition["event"]
    to_state = transition["to"]
    condition = transition.get("condition", "")

    broadcast_links = [l for l in topology["links"]
                       if l["network_type"] == "broadcast"]
    p2p_links = [l for l in topology["links"]
                 if l["network_type"] == "point-to-point"]

    router_names = {r["router_id"]: r["hostname"]
                    for r in topology["routers"]}

    if condition == "no_adjacency_needed":
        link = broadcast_links[0] if broadcast_links else topology["links"][0]
    else:
        link = p2p_links[0] if p2p_links else topology["links"][0]

    link_routers = [router_names.get(rid, rid) for rid in link["routers"]]
    net_desc = (f"{link['network_type']} network {link['network']} "
                f"in area {link['area']}")

    setup_desc = (f"Configure {link_routers[0]} and {link_routers[1]} on "
                  f"{net_desc}. Enable OSPF and bring the neighbor "
                  f"relationship to {from_state} state.")

    trigger_desc = EVENT_TRIGGERS.get(event, f"Trigger the {event} event.")
    if condition:
        trigger_desc += f" Ensure condition: {condition.replace('_', ' ')}."

    cond_label = f" ({condition.replace('_', ' ')})" if condition else ""

    path = [dict(t) for t in PATH_TO_STATE.get(from_state, [])]
    path.append({k: v for k, v in transition.items()})

    steps = [
        {
            "step_id": "1",
            "description": setup_desc,
            "expected_result": f"Neighbor is in {from_state} state.",
        },
        {
            "step_id": "2",
            "description": trigger_desc,
            "expected_result": f"{event} event is generated.",
        },
        {
            "step_id": "3",
            "description": f"Verify that neighbor state transitions to "
                           f"{to_state}.",
            "expected_result": f"Neighbor state is {to_state}.",
        },
    ]

    return {
        "id": f"TC-OSPF-NBR-GEN-{tc_id:03d}",
        "title": f"OSPF {event} from {from_state} to {to_state}{cond_label}",
        "objective": (f"Verify that the {event} event in {from_state} state "
                      f"correctly transitions the neighbor to {to_state}"
                      f"{cond_label} on {net_desc}."),
        "fsm_transitions": path,
        "steps": steps,
        "tags": ["function", "ospf", "generated"],
        "test_reference": ["RFC 2328 Section 10.3"],
    }


def main():
    os.makedirs("/app/output", exist_ok=True)

    # 1. Correct and expand FSM
    expanded = expand_wildcards(CORRECT_TRANSITIONS, STATES)
    fsm = {
        "protocol": "OSPFv2",
        "source": "RFC 2328 Section 10.3",
        "states": list(STATES),
        "events": list(EVENTS),
        "transitions": expanded,
    }
    with open("/app/output/fsm.json", "w") as f:
        json.dump(fsm, f, indent=2)
    print(f"FSM written: {len(expanded)} transitions")

    # 2. Parse FRR configs and build topology
    parsed_configs = []
    for conf_path in sorted(glob.glob("/app/frr_configs/r*.conf")):
        parsed_configs.append(parse_frr_config(conf_path))
    topology = build_topology(parsed_configs)
    with open("/app/output/topology.json", "w") as f:
        json.dump(topology, f, indent=2)
    print(f"Topology written: {len(topology['routers'])} routers, "
          f"{len(topology['links'])} links")

    # 3. Generate FSM diagram
    dot_source = generate_dot(fsm)
    render_diagram(dot_source, "/app/output/fsm_diagram.svg")
    print("FSM diagram rendered to fsm_diagram.svg")

    # 4. Analyze existing test coverage
    with open("/app/existing_tests.json") as f:
        existing = json.load(f)

    cov_before = analyze_coverage(expanded, existing["test_cases"])
    with open("/app/output/coverage_before.json", "w") as f:
        json.dump(cov_before, f, indent=2)
    print(f"Coverage before: {cov_before['coverage_percentage']}% "
          f"({len(cov_before['covered_transitions'])}/"
          f"{cov_before['total_transitions']})")

    # 5. Generate test cases for uncovered transitions
    test_suite = {"test_cases": []}
    seen = set()
    tc_id = 1
    for t in cov_before["uncovered_transitions"]:
        key = transition_key(t)
        if key not in seen:
            tc = generate_test_case(t, tc_id, topology)
            test_suite["test_cases"].append(tc)
            seen.add(key)
            tc_id += 1

    with open("/app/output/test_suite.json", "w") as f:
        json.dump(test_suite, f, indent=2)
    print(f"Generated {len(test_suite['test_cases'])} new test cases")

    # 6. Recompute coverage
    all_tests = existing["test_cases"] + test_suite["test_cases"]
    cov_after = analyze_coverage(expanded, all_tests)
    with open("/app/output/coverage_after.json", "w") as f:
        json.dump(cov_after, f, indent=2)
    print(f"Coverage after: {cov_after['coverage_percentage']}% "
          f"({len(cov_after['covered_transitions'])}/"
          f"{cov_after['total_transitions']})")


if __name__ == "__main__":
    main()
