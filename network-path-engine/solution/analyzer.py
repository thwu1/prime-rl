#!/usr/bin/env python3
"""
Reconstruct multi-stage intrusion from distributed packet captures.
Reads 4 pcap files + topology, produces /app/report.json.
"""

import base64
import json
from collections import defaultdict
from scapy.all import rdpcap, TCP, UDP, ARP, DNS, DNSQR, Dot1Q, Raw, IP, conf

conf.verb = 0


def load_topology():
    with open("/app/topology.json") as f:
        return json.load(f)


def b64_decode_label(label):
    """Decode a base64 DNS label (re-add stripped padding)."""
    pad = (4 - len(label) % 4) % 4
    return base64.b64decode(label + "=" * pad).decode()


# ---------------------------------------------------------------------------
# Perimeter analysis — external recon + exploit
# ---------------------------------------------------------------------------
def analyze_perimeter(path):
    pkts = rdpcap(path)
    result = {"packet_count": len(pkts), "tcp": 0, "udp": 0, "arp": 0,
              "syn_scan": None, "http_exploit": None}

    syn_targets = {}  # (src,dst) -> {port: status}

    for pkt in pkts:
        if pkt.haslayer(TCP):
            result["tcp"] += 1
            tcp = pkt[TCP]
            ip = pkt[IP]

            if str(tcp.flags) == "S":
                key = (ip.src, ip.dst)
                syn_targets.setdefault(key, {})[tcp.dport] = "sent"
            elif str(tcp.flags) == "SA":
                key = (ip.dst, ip.src)
                if key in syn_targets and tcp.sport in syn_targets[key]:
                    syn_targets[key][tcp.sport] = "open"
            elif "R" in str(tcp.flags):
                key = (ip.dst, ip.src)
                if key in syn_targets and tcp.sport in syn_targets[key]:
                    syn_targets[key][tcp.sport] = "closed"

            if pkt.haslayer(Raw) and tcp.dport == 80:
                payload = pkt[Raw].load.decode("utf-8", errors="ignore")
                if "/../" in payload or "{ :;}" in payload:
                    result["http_exploit"] = {
                        "source_ip": ip.src, "target_ip": ip.dst}
        elif pkt.haslayer(UDP):
            result["udp"] += 1
        elif pkt.haslayer(ARP):
            result["arp"] += 1

    for (src, dst), ports in syn_targets.items():
        if len(ports) >= 3:
            result["syn_scan"] = {
                "source_ip": src, "target_ip": dst,
                "ports_scanned": sorted(ports.keys()),
                "ports_open": sorted(p for p, s in ports.items() if s == "open"),
                "ports_closed": sorted(p for p, s in ports.items() if s == "closed"),
            }
    return result


# ---------------------------------------------------------------------------
# DMZ analysis — C2 DNS tunneling
# ---------------------------------------------------------------------------
def analyze_dmz(path):
    pkts = rdpcap(path)
    result = {"packet_count": len(pkts), "tcp": 0, "udp": 0, "arp": 0,
              "dns_tunneling": None}

    tunnel_queries = []

    for pkt in pkts:
        if pkt.haslayer(TCP):
            result["tcp"] += 1
        elif pkt.haslayer(UDP):
            result["udp"] += 1
            if pkt.haslayer(DNS) and pkt[DNS].qr == 0 and pkt[DNS].qd:
                qname = pkt[DNS].qd.qname.decode().rstrip(".")
                if pkt[DNS].qd.qtype == 16:  # TXT
                    parts = qname.split(".")
                    if len(parts) >= 4:
                        tunnel_queries.append({
                            "source_ip": pkt[IP].src,
                            "label": parts[0],
                            "domain": ".".join(parts[1:]),
                        })
        elif pkt.haslayer(ARP):
            result["arp"] += 1

    domains = defaultdict(list)
    for q in tunnel_queries:
        domains[q["domain"]].append(q)

    tunnels = []
    for domain, queries in domains.items():
        if len(queries) >= 2:
            tunnels.append({
                "domain": domain,
                "source_ip": queries[0]["source_ip"],
                "query_count": len(queries),
                "labels": [q["label"] for q in queries],
            })
    if tunnels:
        result["dns_tunneling"] = tunnels
    return result


