#!/usr/bin/env python3
"""Audit and remediate broken OpenWrt UCI configuration for CR-2024-047.

Diagnoses defects in previous admin's partial implementation, then builds
and writes correct configurations.

Defects diagnosed:
  Network:
    1. wan_backup bound to eth2 (non-existent) — must be eth1
    2. HQ VPN AllowedIPs 0.0.0.0/0 — must be 172.16.0.0/12 (conflicts with vpn_ext)
    3. vpn_ext has placeholder private key — must use key from change request
    4. Guest policy routing rule uses wrong source subnet 10.0.30.0/24 (IoT) — must be 10.0.40.0/24
    5. ULA prefix fc00::/48 — must be fd12:3456:789a::/48 (fc00 is reserved, fd is locally assigned)
    6. ip6assign on iot and guest — must be on mgmt and corp only (IPv6 bypasses policy routing)
  Firewall:
    7. wan_backup zone missing 'list network wan_backup' — zone is disconnected
    8. vpn_hq zone has masquerade — HQ has return routes, masq hides source IPs
    9. vpn_ext zone missing masquerade — provider expects tunnel address, needs NAT
   10. guest→wan forwarding still present — guest must only exit via vpn_ext or wan_backup
   11. Missing forwardings: iot→wan_backup, mgmt→vpn_hq, mgmt→iot, corp→vpn_hq
   12. IoT restriction rules in wrong order — reject-all before allows shadows them
   13. Guest DNS redirect uses SNAT — must be DNAT for interception
   14. Missing IoT DNS redirect
   15. Missing WAN rate limit rule

"""

import os
import sys


def build_section(stype, name=None, options=None, lists=None):
    """Build a UCI section data structure."""
    return {
        'type': stype,
        'name': name,
        'options': options or [],
        'lists': lists or [],
    }


def serialize_config(sections):
    """Serialize a list of UCI sections to config file text."""
    lines = []
    for i, s in enumerate(sections):
        if i > 0:
            lines.append('')
        header = "config {}".format(s['type'])
        if s['name']:
            header += " '{}'".format(s['name'])
        lines.append(header)
        for key, value in s['options']:
            lines.append("\toption {} '{}'".format(key, value))
        for key, value in s['lists']:
            lines.append("\tlist {} '{}'".format(key, value))
    return '\n'.join(lines) + '\n'


def parse_change_request(path):
    """Extract key parameters from the change request."""
    params = {}
    with open(path) as f:
        text = f.read()
    # Extract VPN ext private key
    for line in text.split('\n'):
        if 'Private key:' in line and 'gN65' in line:
            params['vpn_ext_private_key'] = line.split(':', 1)[1].strip()
        elif 'Private key:' in line and 'yAnz' in line:
            params['vpn_hq_private_key'] = line.split(':', 1)[1].strip()
        elif 'fd12:' in line and 'ULA' in line.lower() or 'fd12:3456' in line:
            # Extract ULA prefix from the line mentioning it
            for word in line.split():
                if word.startswith('fd'):
                    params['ula_prefix'] = word.rstrip('.')
    params.setdefault('ula_prefix', 'fd12:3456:789a::/48')
    params.setdefault('vpn_ext_private_key', 'gN65BkIKy1eCE9pP1wdc8ROUgxU3ZdQbFmcqEIa7cFo=')
    return params


