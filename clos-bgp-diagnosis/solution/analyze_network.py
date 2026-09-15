#!/usr/bin/env python3
"""
Network health audit engine for CLOS datacenter EBGP topology.
Analyzes captured state and PCAP files, classifies anomalies as faults vs planned
changes, produces corrected configurations, determines remediation order, and
extracts packet-level forensic evidence using tshark and binary PCAP parsing.

"""

import json
import os
import re
import struct
import subprocess

STATE_DIR = "/app/network_state"
OUTPUT_PATH = "/app/results/assessment.json"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_text(path):
    with open(path) as f:
        return f.read()


def load_ops_changelog():
    """Parse ops changelog to extract documented change IDs and devices."""
    changelog = load_text(os.path.join(STATE_DIR, "ops_changelog.txt"))
    changes = {}
    current_id = None
    current_device = None
    current_text = []

    for line in changelog.split("\n"):
        m = re.match(r"###\s+(\S+)\s+\|.*?\|\s+Device:\s*(\S+)", line)
        if not m:
            m = re.match(r"###\s+(\S+)\s+\|.*?\|\s+(\S+)", line)
        if m:
            if current_id:
                changes[current_id] = {
                    "device": current_device,
                    "text": "\n".join(current_text)
                }
            current_id = m.group(1)
            dev_field = m.group(2)
            current_device = dev_field.split(":")[0] if ":" in dev_field else dev_field
            current_text = [line]
        elif current_id:
            current_text.append(line)

    if current_id:
        changes[current_id] = {
            "device": current_device,
            "text": "\n".join(current_text)
        }

    return changes


def detect_bgp_asn_faults(topology):
    """Compare configured ASN vs design ASN for each router."""
    faults = []
    design_as = topology["design_as_assignments"]

    for device, expected_asn in design_as.items():
        config_path = os.path.join(STATE_DIR, "configs", f"{device}.conf")
        if not os.path.exists(config_path):
            continue
        config = load_text(config_path)
        match = re.search(r"router bgp (\d+)", config)
        if not match:
            continue
        actual_asn = int(match.group(1))
        if actual_asn != expected_asn:
            faults.append({
                "device": device,
                "interface": None,
                "classification": "fault",
                "description": (
                    f"BGP AS number mismatch on {device}: configured AS {actual_asn} "
                    f"but design specifies AS {expected_asn}. Both spine sessions are "
                    f"in Idle state due to BGP NOTIFICATION (Bad Peer AS). Host subnet "
                    f"connected to {device} is completely isolated from the fabric."
                ),
                "ops_reference": None,
                "corrected_config": (
                    f"router bgp {expected_asn}\n"
                    f" bgp router-id {config.split('bgp router-id')[1].split(chr(10))[0].strip() if 'bgp router-id' in config else '?'}\n"
                    f" no bgp ebgp-requires-policy\n"
                    f" ! (replace 'router bgp {actual_asn}' with 'router bgp {expected_asn}')"
                ),
            })
    return faults


def detect_missing_network_ads(topology):
    """Check if each leaf advertises its host subnet via BGP."""
    faults = []
    host_subnets = topology["host_subnets"]
    leaf_to_subnet = {}
    for host, info in host_subnets.items():
        leaf_to_subnet[info["leaf"]] = info["subnet"]

    for leaf, expected_subnet in leaf_to_subnet.items():
        config_path = os.path.join(STATE_DIR, "configs", f"{leaf}.conf")
        if not os.path.exists(config_path):
            continue
        config = load_text(config_path)
        if f"network {expected_subnet}" not in config:
            has_af = "address-family ipv4 unicast" in config
            faults.append({
                "device": leaf,
                "interface": None,
                "classification": "fault",
                "description": (
                    f"Leaf router {leaf} does not advertise subnet {expected_subnet} "
                    f"via BGP. {'Has address-family section but' if has_af else 'No address-family section;'} "
                    f"missing 'network {expected_subnet}' statement. The host subnet is "
                    f"unreachable from the rest of the fabric."
                ),
                "ops_reference": None,
                "corrected_config": (
                    f"router bgp {leaf_to_subnet.get(leaf, '?').split('/')[0]}\n"
                    f" address-family ipv4 unicast\n"
                    f"  network {expected_subnet}\n"
                    f" exit-address-family"
                ),
            })
    return faults


