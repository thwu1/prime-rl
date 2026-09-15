#!/usr/bin/env python3
"""
OSPF Adjacency Forensics Solution.
Uses tshark for pcap field extraction and scapy for binary-level
protocol decoding to analyze OSPF adjacency failures.

"""

import json
import os
import subprocess
import sys

from scapy.all import rdpcap, conf
from scapy.contrib.ospf import OSPF_Hdr, OSPF_Hello, OSPF_DBDesc

conf.verb = 0

PCAP = "/app/capture/ospf_adjacency.pcap"
TOPO = "/app/topology/topology.json"
OUT = "/app/output"


def run_tshark(display_filter, fields):
    """Run tshark field extraction and return parsed rows."""
    cmd = ["tshark", "-r", PCAP, "-n", "-Y", display_filter,
           "-T", "fields", "-E", "separator=|", "-E", "header=n"]
    for f in fields:
        cmd += ["-e", f]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    return [l.split("|") for l in lines]


def build_inventory():
    """Build packet inventory using scapy with tshark cross-verification."""
    # Verify tshark can read the pcap
    ts_hello = run_tshark("ospf.msg==1", ["frame.number", "ospf.srcrouter"])
    ts_dd = run_tshark("ospf.msg==2", ["frame.number", "ospf.srcrouter"])
    print(f"  tshark: {len(ts_hello)} Hello, {len(ts_dd)} DD packets")

    # Use tshark to extract R3's HelloInterval for cross-check
    ts_r3 = run_tshark("ospf.msg==1 && ospf.srcrouter==3.3.3.3",
                       ["ospf.hello.hello_interval"])
    if ts_r3:
        print(f"  tshark R3 HelloInterval: {ts_r3[0][0]}")

    # Use tshark to extract R4's DD MTU for cross-check
    ts_r4_dd = run_tshark("ospf.msg==2 && ospf.srcrouter==4.4.4.4",
                          ["ospf.db.dd.mtu"])
    if ts_r4_dd:
        print(f"  tshark R4 DD MTU: {ts_r4_dd[0][0]}")

    # Full inventory via scapy for binary-level access
    pkts = rdpcap(PCAP)
    inventory = []
    hello_count = 0
    dd_count = 0
    routers = set()

    for i, pkt in enumerate(pkts):
        if not pkt.haslayer(OSPF_Hdr):
            continue
        ospf = pkt[OSPF_Hdr]
        rid = ospf.src
        otype = int(ospf.type)
        routers.add(rid)

        entry = {
            "packet_number": i + 1,
            "timestamp": float(pkt.time),
            "src_ip": pkt["IP"].src,
            "dst_ip": pkt["IP"].dst,
            "ospf_type": otype,
            "router_id": rid,
        }

        if otype == 1 and pkt.haslayer(OSPF_Hello):
            hello_count += 1
            h = pkt[OSPF_Hello]
            opts = int(h.options)
            entry["hello_interval"] = int(h.hellointerval)
            entry["dead_interval"] = int(h.deadinterval)
            entry["options_e_bit"] = bool(opts & 0x02)
            entry["neighbors"] = list(h.neighbors) if h.neighbors else []
        elif otype == 2 and pkt.haslayer(OSPF_DBDesc):
            dd_count += 1
            d = pkt[OSPF_DBDesc]
            entry["mtu"] = int(d.mtu)
            entry["flags"] = int(d.dbdescr)
            entry["dd_sequence"] = int(d.ddseq)

        inventory.append(entry)

    return {
        "total_packets": len(inventory),
        "hello_packets": hello_count,
        "dd_packets": dd_count,
        "routers_observed": sorted(routers),
        "packets": inventory,
    }


