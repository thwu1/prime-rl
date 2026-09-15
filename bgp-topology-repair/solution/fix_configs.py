#!/usr/bin/env python3
"""
Diagnose and fix BGP misconfigurations in FRR configuration files.
Reads each router config, identifies missing statements based on the
topology requirements, and applies targeted fixes.
"""

import re
import os

CONFIG_DIR = "/app/configs"


def read_config(router):
    path = os.path.join(CONFIG_DIR, f"{router}.conf")
    with open(path) as f:
        return f.read()


def write_config(router, content):
    path = os.path.join(CONFIG_DIR, f"{router}.conf")
    with open(path, "w") as f:
        f.write(content)


def has_pattern(text, pattern):
    return bool(re.search(pattern, text))


def fix_r1():
    """
    R1 needs:
    - ebgp-multihop for loopback peering with R4 (10.255.1.4)
    - next-hop-self for iBGP peer R2 (10.255.0.2)
    - outbound AS-path filter on R4 to prevent transit
    """
    config = read_config("r1")

    # Fix 1: Add ebgp-multihop for R4 loopback peering
    if not has_pattern(config, r'neighbor 10\.255\.1\.4 ebgp-multihop'):
        config = config.replace(
            " neighbor 10.255.1.4 update-source lo\n",
            " neighbor 10.255.1.4 update-source lo\n"
            " neighbor 10.255.1.4 ebgp-multihop 2\n"
        )

    # Fix 2: Add next-hop-self for iBGP peer R2
    if not has_pattern(config, r'neighbor 10\.255\.0\.2 next-hop-self'):
        config = config.replace(
            "  network 192.168.100.0/24\n",
            "  network 192.168.100.0/24\n"
            "  neighbor 10.255.0.2 next-hop-self\n"
        )

    # Fix 3: Add transit prevention outbound filter for R4
    if not has_pattern(config, r'neighbor 10\.255\.1\.4 route-map \S+ out'):
        # Add route-map application in address-family
        config = config.replace(
            " exit-address-family",
            "  neighbor 10.255.1.4 route-map EXPORT_FILTER out\n"
            " exit-address-family"
        )
        # Add AS-path ACL and route-map definitions before router bgp
        config = config.replace(
            "!\nrouter bgp 65000",
            "!\nbgp as-path access-list LOCAL_ONLY permit ^$\n"
            "!\nroute-map EXPORT_FILTER permit 10\n"
            " match as-path LOCAL_ONLY\n"
            "!\nrouter bgp 65000"
        )

    write_config("r1", config)
    print("R1: Applied ebgp-multihop, next-hop-self, transit filter")


def fix_r2():
    """
    R2 needs:
    - route-reflector-client for both iBGP peers (R1 and R3)
    """
    config = read_config("r2")

    if not has_pattern(config, r'neighbor 10\.255\.0\.1 route-reflector-client'):
        config = config.replace(
            "  network 192.168.100.0/24\n exit-address-family",
            "  network 192.168.100.0/24\n"
            "  neighbor 10.255.0.1 route-reflector-client\n"
            "  neighbor 10.255.0.3 route-reflector-client\n"
            " exit-address-family"
        )

    write_config("r2", config)
    print("R2: Applied route-reflector-client for R1 and R3")


def fix_r3():
    """
    R3 needs:
    - OSPF network statement for R2-R3 link (10.0.23.0/24)
    - next-hop-self for iBGP peer R2
    - inbound route-map on R5 setting local-preference 200
    - outbound AS-path filter on R5 to prevent transit
    """
    config = read_config("r3")

    # Fix 1: Add missing OSPF network for R2-R3 link
    if not has_pattern(config, r'network 10\.0\.23\.0'):
        config = config.replace(
            " network 10.255.0.3/32 area 0\n",
            " network 10.255.0.3/32 area 0\n"
            " network 10.0.23.0/24 area 0\n"
        )

    # Fix 2-4: Add AF statements and route-map/ACL definitions
    if not has_pattern(config, r'neighbor 10\.255\.0\.2 next-hop-self'):
        # Populate the empty address-family block
        config = config.replace(
            " address-family ipv4 unicast\n exit-address-family",
            " address-family ipv4 unicast\n"
            "  neighbor 10.255.0.2 next-hop-self\n"
            "  neighbor 10.0.35.5 route-map SET_LOCPREF_200 in\n"
            "  neighbor 10.0.35.5 route-map EXPORT_R3 out\n"
            " exit-address-family"
        )
        # Add AS-path ACL and route-map definitions before router bgp
        config = config.replace(
            "!\nrouter bgp 65000",
            "!\nbgp as-path access-list LOCAL_ONLY_R3 permit ^$\n"
            "!\nroute-map EXPORT_R3 permit 10\n"
            " match as-path LOCAL_ONLY_R3\n"
            "!\nroute-map SET_LOCPREF_200 permit 10\n"
            " set local-preference 200\n"
            "!\nrouter bgp 65000"
        )

    write_config("r3", config)
    print("R3: Applied OSPF network, next-hop-self, local-pref, transit filter")


def fix_r4():
    """
    R4 needs:
    - ebgp-multihop for loopback peering with R1 (10.255.0.1)
    """
    config = read_config("r4")

    if not has_pattern(config, r'neighbor 10\.255\.0\.1 ebgp-multihop'):
        config = config.replace(
            " neighbor 10.255.0.1 update-source lo\n",
            " neighbor 10.255.0.1 update-source lo\n"
            " neighbor 10.255.0.1 ebgp-multihop 2\n"
        )

    write_config("r4", config)
    print("R4: Applied ebgp-multihop")


if __name__ == "__main__":
    fix_r1()
    fix_r2()
    fix_r3()
    fix_r4()
    print("\nAll configuration fixes applied successfully.")