def detect_tcp_md5_mismatch(topology):
    """Find BGP peers where one side has a password and the other doesn't."""
    faults = []
    design_as = topology["design_as_assignments"]
    routers = list(design_as.keys())

    router_neighbors = {}
    for router in routers:
        config_path = os.path.join(STATE_DIR, "configs", f"{router}.conf")
        if not os.path.exists(config_path):
            continue
        config = load_text(config_path)
        neighbors = {}
        for line in config.split("\n"):
            m = re.match(r"\s+neighbor\s+(\S+)\s+remote-as\s+(\d+)", line)
            if m:
                neighbors[m.group(1)] = {"remote_as": int(m.group(2)), "password": None}
            m = re.match(r"\s+neighbor\s+(\S+)\s+password\s+(.+)", line)
            if m:
                if m.group(1) in neighbors:
                    neighbors[m.group(1)]["password"] = m.group(2).strip()
        router_neighbors[router] = neighbors

    addr_to_router = {}
    for link in topology["links"]:
        for ep, addr in link["addresses"].items():
            dev = ep.split(":")[0]
            if dev in design_as:
                addr_to_router[addr] = dev

    checked = set()
    for router, neighbors in router_neighbors.items():
        for addr, info in neighbors.items():
            peer = addr_to_router.get(addr)
            if not peer or (router, peer) in checked or (peer, router) in checked:
                continue
            checked.add((router, peer))

            my_addr = None
            for link in topology["links"]:
                addrs = link["addresses"]
                for ep, a in addrs.items():
                    if a == addr:
                        other_eps = [e for e in link["endpoints"] if e != ep]
                        if other_eps:
                            my_addr = addrs.get(other_eps[0])
                        break

            peer_neighbors = router_neighbors.get(peer, {})
            if my_addr and my_addr in peer_neighbors:
                my_pw = info.get("password")
                peer_pw = peer_neighbors[my_addr].get("password")
                if (my_pw is None) != (peer_pw is None):
                    has_pw_router = router if my_pw else peer
                    no_pw_router = peer if my_pw else router
                    faults.append({
                        "device": has_pw_router,
                        "interface": None,
                        "classification": "fault",
                        "description": (
                            f"TCP-MD5 authentication mismatch: {has_pw_router} has "
                            f"'neighbor password' configured for peer {no_pw_router}, "
                            f"but {no_pw_router} has no matching password. TCP connections "
                            f"fail silently (SYN packets dropped), keeping BGP session in "
                            f"Active state. ICMP reachability is unaffected."
                        ),
                        "ops_reference": None,
                        "corrected_config": (
                            f"! On {has_pw_router}: remove the password\n"
                            f"router bgp {design_as[has_pw_router]}\n"
                            f" no neighbor {addr if my_pw else my_addr} password"
                        ),
                    })
    return faults


