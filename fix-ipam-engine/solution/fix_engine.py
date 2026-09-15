#!/usr/bin/env python3
"""
Analyze and fix bugs in the IPAM engine by reading the source,
identifying incorrect patterns, and applying targeted fixes.

Fixes 5 bugs in /app/ipam/engine.py:
1. get_child_prefixes: missing strict containment check
2. get_prefix_utilization: missing network/broadcast subtraction for non-pool IPv4
3. get_available_ips: IPv6 incorrectly subtracts last address
4. get_child_ips: missing VRF filter
5. rebuild_hierarchy: depth calculation missing VRF filter
"""


def apply_fixes():
    with open('/app/ipam/engine.py', 'r') as f:
        src = f.read()

    original = src

    # Fix 1: get_child_prefixes must use strict containment.
    # The parent prefix is contained within itself (self-containment in netaddr),
    # so we need prefixlen > to ensure strictly smaller networks only.
    src = src.replace(
        '            if p.prefix in parent.prefix:\n'
        '                if p.vrf == parent.vrf:',
        '            if p.prefix in parent.prefix and p.prefix.prefixlen > parent.prefix.prefixlen:\n'
        '                if p.vrf == parent.vrf:'
    )

    # Fix 2: For active (non-container) IPv4 prefixes that are not pools
    # and have prefixlen < 31, the usable address count excludes the
    # network address and broadcast address (2 addresses).
    src = src.replace(
        '            prefix_size = prefix.prefix.size\n'
        '            utilization = float(child_ips.size) / prefix_size * 100',
        '            prefix_size = prefix.prefix.size\n'
        '            if prefix.family == 4 and prefix.prefix.prefixlen < 31 and not prefix.is_pool:\n'
        '                prefix_size -= 2\n'
        '            utilization = float(child_ips.size) / prefix_size * 100'
    )

    # Fix 3: For IPv6, only the subnet-router anycast address (first address)
    # is reserved per RFC 4291. IPv6 has no broadcast address concept, so the
    # last address should NOT be subtracted.
    src = src.replace(
        '            # IPv6: subtract first and last addresses\n'
        '            available -= netaddr.IPSet([\n'
        '                netaddr.IPAddress(prefix.prefix.first),\n'
        '                netaddr.IPAddress(prefix.prefix.last),\n'
        '            ])',
        '            # IPv6: subtract only subnet-router anycast (first) per RFC 4291\n'
        '            available -= netaddr.IPSet([\n'
        '                netaddr.IPAddress(prefix.prefix.first),\n'
        '            ])'
    )

    # Fix 4: get_child_ips must filter by the prefix's VRF.
    # Without this, IPs from different VRFs sharing the same address space
    # would incorrectly appear as children.
    src = src.replace(
        '            if ip.address.ip in prefix.prefix:\n'
        '                children.append(ip)',
        '            if ip.address.ip in prefix.prefix and ip.vrf == prefix.vrf:\n'
        '                children.append(ip)'
    )

    # Fix 5: rebuild_hierarchy depth must only count ancestors in the same VRF.
    # Without VRF filtering, overlapping address space across VRFs causes
    # incorrect depth values.
    src = src.replace(
        '                if p.prefix in other.prefix and other.prefix.prefixlen < p.prefix.prefixlen:\n'
        '                    depth += 1',
        '                if p.prefix in other.prefix and other.prefix.prefixlen < p.prefix.prefixlen:\n'
        '                    if other.vrf == p.vrf:\n'
        '                        depth += 1'
    )

    assert src != original, "No fixes were applied - source patterns did not match"

    with open('/app/ipam/engine.py', 'w') as f:
        f.write(src)

    print("Applied 5 fixes to /app/ipam/engine.py")


if __name__ == '__main__':
    apply_fixes()