def build_correct_network(params):
    """Build the correct network configuration."""
    sections = []

    # Loopback
    sections.append(build_section('interface', 'loopback', [
        ('device', 'lo'), ('proto', 'static'),
        ('ipaddr', '127.0.0.1'), ('netmask', '255.255.255.0'),
    ]))

    # Globals — FIX #5: ULA prefix fc00→fd12:3456:789a
    sections.append(build_section('globals', 'globals', [
        ('ula_prefix', params['ula_prefix']),
    ]))

    # Primary WAN
    sections.append(build_section('device', options=[('name', 'eth0')]))
    sections.append(build_section('interface', 'wan', [
        ('device', 'eth0'), ('proto', 'dhcp'),
    ]))
    sections.append(build_section('interface', 'wan6', [
        ('device', 'eth0'), ('proto', 'dhcpv6'),
        ('reqaddress', 'try'), ('reqprefix', 'auto'),
    ]))

    # DSA bridge with VLAN filtering
    sections.append(build_section('device', options=[
        ('name', 'br-lan'), ('type', 'bridge'), ('vlan_filtering', '1'),
    ], lists=[
        ('ports', 'lan1'), ('ports', 'lan2'), ('ports', 'lan3'),
        ('ports', 'lan4'), ('ports', 'lan5'),
    ]))

    # VLAN assignments
    sections.append(build_section('bridge-vlan', options=[
        ('device', 'br-lan'), ('vlan', '10'),
    ], lists=[('ports', 'lan1:u*'), ('ports', 'lan2:u*')]))

    sections.append(build_section('bridge-vlan', options=[
        ('device', 'br-lan'), ('vlan', '20'),
    ], lists=[('ports', 'lan3:u*'), ('ports', 'lan4:u*')]))

    sections.append(build_section('bridge-vlan', options=[
        ('device', 'br-lan'), ('vlan', '30'),
    ], lists=[('ports', 'lan5:u*')]))

    # Management — FIX #6: ADD ip6assign (was missing)
    sections.append(build_section('interface', 'mgmt', [
        ('device', 'br-lan.10'), ('proto', 'static'),
        ('ipaddr', '10.0.10.1'), ('netmask', '255.255.255.0'),
        ('ip6assign', '64'),
    ]))

    # Corporate — FIX #6: ADD ip6assign (was missing)
    sections.append(build_section('interface', 'corp', [
        ('device', 'br-lan.20'), ('proto', 'static'),
        ('ipaddr', '10.0.20.1'), ('netmask', '255.255.255.0'),
        ('ip6assign', '64'),
    ]))

    # IoT — FIX #6: REMOVE ip6assign (was incorrectly assigned)
    sections.append(build_section('interface', 'iot', [
        ('device', 'br-lan.30'), ('proto', 'static'),
        ('ipaddr', '10.0.30.1'), ('netmask', '255.255.255.0'),
    ]))

    # Guest bridge
    sections.append(build_section('device', options=[
        ('name', 'br-guest'), ('type', 'bridge'),
    ]))

    # Guest — FIX #6: REMOVE ip6assign (was incorrectly assigned)
    sections.append(build_section('interface', 'guest', [
        ('device', 'br-guest'), ('proto', 'static'),
        ('ipaddr', '10.0.40.1'), ('netmask', '255.255.255.0'),
    ]))

    # VPN HQ interface (unchanged)
    sections.append(build_section('interface', 'vpn_hq', [
        ('proto', 'wireguard'),
        ('private_key', 'yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk='),
        ('listen_port', '51820'),
    ], lists=[('addresses', '10.0.99.2/24')]))

    # Backup WAN device — FIX #1: eth2→eth1
    sections.append(build_section('device', options=[('name', 'eth1')]))

    # Backup WAN interface — FIX #1: device eth2→eth1
    sections.append(build_section('interface', 'wan_backup', [
        ('device', 'eth1'), ('proto', 'static'),
        ('ipaddr', '100.64.0.2'), ('netmask', '255.255.255.252'),
        ('gateway', '100.64.0.1'), ('metric', '20'),
    ], lists=[('dns', '1.1.1.1'), ('dns', '8.8.8.8')]))

    # HQ VPN peer — FIX #2: AllowedIPs 0.0.0.0/0→172.16.0.0/12
    sections.append(build_section('wireguard_vpn_hq', 'hq_peer', [
        ('description', 'HQ VPN Gateway'),
        ('public_key', 'xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg='),
        ('endpoint_host', 'vpn.hq.example.com'),
        ('endpoint_port', '51820'),
        ('persistent_keepalive', '25'),
        ('route_allowed_ips', '1'),
    ], lists=[('allowed_ips', '172.16.0.0/12')]))

    # Commercial VPN interface — FIX #3: replace placeholder private key
    sections.append(build_section('interface', 'vpn_ext', [
        ('proto', 'wireguard'),
        ('private_key', params['vpn_ext_private_key']),
    ], lists=[('addresses', '10.8.0.2/24')]))

    # Commercial VPN peer
    sections.append(build_section('wireguard_vpn_ext', 'ext_peer', [
        ('description', 'Commercial VPN Provider'),
        ('public_key', 'HIgo9xNzJMWLKASShiTqIybxR0V1tB1YBjMBOAtiSw4='),
        ('endpoint_host', 'vpn.provider.example.com'),
        ('endpoint_port', '51821'),
        ('persistent_keepalive', '25'),
    ], lists=[('allowed_ips', '0.0.0.0/0')]))

    # Policy routing tables
    sections.append(build_section('route', options=[
        ('interface', 'vpn_hq'), ('target', '172.16.0.0/12'), ('table', '100'),
    ]))
    sections.append(build_section('route', options=[
        ('interface', 'vpn_ext'), ('target', '0.0.0.0/0'), ('table', '200'),
    ]))

    # IP rules — FIX #4: guest rule source 10.0.30→10.0.40
    sections.append(build_section('rule', options=[
        ('src', '10.0.20.0/24'), ('dest', '172.16.0.0/12'),
        ('lookup', '100'), ('priority', '100'),
    ]))
    sections.append(build_section('rule', options=[
        ('src', '10.0.40.0/24'), ('lookup', '200'), ('priority', '200'),
    ]))

    return sections


