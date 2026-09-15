#!/usr/bin/env python3
"""Fix all bugs and implement missing features in the SDN configuration compiler.

Uses line-by-line processing for robustness against whitespace variations.

Bugs:
1. frr.py: MAP_VTEP_IN seq 1 uses 'permit' (should be 'deny')
2. frr.py: MAP_VTEP_IN has duplicate seq 3-4 entries (copy-paste artifacts)
3. frr.py: Route targets use vnet.tag (L2 VNI) instead of zone.vrf_vxlan (L3 VNI)
4. frr.py: Route targets emitted per-VNet (should be single zone-level pair)
5. generator.py: VXLAN local IP uses management_ip instead of vtep_ip
6. generator.py: Bridge MAC uses per-node hash instead of zone anycast MAC
7. validator.py: Gateway validation doesn't reject network/broadcast addresses

Feature:
8. validator.py: Implement validate_vni_conflicts() for L2/L3 VNI collision
   and cross-zone tag reuse detection; wire into validate_config()
"""


def read_lines(path):
    """Read file and return list of lines (newlines stripped)."""
    with open(path) as f:
        return [line.rstrip('\n').rstrip('\r') for line in f]


def write_lines(path, lines):
    """Write list of lines to file (adding newlines)."""
    with open(path, 'w') as f:
        for line in lines:
            f.write(line + '\n')


# ============ FIX frr.py (Bugs 1-4) ============
print("Fixing frr.py (bugs 1-4) ...")
frr_path = '/srv/sdn/sdn_compiler/frr.py'
frr_lines = read_lines(frr_path)
new_frr = []
i = 0
while i < len(frr_lines):
    line = frr_lines[i]

    # Bug 1: MAP_VTEP_IN seq 1 should deny default routes, not permit
    if 'MAP_VTEP_IN permit 1' in line and 'lines.append' in line:
        new_frr.append(line.replace('permit 1', 'deny 1'))
        i += 1
        continue

    # Bug 2: Remove duplicate seq 3 and seq 4 blocks, renumber seq 5 -> 3
    # The seq 3 and seq 4 are copy-paste duplicates of seq 1 and seq 2
    if 'Seq 3: additional' in line and 'default route' in line:
        # Skip everything from here until the "Seq 5:" comment
        j = i + 1
        while j < len(frr_lines):
            if 'Seq 5:' in frr_lines[j]:
                break
            j += 1
        # Replace the "Seq 5" comment with "Seq 3"
        if j < len(frr_lines):
            new_frr.append(frr_lines[j].replace('Seq 5', 'Seq 3'))
            i = j + 1
        else:
            new_frr.append(line)
            i += 1
        continue

    # Bug 2 continued: Rename "permit 5" to "permit 3" on the permit-all line
    if 'MAP_VTEP_IN permit 5' in line and 'lines.append' in line:
        new_frr.append(line.replace('permit 5', 'permit 3'))
        i += 1
        continue

    # Bugs 3+4: Replace per-VNet route target loop with single zone-level pair
    # Original iterates over vnets and uses vnet.tag; should use zone.vrf_vxlan once
    if line.strip() == 'for vnet in vnets:':
        # Verify this is the route target loop by checking the next line
        if i + 1 < len(frr_lines) and 'vnet.tag' in frr_lines[i + 1]:
            # Emit fixed code: single zone-level route target pair
            new_frr.append('    rt = f"65000:{zone.vrf_vxlan}"')
            new_frr.append('    lines.append(f" route-target import {rt}")')
            new_frr.append('    lines.append(f" route-target export {rt}")')
            # Skip the for line + 3 body lines (rt assignment, import, export)
            i += 4
            continue

    new_frr.append(line)
    i += 1

write_lines(frr_path, new_frr)
print("  Fixed: " + frr_path)


# ============ FIX generator.py (Bugs 5-6) ============
print("Fixing generator.py (bugs 5-6) ...")
gen_path = '/srv/sdn/sdn_compiler/generator.py'
gen_lines = read_lines(gen_path)
new_gen = []
i = 0
while i < len(gen_lines):
    line = gen_lines[i]

    # Bug 5: VXLAN local IP should use vtep_ip, not management_ip
    if 'node.management_ip' in line and 'dstport' in line:
        new_gen.append(line.replace('node.management_ip', 'node.vtep_ip'))
        i += 1
        continue

    # Bug 6: Bridge MAC should use zone anycast MAC for EVPN zones
    # Match the start of the 3-line MAC hash computation block
    if 'mac_input' in line and 'node.name' in line and 'bridge_name' in line:
        # Replace hash-based MAC with conditional anycast MAC
        new_gen.append("    if zone.type == 'evpn' and zone.anycast_mac:")
        new_gen.append('        bridge_mac = zone.anycast_mac')
        new_gen.append('    else:')
        # Keep original 3 lines (mac_input, mac_hash, bridge_mac) indented into else
        new_gen.append('    ' + line)  # mac_input line
        if i + 1 < len(gen_lines) and 'mac_hash' in gen_lines[i + 1]:
            new_gen.append('    ' + gen_lines[i + 1])  # mac_hash line
        if i + 2 < len(gen_lines) and 'bridge_mac' in gen_lines[i + 2]:
            new_gen.append('    ' + gen_lines[i + 2])  # bridge_mac = ':'.join(...)
        i += 3  # skip the 3 hash computation lines
        continue

    new_gen.append(line)
    i += 1

