#!/usr/bin/env python3
"""
Network incident forensics, traffic analysis, and remediation design.

Phase 1: Parse diagnostic text files for kernel/socket/log data.
Phase 2: Analyze pcap with tshark to classify attack traffic.
Phase 3: Apply policy formulas to design remediation configuration.
Phase 4: Generate nftables mitigation ruleset.
"""

import json
import os
import re
import subprocess

DATA_DIR = "/app/data"


def read_file(name):
    with open(os.path.join(DATA_DIR, name), "r") as f:
        return f.read()


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Diagnostic file parsing
# ═══════════════════════════════════════════════════════════════════

def parse_sysctl(content):
    result = {}
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def parse_iptables_chain_packets(content, chain_name="PREROUTING"):
    in_chain = False
    header_seen = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Chain {}".format(chain_name)):
            in_chain = True
            header_seen = False
            continue
        if in_chain:
            if stripped.startswith("pkts"):
                header_seen = True
                continue
            if header_seen and stripped:
                parts = stripped.split()
                if parts:
                    return int(parts[0])
            if stripped.startswith("Chain ") and chain_name not in stripped:
                in_chain = False
    return 0


def parse_nstat(content):
    result = {}
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return result


def parse_ss_listen(content):
    lines = content.strip().split("\n")
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "LISTEN":
            recv_q = int(parts[1])
            send_q = int(parts[2])
            addr_port = parts[3]
            port = int(addr_port.rsplit(":", 1)[1])
            if recv_q > send_q:
                return port, send_q
    return None, None