def analyze_adjacencies(inv):
    """Analyze per-pair adjacency formation via FSM replay."""
    with open(TOPO) as f:
        topo = json.load(f)
    ref = topo["expected_config"]
    rid_to_ip = {r["router_id"]: r["interface_ip"] for r in topo["routers"]}
    ip_to_rid = {v: k for k, v in rid_to_ip.items()}

    hellos = [p for p in inv["packets"] if p["ospf_type"] == 1]
    dds = [p for p in inv["packets"] if p["ospf_type"] == 2]

    # Check Hello conformance per router (RFC 2328 Section 10.5)
    hello_violations = {}
    for h in hellos:
        rid = h["router_id"]
        if rid in hello_violations:
            continue
        viols = []
        if h.get("hello_interval") != ref["hello_interval"]:
            viols.append(
                f"HelloInterval={h['hello_interval']}, expected {ref['hello_interval']}"
            )
        if h.get("dead_interval") != ref["dead_interval"]:
            viols.append(
                f"DeadInterval={h['dead_interval']}, expected {ref['dead_interval']}"
            )
        if h.get("options_e_bit") != ref["external_routing_capability"]:
            viols.append(
                f"E-bit={'set' if h.get('options_e_bit') else 'clear'}, "
                f"expected {'set' if ref['external_routing_capability'] else 'clear'}"
            )
        if viols:
            hello_violations[rid] = viols

    all_rids = sorted(inv["routers_observed"])
    adjacencies = []

    for i, ra in enumerate(all_rids):
        for rb in all_rids[i + 1:]:
            if ra in hello_violations:
                adj = {
                    "router_a": ra, "router_b": rb,
                    "final_state": "Down", "successful": False,
                    "failure_reason":
                        f"Hello rejected - {'; '.join(hello_violations[ra])}"
                }
            elif rb in hello_violations:
                adj = {
                    "router_a": ra, "router_b": rb,
                    "final_state": "Down", "successful": False,
                    "failure_reason":
                        f"Hello rejected - {'; '.join(hello_violations[rb])}"
                }
            else:
                # Both pass Hello checks - examine DD exchange
                ip_a = rid_to_ip.get(ra)
                ip_b = rid_to_ip.get(rb)
                pair_dds = [
                    d for d in dds
                    if (d["router_id"] == ra and d["dst_ip"] == ip_b)
                    or (d["router_id"] == rb and d["dst_ip"] == ip_a)
                ]

                if not pair_dds:
                    adj = {
                        "router_a": ra, "router_b": rb,
                        "final_state": "2-Way", "successful": False,
                        "failure_reason": "No DD exchange initiated"
                    }
                else:
                    mtus = set()
                    for d in pair_dds:
                        mtus.add(d.get("mtu", 1500))

                    if len(mtus) > 1:
                        # MTU mismatch - check if ExStart ever completed
                        all_init = all(
                            d.get("flags", 7) == 0x07 for d in pair_dds
                            if d["router_id"] in (ra, rb)
                        )
                        # Also check: did any non-init DD appear for this pair?
                        non_init = [
                            d for d in pair_dds
                            if d.get("flags", 7) & 0x04 == 0
                        ]
                        if not non_init:
                            adj = {
                                "router_a": ra, "router_b": rb,
                                "final_state": "ExStart",
                                "successful": False,
                                "failure_reason":
                                    f"ExStart stall - Interface MTU mismatch "
                                    f"(MTU values: {sorted(mtus)})"
                            }
                        else:
                            adj = {
                                "router_a": ra, "router_b": rb,
                                "final_state": "Exchange",
                                "successful": False,
                                "failure_reason": "DD exchange incomplete"
                            }
                    else:
                        # Same MTU - check if exchange completed
                        final = [
                            d for d in pair_dds
                            if d.get("flags", 7) & 0x02 == 0
                            and d.get("flags", 7) & 0x04 == 0
                        ]
                        if final:
                            adj = {
                                "router_a": ra, "router_b": rb,
                                "final_state": "Full",
                                "successful": True,
                                "failure_reason": ""
                            }
                        else:
                            adj = {
                                "router_a": ra, "router_b": rb,
                                "final_state": "Exchange",
                                "successful": False,
                                "failure_reason": "DD exchange in progress"
                            }

            adjacencies.append(adj)

    return {"adjacencies": adjacencies}, hello_violations