write_lines(gen_path, new_gen)
print("  Fixed: " + gen_path)


# ============ FIX validator.py (Bug 7 + Feature) ============
print("Fixing validator.py (bug 7 + VNI conflict feature) ...")
val_path = '/srv/sdn/sdn_compiler/validator.py'
val_lines = read_lines(val_path)
new_val = []
i = 0

while i < len(val_lines):
    line = val_lines[i]

    # Bug 7: After "gw not in network" check, add network/broadcast address rejection
    if 'if gw not in network:' in line:
        # Keep the if line and its error append block
        new_val.append(line)
        i += 1
        # Copy lines until we find the closing paren of errors.append(...)
        while i < len(val_lines):
            new_val.append(val_lines[i])
            # The closing paren line is just "        )" (stripped: ")")
            if val_lines[i].strip() == ')' and 'append' not in val_lines[i]:
                i += 1
                break
            i += 1
        # Insert elif blocks for network and broadcast address rejection
        new_val.append('    elif gw == network.network_address:')
        new_val.append('        errors.append(')
        new_val.append("            f\"Subnet '{subnet.cidr}': gateway {subnet.gateway} is the \"")
        new_val.append('            f"network address, not a valid host address"')
        new_val.append('        )')
        new_val.append('    elif gw == network.broadcast_address:')
        new_val.append('        errors.append(')
        new_val.append("            f\"Subnet '{subnet.cidr}': gateway {subnet.gateway} is the \"")
        new_val.append('            f"broadcast address, not a valid host address"')
        new_val.append('        )')
        continue

    # Feature: Insert validate_vni_conflicts function before validate_config
    if line.startswith('def validate_config('):
        new_val.append('')
        new_val.append('def validate_vni_conflicts(sdn_config: SDNConfig) -> List[str]:')
        new_val.append('    """Detect VNI namespace conflicts across the SDN configuration.')
        new_val.append('')
        new_val.append('    Checks for:')
        new_val.append('    1. L2 VNI (VNet tag) collision with L3 VNI (zone vrf_vxlan) -')
        new_val.append('       causes traffic crossover on the VXLAN data plane')
        new_val.append('    2. Same L2 VNI used across different zones - merges broadcast domains')
        new_val.append('    """')
        new_val.append('    errors = []')
        new_val.append('')
        new_val.append('    # Collect all L3 VNIs (zone VRF VXLAN IDs)')
        new_val.append('    l3_vnis = {}')
        new_val.append('    for zone_name, zone in sdn_config.zones.items():')
        new_val.append('        if zone.vrf_vxlan:')
        new_val.append('            l3_vnis[zone.vrf_vxlan] = zone_name')
        new_val.append('')
        new_val.append('    # Check L2 VNI vs L3 VNI collisions')
        new_val.append('    for vnet_name, vnet in sdn_config.vnets.items():')
        new_val.append('        if vnet.tag in l3_vnis:')
        new_val.append('            errors.append(')
        new_val.append("                f\"VNet '{vnet_name}': L2 VNI {vnet.tag} conflicts with \"")
        new_val.append("                f\"L3 VNI of zone '{l3_vnis[vnet.tag]}'\"")
        new_val.append('            )')
        new_val.append('')
        new_val.append('    # Check cross-zone L2 VNI reuse')
        new_val.append('    tag_owners = {}')
        new_val.append('    for vnet_name, vnet in sdn_config.vnets.items():')
        new_val.append('        if vnet.tag in tag_owners:')
        new_val.append('            prev_name, prev_zone = tag_owners[vnet.tag]')
        new_val.append('            if prev_zone != vnet.zone:')
        new_val.append('                errors.append(')
        new_val.append("                    f\"VNet '{vnet_name}': L2 VNI {vnet.tag} already used by \"")
        new_val.append("                    f\"'{prev_name}' in zone '{prev_zone}'\"")
        new_val.append('                )')
        new_val.append('        else:')
        new_val.append('            tag_owners[vnet.tag] = (vnet_name, vnet.zone)')
        new_val.append('')
        new_val.append('    return errors')
        new_val.append('')
        new_val.append('')
        # Now output the original validate_config line
        new_val.append(line)
        i += 1
        continue

    # Feature: Wire validate_vni_conflicts into validate_config
    # Insert the call after the validate_tag_uniqueness call
    if 'validate_tag_uniqueness' in line and 'errors.extend' in line:
        new_val.append(line)
        i += 1
        # Insert VNI conflict validation
        new_val.append('')
        new_val.append('    # Validate VNI conflicts')
        new_val.append('    errors.extend(validate_vni_conflicts(sdn_config))')
        continue

    new_val.append(line)
    i += 1

write_lines(val_path, new_val)
print("  Fixed: " + val_path)

print("\nAll 7 bugs fixed and VNI conflict validator implemented.")