# ---------------------------------------------------------------------------
# Core switch analysis — cross-VLAN traffic with 802.1Q
# ---------------------------------------------------------------------------
def analyze_core(path, topology):
    pkts = rdpcap(path)
    result = {"packet_count": len(pkts), "tcp": 0, "udp": 0, "arp": 0,
              "cross_vlan": [], "internal_scan": None,
              "lateral_movement": None, "data_access": None}

    host_vlans = {h["ip"]: h["vlan"] for h in topology["hosts"]}
    scan_targets = defaultdict(list)
    cross_vlan_conns = []

    for pkt in pkts:
        if pkt.haslayer(TCP):
            result["tcp"] += 1
            if pkt.haslayer(Dot1Q) and pkt.haslayer(IP):
                ip = pkt[IP]
                tcp = pkt[TCP]
                src_vlan = host_vlans.get(ip.src)
                dst_vlan = host_vlans.get(ip.dst)

                if str(tcp.flags) == "S":
                    if tcp.dport == 22:
                        scan_targets[ip.src].append(ip.dst)
                    if tcp.dport == 3306:
                        result["data_access"] = {
                            "source_ip": ip.src, "target_ip": ip.dst,
                            "port": 3306}
                    if src_vlan and dst_vlan and src_vlan != dst_vlan:
                        cross_vlan_conns.append({
                            "src": ip.src, "dst": ip.dst,
                            "src_vlan": src_vlan, "dst_vlan": dst_vlan})

                if str(tcp.flags) == "A" and tcp.dport == 22:
                    result["lateral_movement"] = {
                        "source_ip": ip.src, "target_ip": ip.dst,
                        "port": 22}
        elif pkt.haslayer(UDP):
            result["udp"] += 1
        elif pkt.haslayer(ARP):
            result["arp"] += 1

    for scanner, targets in scan_targets.items():
        unique = list(dict.fromkeys(targets))
        if len(unique) >= 3:
            result["internal_scan"] = {
                "source_ip": scanner, "targets": unique, "port": 22}
    result["cross_vlan"] = cross_vlan_conns
    return result


# ---------------------------------------------------------------------------
# Internal monitor analysis — exfiltration + ARP poisoning
# ---------------------------------------------------------------------------
def analyze_internal(path, topology):
    pkts = rdpcap(path)
    result = {"packet_count": len(pkts), "tcp": 0, "udp": 0, "arp": 0,
              "exfil_dns": None, "arp_poisoning": None}

    gw_mac, gw_ip = None, None
    for v in topology["vlans"]:
        if v["id"] == 200:
            gw_mac = v["gateway"]["mac"].lower()
            gw_ip = v["gateway"]["ip"]
            break

    dns_queries = []
    arp_entries = defaultdict(set)  # ip -> set of macs

    for pkt in pkts:
        if pkt.haslayer(TCP):
            result["tcp"] += 1
        elif pkt.haslayer(UDP):
            result["udp"] += 1
            if pkt.haslayer(DNS) and pkt[DNS].qr == 0 and pkt[DNS].qd:
                if pkt[DNS].qd.qtype == 16:
                    qname = pkt[DNS].qd.qname.decode().rstrip(".")
                    parts = qname.split(".")
                    if len(parts) >= 4:
                        dns_queries.append({
                            "source_ip": pkt[IP].src,
                            "label": parts[0],
                            "domain": ".".join(parts[1:]),
                        })
        elif pkt.haslayer(ARP):
            result["arp"] += 1
            arp_entries[pkt[ARP].psrc].add(pkt[ARP].hwsrc.lower())

    # Decode exfiltration
    exfil_domains = defaultdict(list)
    for q in dns_queries:
        exfil_domains[q["domain"]].append(q)

    for domain, queries in exfil_domains.items():
        if len(queries) >= 2:
            labels = [q["label"] for q in queries]
            try:
                decoded = "".join(b64_decode_label(l) for l in labels)
                result["exfil_dns"] = {
                    "domain": domain,
                    "source_ip": queries[0]["source_ip"],
                    "decoded_data": decoded,
                    "query_count": len(queries),
                }
            except Exception:
                pass

    # Detect ARP poisoning
    if gw_ip and gw_ip in arp_entries:
        macs = arp_entries[gw_ip]
        if len(macs) > 1 and gw_mac in macs:
            rogue = macs - {gw_mac}
            result["arp_poisoning"] = {
                "spoofed_ip": gw_ip,
                "legitimate_mac": gw_mac,
                "attacker_macs": sorted(rogue),
            }
    return result