def parse_ss_outbound(content):
    result = {}
    for line in content.split("\n"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def count_timewait(content):
    count = 0
    for line in content.strip().split("\n"):
        if line.strip().startswith("TIME-WAIT"):
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════════
# Phase 2: PCAP analysis with tshark
# ═══════════════════════════════════════════════════════════════════

def run_tshark(args):
    """Run a tshark command and return stdout."""
    cmd = ["tshark"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout


def analyze_pcap(pcap_path):
    """Analyze traffic capture to identify attack sources and compute metrics."""

    # Extract all SYN-only packets (SYN=1, ACK=0) with source IP
    syn_only_output = run_tshark([
        "-r", pcap_path,
        "-Y", "tcp.flags.syn==1 && tcp.flags.ack==0",
        "-T", "fields", "-e", "ip.src",
    ])
    syn_only_ips = [ip.strip() for ip in syn_only_output.strip().split("\n")
                    if ip.strip()]

    # Extract SYN-ACK packets (SYN=1, ACK=1) with destination IP
    synack_output = run_tshark([
        "-r", pcap_path,
        "-Y", "tcp.flags.syn==1 && tcp.flags.ack==1",
        "-T", "fields", "-e", "ip.dst",
    ])
    synack_dst_ips = [ip.strip() for ip in synack_output.strip().split("\n")
                      if ip.strip()]

    # Extract UDP sources with src port 53 (DNS reflection)
    udp_dns_output = run_tshark([
        "-r", pcap_path,
        "-Y", "udp.srcport==53",
        "-T", "fields", "-e", "ip.src",
    ])
    udp_dns_ips = [ip.strip() for ip in udp_dns_output.strip().split("\n")
                   if ip.strip()]

    # Group SYN-only source IPs by /24
    syn_by_subnet = {}
    for ip in syn_only_ips:
        octets = ip.split(".")
        subnet = ".".join(octets[:3]) + ".0/24"
        syn_by_subnet[subnet] = syn_by_subnet.get(subnet, 0) + 1

    # Group SYN-ACK destination IPs by /24
    synack_subnets = set()
    for ip in synack_dst_ips:
        octets = ip.split(".")
        subnet = ".".join(octets[:3]) + ".0/24"
        synack_subnets.add(subnet)

    # Classify: attack /24s have SYN-only but NO SYN-ACK responses
    attack_cidrs = sorted([
        subnet for subnet in syn_by_subnet
        if subnet not in synack_subnets
    ])

    # Count total attack SYN packets
    attack_syn_total = sum(
        syn_by_subnet[s] for s in attack_cidrs
    )

    # Count legitimate SYN packets (from non-attack subnets)
    legitimate_syns = sum(
        count for subnet, count in syn_by_subnet.items()
        if subnet not in attack_cidrs
    )

    # Legitimate SYN rate: divide by capture duration (100 seconds per policy)
    legitimate_syn_rate = round(legitimate_syns / 100)

    # Count distinct UDP reflection sources
    udp_reflection_sources = len(set(udp_dns_ips))

    return {
        "syn_flood_source_cidrs": attack_cidrs,
        "syn_flood_total_packets": attack_syn_total,
        "legitimate_syn_rate_pps": legitimate_syn_rate,
        "udp_reflection_sources": udp_reflection_sources,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Remediation design per policy
# ═══════════════════════════════════════════════════════════════════

def design_remediation(conntrack_max, syn_flood_total, legitimate_rate,
                       has_overflow, has_port_exhaustion):
    """Apply policy requirements to compute remediation configuration."""

    # Policy §1: conntrack_max = max(current * 3, attack_total)
    rec_conntrack = max(conntrack_max * 3, syn_flood_total)

    # Policy §2: syn backlog = 2048 when overflow detected
    rec_backlog = 2048 if has_overflow else None

    # Policy §3: rate limit = legitimate_rate * 10
    rec_rate = legitimate_rate * 10

    # Policy §4: port range expansion on exhaustion
    rec_range = "1024 65535" if has_port_exhaustion else None

    # Policy §3: prerouting hook at raw priority (-300, before conntrack -200)
    hook = "prerouting"
    priority = -300

    return {
        "recommended_conntrack_max": rec_conntrack,
        "recommended_syn_backlog": rec_backlog,
        "recommended_rate_limit_pps": rec_rate,
        "recommended_port_range": rec_range,
        "nftables_hook": hook,
        "nftables_priority": priority,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Generate nftables mitigation ruleset
# ═══════════════════════════════════════════════════════════════════

def write_nftables_ruleset(attack_cidrs, rate_limit_pps, hook, priority):
    """Generate nftables ruleset implementing packet-level mitigations."""
    cidr_rules = "\n".join(
        "        ip saddr {} tcp flags syn / syn,ack drop".format(cidr)
        for cidr in attack_cidrs
    )

    ruleset = (
        "#!/usr/sbin/nft -f\n"
        "# Incident mitigation ruleset\n"
        "#\n"
        "# Blocks identified SYN flood source subnets and rate-limits\n"
        "# remaining SYN traffic before connection tracking.\n"
        "\n"
        "table inet incident_mitigation {{\n"
        "    chain syn_filter {{\n"
        "        type filter hook {hook} priority {priority}; policy accept;\n"
        "\n"
        "        # Drop SYN packets from identified attack source subnets\n"
        "{cidr_rules}\n"
        "\n"
        "        # Rate limit remaining inbound SYN packets\n"
        "        tcp flags syn / syn,ack limit rate over {rate}/second drop\n"
        "    }}\n"
        "}}\n"
    ).format(
        hook=hook,
        priority=priority,
        cidr_rules=cidr_rules,
        rate=rate_limit_pps,
    )

    with open("/app/mitigation.nft", "w") as f:
        f.write(ruleset)
    print("Wrote nftables ruleset to /app/mitigation.nft")


def main():
    # ── Phase 1: Parse diagnostic files ───────────────────────────
    sysctl = parse_sysctl(read_file("sysctl_snapshot.txt"))
    raw_pkts = parse_iptables_chain_packets(
        read_file("iptables_raw.txt"), "PREROUTING")
    mangle_pkts = parse_iptables_chain_packets(
        read_file("iptables_mangle.txt"), "PREROUTING")
    nstat = parse_nstat(read_file("nstat_counters.txt"))
    overflow_port, backlog = parse_ss_listen(read_file("ss_listen.txt"))
    outbound = parse_ss_outbound(read_file("ss_outbound.txt"))
    tw_count = count_timewait(read_file("ss_timewait.txt"))
    app_log = read_file("app_errors.log")
    dmesg = read_file("dmesg_network.txt")

    conntrack_drops = raw_pkts - mangle_pkts
    conntrack_max = int(sysctl.get("net.netfilter.nf_conntrack_max", 0))

    port_range_str = sysctl.get("net.ipv4.ip_local_port_range", "32768\t60999")
    port_parts = port_range_str.split()
    port_low, port_high = int(port_parts[0]), int(port_parts[1])
    ephemeral_range_size = port_high - port_low + 1

    ports_used = int(outbound.get("total_outbound_established", 0))
    unique_dests = int(outbound.get("unique_destinations", 0))
    port_overlap = int(
        outbound.get("source_port_overlap_across_destinations", 0))

    eaddrinuse_count = app_log.count("EADDRINUSE")
    eperm_count = app_log.count("EPERM")
    conntrack_table_full = "table full" in dmesg
    eperm_caused_by_conntrack = conntrack_table_full and eperm_count > 0
    uses_bbc = port_overlap == 0 and eaddrinuse_count > 0

    root_causes = []
    if conntrack_drops > 0:
        root_causes.append("conntrack_overflow")
    if overflow_port is not None:
        root_causes.append("accept_queue_overflow")
    if ports_used / ephemeral_range_size > 0.95 or eaddrinuse_count > 0:
        root_causes.append("ephemeral_port_exhaustion")

    # ── Phase 2: PCAP traffic analysis ────────────────────────────
    pcap_path = os.path.join(DATA_DIR, "traffic_capture.pcap")
    traffic = analyze_pcap(pcap_path)

    # ── Phase 3: Remediation design ───────────────────────────────
    has_overflow = overflow_port is not None
    has_port_exhaustion = "ephemeral_port_exhaustion" in root_causes
    remediation = design_remediation(
        conntrack_max,
        traffic["syn_flood_total_packets"],
        traffic["legitimate_syn_rate_pps"],
        has_overflow,
        has_port_exhaustion,
    )

    # ── Phase 4: Generate nftables ruleset ────────────────────────
    write_nftables_ruleset(
        traffic["syn_flood_source_cidrs"],
        remediation["recommended_rate_limit_pps"],
        remediation["nftables_hook"],
        remediation["nftables_priority"],
    )

    # ── Build report ──────────────────────────────────────────────
    report = {
        # Forensic diagnosis
        "conntrack_drops": conntrack_drops,
        "conntrack_max": conntrack_max,
        "accept_overflow_port": overflow_port,
        "accept_overflow_count": nstat.get("TcpExtListenOverflows", 0),
        "listen_backlog": backlog,
        "syn_cookies_sent": nstat.get("TcpExtSyncookiesSent", 0),
        "syn_cookies_recv": nstat.get("TcpExtSyncookiesRecv", 0),
        "ephemeral_range_size": ephemeral_range_size,
        "ephemeral_ports_used": ports_used,
        "unique_outbound_destinations": unique_dests,
        "eaddrinuse_count": eaddrinuse_count,
        "eperm_count": eperm_count,
        "eperm_caused_by_conntrack": eperm_caused_by_conntrack,
        "time_wait_count": tw_count,
        "uses_bind_before_connect": uses_bbc,
        "root_causes": sorted(root_causes),
        # Traffic analysis
        "syn_flood_source_cidrs": traffic["syn_flood_source_cidrs"],
        "syn_flood_total_packets": traffic["syn_flood_total_packets"],
        "legitimate_syn_rate_pps": traffic["legitimate_syn_rate_pps"],
        "udp_reflection_sources": traffic["udp_reflection_sources"],
        # Remediation design
        "recommended_conntrack_max": remediation["recommended_conntrack_max"],
        "recommended_syn_backlog": remediation["recommended_syn_backlog"],
        "recommended_rate_limit_pps": remediation["recommended_rate_limit_pps"],
        "recommended_port_range": remediation["recommended_port_range"],
        "nftables_hook": remediation["nftables_hook"],
        "nftables_priority": remediation["nftables_priority"],
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
