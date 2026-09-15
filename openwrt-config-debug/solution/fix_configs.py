#!/usr/bin/env python3
"""OpenWrt UCI configuration debugger and fixer.

Parses UCI config files, compares against network requirements,
identifies misconfigurations, and applies corrections.

"""

import sys


class UCIConfig:
    """Parser and modifier for OpenWrt UCI configuration files."""

    def __init__(self, path):
        self.path = path
        self.lines = []
        self.sections = []
        self._load()

    def _load(self):
        with open(self.path) as f:
            self.lines = f.readlines()
        self._parse()

    def _parse(self):
        self.sections = []
        current = None
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if stripped.startswith('config '):
                parts = stripped.split(None, 2)
                stype = parts[1] if len(parts) > 1 else ''
                sname = parts[2].strip("'\"") if len(parts) > 2 else None
                current = {
                    'type': stype,
                    'name': sname,
                    'start_line': i,
                    'end_line': i,
                    'options': {},
                    'lists': {},
                    'option_lines': {},
                    'list_lines': {},
                }
                self.sections.append(current)
            elif current is not None:
                if stripped.startswith('option '):
                    parts = stripped.split(None, 2)
                    if len(parts) >= 3:
                        key = parts[1]
                        value = parts[2].strip("'\"")
                        current['options'][key] = value
                        current['option_lines'][key] = i
                        current['end_line'] = i
                elif stripped.startswith('list '):
                    parts = stripped.split(None, 2)
                    if len(parts) >= 3:
                        key = parts[1]
                        value = parts[2].strip("'\"")
                        if key not in current['lists']:
                            current['lists'][key] = []
                            current['list_lines'][key] = []
                        current['lists'][key].append(value)
                        current['list_lines'][key].append(i)
                        current['end_line'] = i

    def find_section(self, stype, sname=None, match_options=None):
        """Find a section by type and optionally name or option values."""
        for s in self.sections:
            if s['type'] != stype:
                continue
            if sname is not None and s['name'] != sname:
                continue
            if match_options:
                if not all(s['options'].get(k) == v
                           for k, v in match_options.items()):
                    continue
            return s
        return None

    def set_option(self, section, key, value):
        """Set or replace an option value in a section."""
        if key in section['option_lines']:
            line_idx = section['option_lines'][key]
            self.lines[line_idx] = "\toption {} '{}'\n".format(key, value)
        else:
            insert_at = section['end_line'] + 1
            self.lines.insert(insert_at, "\toption {} '{}'\n".format(key, value))
            self._parse()
        section['options'][key] = value

    def replace_list(self, section, key, new_values):
        """Replace all list entries for a key in a section."""
        if key in section['list_lines']:
            old_indices = sorted(section['list_lines'][key], reverse=True)
            first_idx = min(section['list_lines'][key])
            for idx in old_indices:
                del self.lines[idx]
            for i, value in enumerate(new_values):
                self.lines.insert(
                    first_idx + i,
                    "\tlist {} '{}'\n".format(key, value),
                )
        else:
            insert_at = section['end_line'] + 1
            for i, value in enumerate(new_values):
                self.lines.insert(
                    insert_at + i,
                    "\tlist {} '{}'\n".format(key, value),
                )
        self._parse()

    def add_list_entry(self, section, key, value):
        """Add a single list entry at the end of a section."""
        insert_at = section['end_line'] + 1
        self.lines.insert(insert_at, "\tlist {} '{}'\n".format(key, value))
        self._parse()

    def append_section(self, text):
        """Append a new section at the end of the file."""
        if self.lines and not self.lines[-1].endswith('\n'):
            self.lines.append('\n')
        self.lines.append('\n')
        for line in text.strip().split('\n'):
            self.lines.append(line + '\n')
        self._parse()

    def save(self):
        with open(self.path, 'w') as f:
            f.writelines(self.lines)