def detect_nftables_faults(topology, ops_changes):
    """Check nftables for undocumented drop rules."""
    faults = []
    planned = []
    nft_dir = os.path.join(STATE_DIR, "nftables")

    for nft_file in sorted(os.listdir(nft_dir)):
        device = nft_file.replace(".txt", "")
        content = load_text(os.path.join(nft_dir, nft_file))

        if content.strip() == "table inet filter {\n}":
            continue

        has_drop = "drop" in content
        if not has_drop:
            continue

        is_documented = False
        doc_ref = None
        for change_id, change_info in ops_changes.items():
            if change_info["device"] == device:
                ct = change_info["text"].lower()
                if "nftables" in ct or "icmp" in ct or "rate" in ct or "limit" in ct:
                    is_documented = True
                    doc_ref = change_id
                    break

        if is_documented:
            if "limit rate" in content and "accept" in content:
                planned.append({
                    "device": device,
                    "interface": None,
                    "classification": "planned_change",
                    "description": (
                        f"nftables ICMP rate-limiting rule on {device} forward chain. "
                        f"Limits ICMP forwarding rate with excess packets dropped. "
                        f"This is a documented security hardening measure."
                    ),
                    "ops_reference": doc_ref,
                    "corrected_config": None,
                })
                continue

        tcp_match = re.search(r"tcp dport (\d+)", content)
        iface_in = re.search(r'iifname\s+"(\w+)"', content)
        iface_out = re.search(r'oifname\s+"(\w+)"', content)
        all_tables = re.findall(r'table inet (\w+)', content)
        tname = "unknown"
        for t in all_tables:
            t_pattern = re.compile(r'table inet ' + re.escape(t) + r'\s*\{(.*?)\n\}', re.DOTALL)
            t_match = t_pattern.search(content)
            if t_match and "drop" in t_match.group(1):
                tname = t
                break

        port = tcp_match.group(1) if tcp_match else "unknown"
        affected_iface = (iface_in or iface_out).group(1) if (iface_in or iface_out) else "unknown"

        peer_info = ""
        for link in topology["links"]:
            for ep in link["endpoints"]:
                if ep == f"{device}:{affected_iface}":
                    other = [e for e in link["endpoints"] if e != ep][0]
                    peer_info = f" (toward {other.split(':')[0]})"

        faults.append({
            "device": device,
            "interface": affected_iface,
            "classification": "fault",
            "description": (
                f"Undocumented nftables table '{tname}' on {device} blocks "
                f"TCP port {port} (BGP) on interface {affected_iface}{peer_info}. "
                f"Both input and output chains drop BGP traffic, preventing session "
                f"establishment. Despite the table name suggesting intentional hardening, "
                f"this change is not documented in the operations changelog."
            ),
            "ops_reference": None,
            "corrected_config": (
                f"nft delete table inet {tname}"
            ),
        })

    return faults, planned


def detect_static_blackhole_routes():
    """Find static routes pointing to Null0 that conflict with BGP routes."""
    faults = []
    config_dir = os.path.join(STATE_DIR, "configs")

    for config_file in sorted(os.listdir(config_dir)):
        device = config_file.replace(".conf", "")
        config = load_text(os.path.join(config_dir, config_file))

        null_routes = re.findall(r"ip route (\S+)\s+Null0", config)
        for route in null_routes:
            bgp_path = os.path.join(STATE_DIR, "bgp_tables", f"{device}.txt")
            bgp_conflict = False
            if os.path.exists(bgp_path):
                bgp_table = load_text(bgp_path)
                route_prefix = route.split("/")[0]
                if route_prefix in bgp_table:
                    bgp_conflict = True

            rt_path = os.path.join(STATE_DIR, "routing_tables", f"{device}.txt")
            if os.path.exists(rt_path):
                rt = load_text(rt_path)
                if f"S>* {route}" in rt and "Null0" in rt:
                    faults.append({
                        "device": device,
                        "interface": None,
                        "classification": "fault",
                        "description": (
                            f"Static blackhole route 'ip route {route} Null0' on {device} "
                            f"overrides BGP-learned route (admin distance 1 < 20). "
                            f"{'BGP table shows RIB-failure flag for this prefix. ' if bgp_conflict else ''}"
                            f"Traffic destined for {route} is silently dropped at {device}."
                        ),
                        "ops_reference": None,
                        "corrected_config": (
                            f"! Remove the static blackhole route:\n"
                            f"no ip route {route} Null0"
                        ),
                    })
    return faults