def build_correct_firewall():
    """Build the correct firewall configuration."""
    sections = []

    # Defaults
    sections.append(build_section('defaults', options=[
        ('syn_flood', '1'), ('input', 'REJECT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'), ('flow_offloading', '1'),
    ]))

    # Internal zones (no masquerade)
    sections.append(build_section('zone', options=[
        ('name', 'mgmt'), ('input', 'ACCEPT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'),
    ], lists=[('network', 'mgmt')]))

    sections.append(build_section('zone', options=[
        ('name', 'corp'), ('input', 'ACCEPT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'),
    ], lists=[('network', 'corp')]))

    sections.append(build_section('zone', options=[
        ('name', 'iot'), ('input', 'DROP'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'),
    ], lists=[('network', 'iot')]))

    sections.append(build_section('zone', options=[
        ('name', 'guest'), ('input', 'REJECT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'),
    ], lists=[('network', 'guest')]))

    # WAN zone (masquerade)
    sections.append(build_section('zone', options=[
        ('name', 'wan'), ('input', 'REJECT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'), ('masq', '1'), ('mtu_fix', '1'),
    ], lists=[('network', 'wan'), ('network', 'wan6')]))

    # FIX #7: wan_backup zone — ADD 'list network wan_backup'
    sections.append(build_section('zone', options=[
        ('name', 'wan_backup'), ('input', 'REJECT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'), ('masq', '1'),
    ], lists=[('network', 'wan_backup')]))

    # FIX #8: vpn_hq zone — REMOVE masquerade (HQ has return routes)
    sections.append(build_section('zone', options=[
        ('name', 'vpn_hq'), ('input', 'ACCEPT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'),
    ], lists=[('network', 'vpn_hq')]))

    # FIX #9: vpn_ext zone — ADD masquerade (provider expects tunnel addr)
    sections.append(build_section('zone', options=[
        ('name', 'vpn_ext'), ('input', 'REJECT'), ('output', 'ACCEPT'),
        ('forward', 'REJECT'), ('masq', '1'),
    ], lists=[('network', 'vpn_ext')]))

    # Forwarding rules — FIX #10: remove guest→wan; FIX #11: add missing rules
    forwardings = [
        ('mgmt', 'wan'),
        ('corp', 'wan'),
        ('iot', 'wan'),
        # guest→wan intentionally ABSENT (FIX #10)
        ('mgmt', 'wan_backup'),
        ('corp', 'wan_backup'),
        ('iot', 'wan_backup'),       # FIX #11: was missing
        ('mgmt', 'vpn_hq'),         # FIX #11: was missing
        ('corp', 'vpn_hq'),         # FIX #11: was missing
        ('mgmt', 'iot'),            # FIX #11: was missing
        ('guest', 'vpn_ext'),
        ('guest', 'wan_backup'),
    ]
    for src, dest in forwardings:
        sections.append(build_section('forwarding', options=[
            ('src', src), ('dest', dest),
        ]))

    # Standard ingress rules
    sections.append(build_section('rule', options=[
        ('name', 'Allow-DHCP-Renew'), ('src', 'wan'), ('proto', 'udp'),
        ('dest_port', '68'), ('target', 'ACCEPT'), ('family', 'ipv4'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'Allow-Ping'), ('src', 'wan'), ('proto', 'icmp'),
        ('icmp_type', 'echo-request'), ('family', 'ipv4'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'guest-dhcp'), ('src', 'guest'), ('proto', 'udp'),
        ('dest_port', '67-68'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'guest-dns'), ('src', 'guest'), ('proto', 'udp tcp'),
        ('dest_port', '53'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'iot-dhcp'), ('src', 'iot'), ('proto', 'udp'),
        ('dest_port', '67-68'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'iot-dns'), ('src', 'iot'), ('proto', 'udp tcp'),
        ('dest_port', '53'), ('target', 'ACCEPT'),
    ]))

    # IoT outbound restrictions — FIX #12: allows BEFORE reject-all
    sections.append(build_section('rule', options=[
        ('name', 'iot-allow-http'), ('src', 'iot'), ('dest', 'wan'),
        ('proto', 'tcp'), ('dest_port', '80 443'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'iot-allow-ntp'), ('src', 'iot'), ('dest', 'wan'),
        ('proto', 'udp'), ('dest_port', '123'), ('target', 'ACCEPT'),
    ]))
    sections.append(build_section('rule', options=[
        ('name', 'iot-block-other'), ('src', 'iot'), ('dest', 'wan'),
        ('target', 'REJECT'),
    ]))

    # FIX #15: WAN rate limit
    sections.append(build_section('rule', options=[
        ('name', 'wan-rate-limit'), ('src', 'wan'), ('proto', 'tcp'),
        ('target', 'ACCEPT'), ('limit', '25/min'),
    ]))

    # DNS DNAT redirects — FIX #13: SNAT→DNAT; FIX #14: add IoT redirect
    sections.append(build_section('redirect', options=[
        ('name', 'guest-dns-redirect'), ('src', 'guest'),
        ('src_dport', '53'), ('dest_port', '53'),
        ('target', 'DNAT'), ('proto', 'tcp udp'),
    ]))
    sections.append(build_section('redirect', options=[
        ('name', 'iot-dns-redirect'), ('src', 'iot'),
        ('src_dport', '53'), ('dest_port', '53'),
        ('target', 'DNAT'), ('proto', 'tcp udp'),
    ]))

    return sections


def diagnose_network(path):
    """Read and diagnose issues in the current network config."""
    print("--- Diagnosing {} ---".format(path))
    issues = []

    with open(path) as f:
        text = f.read()

    if 'eth2' in text and "device 'eth2'" in text:
        issues.append("BUG: wan_backup bound to eth2 (should be eth1)")
    if "allowed_ips '0.0.0.0/0'" in text and 'wireguard_vpn_hq' in text:
        issues.append("BUG: HQ VPN AllowedIPs is 0.0.0.0/0 (should be 172.16.0.0/12)")
    if 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=' in text:
        issues.append("BUG: vpn_ext has placeholder private key")
    if "src '10.0.30.0/24'" in text:
        issues.append("BUG: Policy routing rule uses IoT subnet for guest (10.0.30 vs 10.0.40)")
    if "fc00::/48" in text:
        issues.append("BUG: ULA prefix is fc00::/48 (should be fd12:3456:789a::/48)")

    for issue in issues:
        print("  [!] {}".format(issue))
    if not issues:
        print("  No issues found")
    return issues


def diagnose_firewall(path):
    """Read and diagnose issues in the current firewall config."""
    print("--- Diagnosing {} ---".format(path))
    issues = []

    with open(path) as f:
        lines = f.readlines()
        text = ''.join(lines)

    # Check wan_backup zone binding
    in_wan_backup_zone = False
    wan_backup_has_network = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('config '):
            in_wan_backup_zone = ("name 'wan_backup'" in ''.join(
                lines[lines.index(line):lines.index(line)+8]
            ) if "zone" in stripped else False)
        if in_wan_backup_zone and "list network" in stripped:
            wan_backup_has_network = True

    if not wan_backup_has_network and 'wan_backup' in text:
        issues.append("BUG: wan_backup zone missing 'list network' binding")

    if "target 'SNAT'" in text:
        issues.append("BUG: DNS redirect uses SNAT instead of DNAT")

    # Check rule ordering
    block_pos = text.find("iot-block-other")
    allow_pos = text.find("iot-allow-http")
    if block_pos > 0 and allow_pos > 0 and block_pos < allow_pos:
        issues.append("BUG: IoT reject-all rule appears before allow rules")

    if "option src 'guest'" in text and "option dest 'wan'" in text:
        issues.append("BUG: guest→wan forwarding still present")

    for issue in issues:
        print("  [!] {}".format(issue))
    if not issues:
        print("  No issues found")
    return issues


def main():
    print("=== OpenWrt UCI Configuration Audit & Remediation ===")
    print()

    # Phase 1: Diagnose
    params = parse_change_request('/app/change_request.md')
    print("Extracted change request parameters:")
    for k, v in sorted(params.items()):
        print("  {}: {}".format(k, v))
    print()

    net_issues = diagnose_network('/app/config/network')
    print()
    fw_issues = diagnose_firewall('/app/config/firewall')
    print()

    total = len(net_issues) + len(fw_issues)
    print("Total issues diagnosed: {}".format(total))
    print()

    # Phase 2: Build correct configs
    print("--- Building corrected /app/config/network ---")
    net_sections = build_correct_network(params)
    net_text = serialize_config(net_sections)
    with open('/app/config/network', 'w') as f:
        f.write(net_text)
    print("  Written {} sections".format(len(net_sections)))

    print("--- Building corrected /app/config/firewall ---")
    fw_sections = build_correct_firewall()
    fw_text = serialize_config(fw_sections)
    with open('/app/config/firewall', 'w') as f:
        f.write(fw_text)
    print("  Written {} sections".format(len(fw_sections)))

    print()
    print("=== Remediation complete. ===")


if __name__ == '__main__':
    main()