def fix_network(path='/app/config/network'):
    """Fix misconfigurations in the network config."""
    config = UCIConfig(path)

    # --- Bug 1: VLAN port assignments are swapped ---
    # Requirements: VLAN 20 (Corporate) = lan3,lan4; VLAN 30 (IoT) = lan5
    # Current:      VLAN 20 has lan5;              VLAN 30 has lan3,lan4
    vlan20 = config.find_section('bridge-vlan', match_options={'vlan': '20'})
    if vlan20:
        current_ports = [p.split(':')[0] for p in vlan20['lists'].get('ports', [])]
        if 'lan5' in current_ports and 'lan3' not in current_ports:
            print("[FIX 1] VLAN 20: replacing lan5 with lan3:u*,lan4:u*")
            config.replace_list(vlan20, 'ports', ['lan3:u*', 'lan4:u*'])

    vlan30 = config.find_section('bridge-vlan', match_options={'vlan': '30'})
    if vlan30:
        current_ports = [p.split(':')[0] for p in vlan30['lists'].get('ports', [])]
        if 'lan3' in current_ports and 'lan5' not in current_ports:
            print("[FIX 1] VLAN 30: replacing lan3,lan4 with lan5:u*")
            config.replace_list(vlan30, 'ports', ['lan5:u*'])

    # --- Bug 3: WireGuard HQ peer AllowedIPs too broad ---
    # Requirements: 172.16.0.0/12 only
    # Current:      0.0.0.0/0 (captures ALL traffic)
    hq_peer = config.find_section('wireguard_vpn_hq')
    if hq_peer:
        allowed = hq_peer['lists'].get('allowed_ips', [])
        if '0.0.0.0/0' in allowed:
            print("[FIX 3] WireGuard vpn_hq: restricting AllowedIPs to 172.16.0.0/12")
            config.replace_list(hq_peer, 'allowed_ips', ['172.16.0.0/12'])

    # --- Bug 4: Missing policy routing rule for guest traffic ---
    # Requirements: 10.0.40.0/24 -> table 200 (via vpn_ext)
    guest_rule_found = False
    for s in config.sections:
        if s['type'] == 'rule':
            src = s['options'].get('src', '')
            lookup = s['options'].get('lookup', '')
            if '10.0.40' in src and lookup == '200':
                guest_rule_found = True
    if not guest_rule_found:
        print("[FIX 4] Adding policy routing rule: 10.0.40.0/24 -> table 200")
        config.append_section(
            "config rule\n"
            "\toption src '10.0.40.0/24'\n"
            "\toption lookup '200'\n"
            "\toption priority '200'"
        )

    config.save()
    print("Network config saved.")


def fix_firewall(path='/app/config/firewall'):
    """Fix misconfigurations in the firewall config."""
    config = UCIConfig(path)

    # --- Bug 2: iot zone missing network assignment ---
    # Requirements: zone iot must have 'list network iot'
    iot_zone = config.find_section('zone', match_options={'name': 'iot'})
    if iot_zone:
        networks = iot_zone['lists'].get('network', [])
        if 'iot' not in networks:
            print("[FIX 2] Adding 'list network iot' to iot firewall zone")
            config.add_list_entry(iot_zone, 'network', 'iot')

    # --- Bug 6: Reversed forwarding corp<->vpn_hq ---
    # Requirements: corp -> vpn_hq
    # Current:      vpn_hq -> corp (reversed)
    for s in config.sections:
        if s['type'] == 'forwarding':
            src = s['options'].get('src', '')
            dest = s['options'].get('dest', '')
            if src == 'vpn_hq' and dest == 'corp':
                print("[FIX 6] Reversing forwarding: vpn_hq->corp to corp->vpn_hq")
                config.set_option(s, 'src', 'corp')
                config.set_option(s, 'dest', 'vpn_hq')
                break

    # --- Bug 7: DNS redirect has wrong source zone ---
    # Requirements: src must be 'guest' (prevent DNS leaks)
    # Current:      src is 'iot'
    for s in config.sections:
        if s['type'] == 'redirect':
            src_dport = s['options'].get('src_dport', '')
            if '53' in src_dport:
                current_src = s['options'].get('src', '')
                if current_src != 'guest':
                    print("[FIX 7] DNS redirect: changing src '{}' to 'guest'"
                          .format(current_src))
                    config.set_option(s, 'src', 'guest')
                break

    config.save()
    print("Firewall config saved.")


def fix_dhcp(path='/app/config/dhcp'):
    """Fix misconfigurations in the DHCP config."""
    config = UCIConfig(path)

    # --- Bug 5: Guest DHCP references wrong interface ---
    # Requirements: interface must be 'guest'
    # Current:      interface is 'guest_wifi'
    guest_dhcp = config.find_section('dhcp', sname='guest')
    if guest_dhcp:
        iface = guest_dhcp['options'].get('interface', '')
        if iface != 'guest':
            print("[FIX 5] Guest DHCP: changing interface '{}' to 'guest'"
                  .format(iface))
            config.set_option(guest_dhcp, 'interface', 'guest')

    config.save()
    print("DHCP config saved.")


def main():
    print("=== OpenWrt UCI Configuration Debugger ===")
    print()

    print("--- Analyzing /app/config/network ---")
    fix_network()
    print()

    print("--- Analyzing /app/config/firewall ---")
    fix_firewall()
    print()

    print("--- Analyzing /app/config/dhcp ---")
    fix_dhcp()
    print()

    print("=== All fixes applied. ===")


if __name__ == '__main__':
    main()