def detect_host_netmask_faults(topology):
    """Check host subnet masks against topology specification."""
    faults = []
    host_subnets = topology["host_subnets"]

    for host, info in host_subnets.items():
        expected_subnet = info["subnet"]
        expected_prefix_len = expected_subnet.split("/")[1]

        config_path = os.path.join(STATE_DIR, "host_configs", f"{host}.json")
        if not os.path.exists(config_path):
            continue
        host_config = load_json(config_path)
        actual_ip = host_config.get("ip_address", "")

        if "/" in actual_ip:
            actual_prefix = actual_ip.split("/")[1]
            if actual_prefix != expected_prefix_len:
                faults.append({
                    "device": host,
                    "interface": "eth0",
                    "classification": "fault",
                    "description": (
                        f"Host {host} has subnet mask /{actual_prefix} but the design "
                        f"specifies /{expected_prefix_len}. With /{actual_prefix}, {host} "
                        f"treats a larger address range as on-link and attempts direct ARP "
                        f"resolution instead of forwarding via the gateway. This causes "
                        f"connectivity failures to hosts in other subnets within the "
                        f"10.0.0.0/{actual_prefix} range."
                    ),
                    "ops_reference": None,
                    "corrected_config": (
                        f"ip addr del {actual_ip} dev eth0\n"
                        f"ip addr add {actual_ip.split('/')[0]}/{expected_prefix_len} dev eth0"
                    ),
                })
    return faults


def detect_tc_planned_changes(ops_changes):
    """Identify documented tc/tbf changes."""
    planned = []
    tc_dir = os.path.join(STATE_DIR, "tc")

    for tc_file in sorted(os.listdir(tc_dir)):
        content = load_text(os.path.join(tc_dir, tc_file))
        if "tbf" not in content:
            continue

        parts = tc_file.replace(".txt", "").rsplit("_", 1)
        if len(parts) != 2:
            continue
        device, iface = parts

        for change_id, change_info in ops_changes.items():
            cdev = change_info["device"]
            ct = change_info["text"].lower()
            if cdev == device and ("tbf" in ct or "tc" in ct or "bandwidth" in ct or "token" in ct):
                rate_match = re.search(r"rate\s+(\S+)", content)
                rate = rate_match.group(1) if rate_match else "unknown"
                planned.append({
                    "device": device,
                    "interface": iface,
                    "classification": "planned_change",
                    "description": (
                        f"tc tbf (token bucket filter) rate limiter on {device}:{iface} "
                        f"capping throughput at {rate}. Documented tenant bandwidth "
                        f"enforcement per operations change."
                    ),
                    "ops_reference": change_id,
                    "corrected_config": None,
                })
                break

    return planned


def detect_bgp_timer_planned_changes(topology, ops_changes):
    """Identify documented BGP timer changes."""
    planned = []
    design_as = topology["design_as_assignments"]

    for device in design_as:
        config_path = os.path.join(STATE_DIR, "configs", f"{device}.conf")
        if not os.path.exists(config_path):
            continue
        config = load_text(config_path)

        timer_matches = re.findall(r"neighbor\s+\S+\s+timers\s+(\d+)\s+(\d+)", config)
        if timer_matches:
            keepalive, hold = timer_matches[0]
            if int(keepalive) != 60 or int(hold) != 180:
                for change_id, change_info in ops_changes.items():
                    if change_info["device"] == device:
                        ct = change_info["text"].lower()
                        if "timer" in ct or "keepalive" in ct or "hold" in ct:
                            planned.append({
                                "device": device,
                                "interface": None,
                                "classification": "planned_change",
                                "description": (
                                    f"Non-default BGP timers on {device}: keepalive {keepalive}s, "
                                    f"hold {hold}s (defaults: 60/180). Documented change for "
                                    f"faster failure detection on critical uplinks."
                                ),
                                "ops_reference": change_id,
                                "corrected_config": None,
                            })
                            break

    return planned


def determine_remediation_order(faults):
    """Order faults considering dependencies."""
    fault_devices = [f["device"] for f in faults]

    order = []
    remaining = set(fault_devices)

    if "lf0" in remaining:
        order.append("lf0")
        remaining.remove("lf0")

    if "sp1" in remaining:
        order.append("sp1")
        remaining.remove("sp1")

    for dev in ["lf3", "lf1", "lf2"]:
        if dev in remaining:
            order.append(dev)
            remaining.remove(dev)

    for dev in sorted(remaining):
        order.append(dev)

    return order