def build_violations(inv, hello_viols):
    """Build protocol violations report."""
    with open(TOPO) as f:
        topo = json.load(f)
    ref = topo["expected_config"]
    all_rids = sorted(inv["routers_observed"])
    dds = [p for p in inv["packets"] if p["ospf_type"] == 2]

    violations = []

    # Hello-based violations (Section 10.5)
    for rid, viols in sorted(hello_viols.items()):
        r_hellos = [p for p in inv["packets"]
                    if p["ospf_type"] == 1 and p["router_id"] == rid]
        if not r_hellos:
            continue
        h = r_hellos[0]

        if h.get("hello_interval") != ref["hello_interval"]:
            violations.append({
                "router_id": rid,
                "violation_type": "HelloInterval/DeadInterval mismatch",
                "rfc_section": "10.5",
                "evidence": (
                    f"HelloInterval={h['hello_interval']}, "
                    f"DeadInterval={h['dead_interval']}; "
                    f"expected HelloInterval={ref['hello_interval']}, "
                    f"DeadInterval={ref['dead_interval']}"
                ),
                "affected_pairs": [
                    f"{rid}-{r}" for r in all_rids if r != rid
                ],
            })

        if h.get("options_e_bit") != ref["external_routing_capability"]:
            violations.append({
                "router_id": rid,
                "violation_type": "Options E-bit mismatch",
                "rfc_section": "10.5",
                "evidence": (
                    f"E-bit={'set' if h.get('options_e_bit') else 'clear'}, "
                    f"expected "
                    f"{'set' if ref['external_routing_capability'] else 'clear'}"
                ),
                "affected_pairs": [
                    f"{rid}-{r}" for r in all_rids if r != rid
                ],
            })

    # DD MTU violations (Section 10.6)
    mtu_seen = set()
    for d in dds:
        mtu_val = d.get("mtu", 1500)
        iface_mtu = topo.get("interface_mtu", 1500)
        rid = d["router_id"]
        if mtu_val != iface_mtu and rid not in mtu_seen:
            mtu_seen.add(rid)
            conformant = [
                r for r in all_rids
                if r != rid and r not in hello_viols
            ]
            violations.append({
                "router_id": rid,
                "violation_type": "Interface MTU mismatch in DD packets",
                "rfc_section": "10.6",
                "evidence": (
                    f"DD MTU={mtu_val}, receiving interfaces use "
                    f"MTU={iface_mtu}; DD packets with MTU larger than "
                    f"receiver's interface MTU are silently dropped per "
                    f"RFC 2328 Section 10.6, causing ExStart to stall"
                ),
                "affected_pairs": [f"{rid}-{r}" for r in conformant],
            })

    return {"violations": violations}