# ---------------------------------------------------------------------------
# Build final report
# ---------------------------------------------------------------------------
def build_report(perim, dmz, core, internal, topology):
    report = {}

    # --- Timeline ---
    timeline = []
    if perim["syn_scan"]:
        s = perim["syn_scan"]
        timeline.append({
            "phase": "reconnaissance",
            "source_ip": s["source_ip"],
            "target": s["target_ip"],
            "technique": (f"TCP SYN scan on ports {s['ports_scanned']}; "
                          f"open={s['ports_open']}, closed={s['ports_closed']}"),
        })
    if perim["http_exploit"]:
        e = perim["http_exploit"]
        timeline.append({
            "phase": "initial_access",
            "source_ip": e["source_ip"],
            "target": e["target_ip"],
            "technique": "HTTP path traversal and command injection exploit",
        })
    if dmz["dns_tunneling"]:
        for t in dmz["dns_tunneling"]:
            timeline.append({
                "phase": "c2_establishment",
                "source_ip": t["source_ip"],
                "target": "10.0.1.53",
                "technique": f"DNS TXT tunneling via {t['domain']}",
            })
    if core["internal_scan"]:
        s = core["internal_scan"]
        timeline.append({
            "phase": "internal_reconnaissance",
            "source_ip": s["source_ip"],
            "target": s["targets"],
            "technique": f"Internal SSH port scan on port {s['port']}",
        })
    if core["lateral_movement"]:
        lm = core["lateral_movement"]
        timeline.append({
            "phase": "lateral_movement",
            "source_ip": lm["source_ip"],
            "target": lm["target_ip"],
            "technique": f"SSH login to {lm['target_ip']}:{lm['port']}",
        })
    if core["data_access"]:
        da = core["data_access"]
        timeline.append({
            "phase": "data_access",
            "source_ip": da["source_ip"],
            "target": da["target_ip"],
            "technique": f"MySQL database access on port {da['port']}",
        })
    if internal["exfil_dns"]:
        ex = internal["exfil_dns"]
        timeline.append({
            "phase": "data_exfiltration",
            "source_ip": ex["source_ip"],
            "target": "10.0.1.53",
            "technique": f"DNS TXT tunneling via {ex['domain']}",
        })
    if internal["arp_poisoning"]:
        ap = internal["arp_poisoning"]
        attacker_ip = None
        for h in topology["hosts"]:
            if h["mac"].lower() in ap["attacker_macs"]:
                attacker_ip = h["ip"]
                break
        timeline.append({
            "phase": "persistence",
            "source_ip": attacker_ip or "unknown",
            "target": ap["spoofed_ip"],
            "technique": (f"ARP cache poisoning - spoofing gateway "
                          f"{ap['spoofed_ip']} with MAC {ap['attacker_macs'][0]}"),
        })
    report["attack_timeline"] = timeline

    # --- Attacker infrastructure ---
    ext_ip = perim["syn_scan"]["source_ip"] if perim["syn_scan"] else "unknown"
    c2_domains = [t["domain"] for t in (dmz["dns_tunneling"] or [])]
    exfil_domains = ([internal["exfil_dns"]["domain"]]
                     if internal["exfil_dns"] else [])
    report["attacker_infrastructure"] = {
        "external_ip": ext_ip,
        "c2_domains": c2_domains,
        "exfil_domains": exfil_domains,
    }

    # --- Compromised hosts ---
    compromised = []
    if perim["http_exploit"]:
        compromised.append({
            "ip": perim["http_exploit"]["target_ip"],
            "method": "web_exploit",
        })
    if core["lateral_movement"]:
        compromised.append({
            "ip": core["lateral_movement"]["target_ip"],
            "method": "ssh_lateral_movement",
        })
    report["compromised_hosts"] = compromised

    # --- Exfiltrated data ---
    report["exfiltrated_data"] = (
        internal["exfil_dns"]["decoded_data"] if internal["exfil_dns"] else "")

    # --- Network anomalies ---
    anomalies = []
    if perim["syn_scan"]:
        anomalies.append({
            "type": "syn_scan",
            "details": {
                "source": perim["syn_scan"]["source_ip"],
                "target": perim["syn_scan"]["target_ip"],
                "ports": perim["syn_scan"]["ports_scanned"],
            },
        })
    if dmz["dns_tunneling"] or internal["exfil_dns"]:
        tunnel_doms = [t["domain"] for t in (dmz["dns_tunneling"] or [])]
        if internal["exfil_dns"]:
            tunnel_doms.append(internal["exfil_dns"]["domain"])
        hosts = list(set(
            [t["source_ip"] for t in (dmz["dns_tunneling"] or [])] +
            ([internal["exfil_dns"]["source_ip"]]
             if internal["exfil_dns"] else [])
        ))
        anomalies.append({
            "type": "dns_tunneling",
            "details": {"domains": tunnel_doms, "hosts": hosts},
        })
    if core["cross_vlan"]:
        anomalies.append({
            "type": "cross_vlan_access",
            "details": {"connections": [
                {"src": c["src"], "dst": c["dst"],
                 "src_vlan": c["src_vlan"], "dst_vlan": c["dst_vlan"]}
                for c in core["cross_vlan"]
            ]},
        })
    if internal["arp_poisoning"]:
        ap = internal["arp_poisoning"]
        anomalies.append({
            "type": "arp_poisoning",
            "details": {
                "spoofed_ip": ap["spoofed_ip"],
                "legitimate_mac": ap["legitimate_mac"],
                "attacker_mac": ap["attacker_macs"][0],
            },
        })
    report["network_anomalies"] = anomalies

    # --- Indicators of compromise ---
    all_domains = c2_domains + exfil_domains
    report["indicators_of_compromise"] = {
        "malicious_ips": [ext_ip],
        "malicious_domains": all_domains,
        "compromised_ips": [h["ip"] for h in compromised],
        "targeted_services": (
            [{"ip": core["data_access"]["target_ip"],
              "port": core["data_access"]["port"]}]
            if core["data_access"] else []
        ),
    }

    # --- Traffic summary ---
    captures = [perim, dmz, core, internal]
    report["traffic_summary"] = {
        "total_packets": sum(c["packet_count"] for c in captures),
        "per_capture": {
            "perimeter": perim["packet_count"],
            "dmz_switch": dmz["packet_count"],
            "core_switch": core["packet_count"],
            "internal_monitor": internal["packet_count"],
        },
        "protocol_counts": {
            "tcp": sum(c["tcp"] for c in captures),
            "udp": sum(c["udp"] for c in captures),
            "arp": sum(c["arp"] for c in captures),
        },
    }

    return report


def main():
    topology = load_topology()
    perim = analyze_perimeter("/app/captures/perimeter.pcap")
    dmz = analyze_dmz("/app/captures/dmz_switch.pcap")
    core = analyze_core("/app/captures/core_switch.pcap", topology)
    internal = analyze_internal("/app/captures/internal_monitor.pcap", topology)

    report = build_report(perim, dmz, core, internal, topology)

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