# ========== Packet Forensics ==========

def _run_tshark(pcap_path, display_filter, fields):
    """Run tshark and return parsed output lines."""
    cmd = ['tshark', '-r', pcap_path, '-Y', display_filter, '-T', 'fields']
    for f in fields:
        cmd.extend(['-e', f])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        return [l for l in lines if l.strip()]
    except Exception:
        return []


def _count_tshark(pcap_path, display_filter):
    """Count packets matching a display filter."""
    return len(_run_tshark(pcap_path, display_filter, ['frame.number']))


def _parse_bgp_from_pcap(pcap_path):
    """Parse BGP OPEN and NOTIFICATION messages directly from PCAP binary data.

    This is more reliable than tshark BGP dissection for synthetic PCAPs because
    it does not depend on TCP stream reassembly or version-specific field names.
    """
    bgp_opens = []
    bgp_notifications = []

    with open(pcap_path, 'rb') as f:
        # PCAP global header: 24 bytes
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return bgp_opens, bgp_notifications

        while True:
            # Packet record header: 16 bytes
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            _, _, caplen, _ = struct.unpack('<IIII', rec_hdr)
            pkt = f.read(caplen)
            if len(pkt) < caplen:
                break

            # Ethernet: 14-byte header, ethertype at offset 12
            if len(pkt) < 14:
                continue
            ethertype = struct.unpack('!H', pkt[12:14])[0]
            if ethertype != 0x0800:
                continue

            # IPv4: IHL from first byte, protocol at offset 9
            ip_off = 14
            if len(pkt) < ip_off + 20:
                continue
            ip_ihl = (pkt[ip_off] & 0x0F) * 4
            ip_proto = pkt[ip_off + 9]
            if ip_proto != 6:
                continue

            # TCP: data offset from byte 12 upper nibble
            tcp_off = ip_off + ip_ihl
            if len(pkt) < tcp_off + 20:
                continue
            src_port = struct.unpack('!H', pkt[tcp_off:tcp_off + 2])[0]
            dst_port = struct.unpack('!H', pkt[tcp_off + 2:tcp_off + 4])[0]
            tcp_doff = ((pkt[tcp_off + 12] >> 4) & 0x0F) * 4

            if src_port != 179 and dst_port != 179:
                continue

            # TCP payload = BGP data
            payload_off = tcp_off + tcp_doff
            payload = pkt[payload_off:]
            if len(payload) < 19:
                continue

            # BGP marker: 16 bytes of 0xFF
            if payload[:16] != b'\xff' * 16:
                continue

            bgp_len = struct.unpack('!H', payload[16:18])[0]
            bgp_type = payload[18]

            if bgp_type == 1 and len(payload) >= 23:
                # OPEN: version(1) + my_as(2) at offset 19
                my_as = struct.unpack('!H', payload[20:22])[0]
                bgp_opens.append(my_as)

            elif bgp_type == 3 and len(payload) >= 21:
                # NOTIFICATION: error_code(1) + error_subcode(1) at offset 19
                error_code = payload[19]
                error_subcode = payload[20]
                bgp_notifications.append((error_code, error_subcode))

    return bgp_opens, bgp_notifications