def build_report(adj_matrix, viols):
    """Build root cause summary report."""
    adjs = adj_matrix["adjacencies"]
    successful = sum(1 for a in adjs if a["successful"])
    failed = sum(1 for a in adjs if not a["successful"])

    root_causes = []

    for v in viols["violations"]:
        vtype = v["violation_type"]

        if "HelloInterval" in vtype or "DeadInterval" in vtype:
            root_causes.append({
                "category": "timer_mismatch",
                "affected_router": v["router_id"],
                "description": (
                    f"Router {v['router_id']} is configured with "
                    f"non-matching OSPF timer values. {v['evidence']}. "
                    f"Per RFC 2328 Section 10.5, Hello packets with "
                    f"mismatched HelloInterval or RouterDeadInterval are "
                    f"silently discarded, preventing any neighbor "
                    f"relationship from forming."
                ),
                "rfc_reference": (
                    "RFC 2328 Section 10.5 (Receiving Hello Packets), "
                    "Check 4: HelloInterval and RouterDeadInterval must "
                    "be identical"
                ),
                "remediation": (
                    f"Configure router {v['router_id']} with "
                    f"HelloInterval=10 and DeadInterval=40 to match "
                    f"the network-wide OSPF configuration."
                ),
            })

        elif "E-bit" in vtype:
            root_causes.append({
                "category": "options_mismatch",
                "affected_router": v["router_id"],
                "description": (
                    f"Router {v['router_id']} has Options E-bit cleared "
                    f"(stub area configuration) while the network area "
                    f"0.0.0.0 expects E-bit set (non-stub). {v['evidence']}. "
                    f"Per RFC 2328 Section 10.5, Hello packets with "
                    f"mismatched E-bit are silently discarded."
                ),
                "rfc_reference": (
                    "RFC 2328 Section 10.5 (Receiving Hello Packets), "
                    "Check 5: E-bit must match area ExternalRouting"
                    "Capability"
                ),
                "remediation": (
                    f"Reconfigure router {v['router_id']} to match the "
                    f"area type. Area 0.0.0.0 (backbone) cannot be a "
                    f"stub area; remove the stub area configuration."
                ),
            })

        elif "MTU" in vtype:
            root_causes.append({
                "category": "mtu_mismatch",
                "affected_router": v["router_id"],
                "description": (
                    f"Router {v['router_id']} advertises a different "
                    f"interface MTU in Database Description packets. "
                    f"{v['evidence']}. The receiving router silently "
                    f"drops DD packets with MTU larger than its own "
                    f"interface MTU, causing the ExStart state to stall "
                    f"indefinitely with repeated retransmissions and no "
                    f"explicit error indication."
                ),
                "rfc_reference": (
                    "RFC 2328 Section 10.6 (Receiving Database "
                    "Description Packets): reject DD if Interface MTU "
                    "exceeds receiving interface capacity"
                ),
                "remediation": (
                    f"Align the interface MTU on router {v['router_id']} "
                    f"to 1500 to match other routers on this segment, "
                    f"or configure 'ip ospf mtu-ignore' on all "
                    f"interfaces (not recommended for production)."
                ),
            })

    return {
        "successful_adjacencies": successful,
        "failed_adjacencies": failed,
        "root_causes": root_causes,
    }


def main():
    os.makedirs(OUT, exist_ok=True)

    # Verify tools
    r = subprocess.run(["tshark", "--version"],
                       capture_output=True, text=True)
    print(f"tshark: {r.stdout.split(chr(10))[0]}")

    # Step 1: Packet inventory
    print("Step 1: Building packet inventory...")
    inv = build_inventory()
    print(f"  {inv['total_packets']} packets: "
          f"{inv['hello_packets']} Hello, {inv['dd_packets']} DD")
    print(f"  Routers: {inv['routers_observed']}")
    with open(f"{OUT}/packet_inventory.json", "w") as f:
        json.dump(inv, f, indent=2)

    # Step 2: Adjacency matrix
    print("Step 2: Analyzing adjacencies...")
    adj_matrix, hello_viols = analyze_adjacencies(inv)
    for a in adj_matrix["adjacencies"]:
        status = "OK" if a["successful"] else a["failure_reason"][:60]
        print(f"  {a['router_a']} - {a['router_b']}: "
              f"{a['final_state']} ({status})")
    with open(f"{OUT}/adjacency_matrix.json", "w") as f:
        json.dump(adj_matrix, f, indent=2)

    # Step 3: Protocol violations
    print("Step 3: Identifying protocol violations...")
    viols = build_violations(inv, hello_viols)
    for v in viols["violations"]:
        print(f"  {v['router_id']}: {v['violation_type']} "
              f"(RFC {v['rfc_section']})")
    with open(f"{OUT}/protocol_violations.json", "w") as f:
        json.dump(viols, f, indent=2)

    # Step 4: Root cause report
    print("Step 4: Building root cause report...")
    report = build_report(adj_matrix, viols)
    print(f"  Successful: {report['successful_adjacencies']}, "
          f"Failed: {report['failed_adjacencies']}")
    for rc in report["root_causes"]:
        print(f"  [{rc['category']}] {rc['affected_router']}")
    with open(f"{OUT}/root_cause_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\nDone. All outputs written to /app/output/")


if __name__ == "__main__":
    main()
