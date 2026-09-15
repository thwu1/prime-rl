#!/usr/bin/env python3
"""
Generate remediated configurations and unified diff patches.

"""

import json
import os
import re
import subprocess
import shutil


CONFIGS_DIR = "/app/configs"
PATCHES_DIR = "/app/remediation_patches"
REMEDIATED_DIR = "/tmp/remediated_configs"


def load_report():
    with open("/app/audit_report.json", "r") as f:
        return json.load(f)


def read_config(router):
    path = os.path.join(CONFIGS_DIR, f"{router}.cfg")
    with open(path, "r") as f:
        return f.read()


def apply_r1_fixes(config):
    """Fix R1: OSPF Area 1 auth to message-digest, restore BFD on Gi1."""
    # Fix Area 1 authentication: plaintext -> message-digest
    config = re.sub(
        r"(area 1 authentication)\s*$",
        r"area 1 authentication message-digest",
        config,
        flags=re.MULTILINE,
    )
    # Fix interface auth on Gi2 from plaintext key to md5
    config = config.replace(
        " ip ospf authentication-key 7 1511021F07",
        " ip ospf message-digest-key 1 md5 7 1511021F07",
    )
    # Fix BFD on Gi1: remove 'no bfd interval' and add proper BFD
    config = config.replace(
        " no bfd interval\n",
        " bfd interval 500 min_rx 500 multiplier 3\n",
    )
    return config


def apply_r2_fixes(config):
    """Fix R2: Define prefix-list ALLOWED_OUT, add tag-based loop prevention."""
    # Add prefix-list ALLOWED_OUT before the route-map EXPORT_POLICY
    prefix_list_def = (
        "ip prefix-list ALLOWED_OUT seq 10 permit 192.168.12.0/24\n"
        "ip prefix-list ALLOWED_OUT seq 20 permit 192.168.14.0/24\n"
        "ip prefix-list ALLOWED_OUT seq 30 permit 1.1.1.1/32\n"
        "ip prefix-list ALLOWED_OUT seq 40 permit 4.4.4.4/32\n"
        "!\n"
    )
    config = config.replace(
        "route-map EXPORT_POLICY permit 10",
        prefix_list_def + "route-map EXPORT_POLICY permit 10",
    )

    # Add set tag to BGP_TO_OSPF route-map
    config = config.replace(
        "route-map BGP_TO_OSPF permit 10\n set metric 100\n",
        "route-map BGP_TO_OSPF permit 10\n set metric 100\n set tag 65002\n",
    )

    # Add deny clause to OSPF_TO_BGP route-map to prevent loop
    config = config.replace(
        "route-map OSPF_TO_BGP permit 10\n",
        "route-map OSPF_TO_BGP deny 5\n match tag 65002\n!\nroute-map OSPF_TO_BGP permit 10\n",
    )

    return config


def apply_r3_fixes(config):
    """Fix R3: CoPP direction from output to input."""
    config = config.replace(
        " service-policy output COPP_POLICY",
        " service-policy input COPP_POLICY",
    )
    return config


def apply_r4_fixes(config):
    """Fix R4: Swap passive-interface from Gi2 to Gi1."""
    config = config.replace(
        " no passive-interface GigabitEthernet2",
        " no passive-interface GigabitEthernet1",
    )
    return config


def apply_r5_fixes(config):
    """Fix R5: OSPF cost on Gi2 from 500 to 10, remove conflicting network statement."""
    config = config.replace(
        " ip ospf cost 500",
        " ip ospf cost 10",
    )
    # Remove the conflicting network statement
    config = config.replace(
        " network 172.16.0.0 0.0.255.255 area 2\n",
        "",
    )
    return config


def apply_r6_fixes(config):
    """Fix R6: VTY ACL to management subnet, add NTP trusted-key."""
    # Fix VTY ACL: narrow from /8 to /24
    config = config.replace(
        " permit 10.0.0.0 0.255.255.255",
        " permit 10.1.1.0 0.0.0.255",
    )
    # Add ntp trusted-key after ntp authentication-key line
    config = config.replace(
        "ntp authentication-key 1 md5 7 04580A0E17\n",
        "ntp authentication-key 1 md5 7 04580A0E17\nntp trusted-key 1\n",
    )
    return config


ROUTER_FIXES = {
    "R1": apply_r1_fixes,
    "R2": apply_r2_fixes,
    "R3": apply_r3_fixes,
    "R4": apply_r4_fixes,
    "R5": apply_r5_fixes,
    "R6": apply_r6_fixes,
}


def main():
    os.makedirs(PATCHES_DIR, exist_ok=True)
    os.makedirs(REMEDIATED_DIR, exist_ok=True)

    report = load_report()
    affected_routers = set(d["router"] for d in report["defects"])

    for router in sorted(affected_routers):
        if router not in ROUTER_FIXES:
            continue

        original = read_config(router)
        remediated = ROUTER_FIXES[router](original)

        # Write remediated config to temp dir
        orig_path = os.path.join(CONFIGS_DIR, f"{router}.cfg")
        remed_path = os.path.join(REMEDIATED_DIR, f"{router}.cfg")
        with open(remed_path, "w") as f:
            f.write(remediated)

        # Generate unified diff patch
        result = subprocess.run(
            ["diff", "-u", orig_path, remed_path],
            capture_output=True,
            text=True,
        )
        # diff returns 1 if files differ (which they should)
        patch_content = result.stdout
        if patch_content:
            patch_path = os.path.join(PATCHES_DIR, f"{router}.patch")
            with open(patch_path, "w") as f:
                f.write(patch_content)
            print(f"Generated patch: {patch_path}")
        else:
            print(f"Warning: No differences found for {router}")

    # Clean up temp dir
    shutil.rmtree(REMEDIATED_DIR, ignore_errors=True)
    print(f"\nPatches written to {PATCHES_DIR}")


if __name__ == "__main__":
    main()