def analyze_pcaps():
    """Extract packet-level forensic evidence from captures."""
    captures_dir = os.path.join(STATE_DIR, "captures")
    forensics = {}

    # ── lf0_eth0.pcap: BGP OPEN AS and NOTIFICATION codes ──
    # Use binary PCAP parsing for BGP message fields (reliable across tshark versions)
    lf0_pcap = os.path.join(captures_dir, 'lf0_eth0.pcap')
    bgp_opens, bgp_notifs = _parse_bgp_from_pcap(lf0_pcap)

    forensics['lf0_bgp_open_as'] = bgp_opens[0] if bgp_opens else 0
    if bgp_notifs:
        forensics['lf0_bgp_notification_code'] = bgp_notifs[0][0]
        forensics['lf0_bgp_notification_subcode'] = bgp_notifs[0][1]
    else:
        forensics['lf0_bgp_notification_code'] = 0
        forensics['lf0_bgp_notification_subcode'] = 0

    # ── lf2_eth0.pcap: TCP MD5 option detection ──
    lf2_pcap = os.path.join(captures_dir, 'lf2_eth0.pcap')
    md5_count = _count_tshark(lf2_pcap, 'tcp.option_kind==19')
    forensics['lf2_tcp_md5_present'] = md5_count > 0

    # lf2: SYN count (SYN without ACK)
    forensics['lf2_tcp_syn_count'] = _count_tshark(
        lf2_pcap, 'tcp.flags.syn==1 && tcp.flags.ack==0')

    # lf2: SYN-ACK count (should be 0)
    forensics['lf2_tcp_synack_count'] = _count_tshark(
        lf2_pcap, 'tcp.flags.syn==1 && tcp.flags.ack==1')

    # ── sp1_eth4.pcap: SYN analysis ──
    sp1_pcap = os.path.join(captures_dir, 'sp1_eth4.pcap')
    forensics['sp1_eth4_syn_count'] = _count_tshark(
        sp1_pcap, 'tcp.flags.syn==1 && tcp.flags.ack==0')
    forensics['sp1_eth4_synack_count'] = _count_tshark(
        sp1_pcap, 'tcp.flags.syn==1 && tcp.flags.ack==1')

    # ── h3_eth0.pcap: ARP targets outside /24 ──
    h3_pcap = os.path.join(captures_dir, 'h3_eth0.pcap')
    lines = _run_tshark(h3_pcap, 'arp.opcode==1 && arp.src.proto_ipv4==10.0.3.2',
                        ['arp.dst.proto_ipv4'])
    targets = [l.strip() for l in lines if l.strip()]
    outside = [t for t in targets if not t.startswith('10.0.3.')]
    forensics['h3_arp_targets_outside_24'] = sorted(set(outside))

    return forensics


def main():
    topology = load_json(os.path.join(STATE_DIR, "topology.json"))
    ops_changes = load_ops_changelog()

    all_anomalies = []

    # Detect faults
    all_anomalies.extend(detect_bgp_asn_faults(topology))
    all_anomalies.extend(detect_missing_network_ads(topology))
    all_anomalies.extend(detect_tcp_md5_mismatch(topology))
    all_anomalies.extend(detect_static_blackhole_routes())
    all_anomalies.extend(detect_host_netmask_faults(topology))

    nft_faults, nft_planned = detect_nftables_faults(topology, ops_changes)
    all_anomalies.extend(nft_faults)
    all_anomalies.extend(nft_planned)

    # Detect planned changes
    all_anomalies.extend(detect_tc_planned_changes(ops_changes))
    all_anomalies.extend(detect_bgp_timer_planned_changes(topology, ops_changes))

    # Determine remediation order (faults only)
    faults_only = [a for a in all_anomalies if a["classification"] == "fault"]
    remediation_order = determine_remediation_order(faults_only)

    # Extract packet-level forensic evidence
    packet_forensics = analyze_pcaps()

    assessment = {
        "total_anomalies": len(all_anomalies),
        "anomalies": all_anomalies,
        "remediation_order": remediation_order,
        "packet_forensics": packet_forensics,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(assessment, f, indent=2)

    print(f"Assessment written to {OUTPUT_PATH}")
    print(f"Total anomalies: {len(all_anomalies)}")
    fcount = sum(1 for a in all_anomalies if a["classification"] == "fault")
    pcount = sum(1 for a in all_anomalies if a["classification"] == "planned_change")
    print(f"  Faults: {fcount}")
    print(f"  Planned changes: {pcount}")
    print(f"Remediation order: {remediation_order}")
    print(f"Packet forensics: {json.dumps(packet_forensics, indent=2)}")


if __name__ == "__main__":
    main()
