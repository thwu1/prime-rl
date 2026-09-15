#!/usr/bin/env python3
"""Diagnose and fix BGP configuration issues across a 4-router FRR topology,
then produce a structured diagnosis document.


Reads the initial (buggy) configuration files, applies targeted fixes based
on analysis of the topology and BGP protocol requirements, writes the
corrected configurations back, and generates diagnosis.json.
"""

import os
import re
import json

CONFIG_DIR = '/app/configs'


def read_config(router):
    path = os.path.join(CONFIG_DIR, f'{router}.conf')
    with open(path) as f:
        return f.read()


def write_config(router, content):
    path = os.path.join(CONFIG_DIR, f'{router}.conf')
    with open(path, 'w') as f:
        f.write(content)


def analyze_and_fix():
    """Analyze topology and fix all configuration issues."""

    # Read all configs
    r1 = read_config('r1')
    r2 = read_config('r2')
    r3 = read_config('r3')
    r4 = read_config('r4')

    # ================================================================
    # BUG 1: r2 iBGP session to r3 via loopback - missing update-source
    #
    # r2 peers with r3 via loopback addresses (10.255.0.3). Without
    # update-source lo, r2's TCP connection originates from its physical
    # interface IP (10.0.23.1) instead of its loopback (10.255.0.2).
    # r3 rejects because it expects connections from 10.255.0.2.
    #
    # Evidence: r3 log shows "connection from 10.0.23.1 rejected"
    # ================================================================
    r2 = r2.replace(
        ' neighbor 10.255.0.3 remote-as 65002\n',
        ' neighbor 10.255.0.3 remote-as 65002\n'
        ' neighbor 10.255.0.3 update-source lo\n'
    )

    # ================================================================
    # BUG 2: r4 has wrong neighbor IP for r1
    #
    # r4 is configured with neighbor 10.0.14.3, but r1's interface on
    # the r1-r4 link is 10.0.14.1. TCP connection to 10.0.14.3 fails
    # with "Connection refused" since nothing is listening there.
    #
    # Evidence: r4 log shows "10.0.14.3 Connect failed (Connection refused)"
    # ================================================================
    r4 = r4.replace('10.0.14.3', '10.0.14.1')

    # ================================================================
    # BUG 3: r3 and r4 eBGP multihop - missing static routes
    #
    # r3 and r4 peer via loopback addresses with ebgp-multihop 3, but
    # neither has a route to the other's loopback. The TCP connection
    # fails with "No route to host".
    #
    # Evidence: both logs show "No route to host" for loopback IPs
    # ================================================================
    r3 = r3.replace(
        'ip route 10.255.0.2/32 10.0.23.1\n',
        'ip route 10.255.0.2/32 10.0.23.1\n'
        'ip route 10.255.0.4/32 10.0.34.2\n'
    )
    r4 = r4.replace(
        'router bgp 65003',
        'ip route 10.255.0.3/32 10.0.34.1\n!\nrouter bgp 65003'
    )

    # ================================================================
    # POLICY 1: next-hop-self on r3 for iBGP client r2
    #
    # Without this, routes reflected from r4 carry r4's external next-hop
    # which is unreachable from r2. r3 must rewrite the next-hop to its
    # own loopback address.
    # ================================================================
    r3 = r3.replace(
        '  neighbor 10.255.0.2 route-reflector-client\n',
        '  neighbor 10.255.0.2 route-reflector-client\n'
        '  neighbor 10.255.0.2 next-hop-self\n'
    )

    # ================================================================
    # POLICY 2: AS-path prepend on r4 toward r3
    #
    # Prepend AS65003 three additional times on announcements to r3,
    # making the transit path AS-path length 5 when seen from r1.
    # ================================================================
    prepend_map = (
        'route-map RM_PREPEND permit 10\n'
        ' set as-path prepend 65003 65003 65003\n!\n'
    )
    r4 = r4.replace(
        'ip route 10.255.0.3/32 10.0.34.1\n!\n',
        'ip route 10.255.0.3/32 10.0.34.1\n!\n' + prepend_map
    )
    r4 = r4.replace(
        ' neighbor 10.255.0.3 update-source lo\n',
        ' neighbor 10.255.0.3 update-source lo\n'
        ' neighbor 10.255.0.3 route-map RM_PREPEND out\n'
    )

    # ================================================================
    # POLICY 3: Route filtering and LOCAL_PREF on r1
    #
    # - Filter 10.4.3.0/24 from both eBGP peers (deny in route-maps)
    # - Set LOCAL_PREF 200 for 10.4.1.0/24 from transit peer (10.0.12.2)
    #   This overrides the shorter direct AS-path, steering traffic
    #   for that prefix through the transit ISP.
    # ================================================================
    policy_block = (
        'ip prefix-list PL_BLOCK seq 10 permit 10.4.3.0/24\n'
        'ip prefix-list PL_BOOST seq 10 permit 10.4.1.0/24\n'
        '!\n'
        'route-map RM_TRANSIT deny 10\n'
        ' match ip address prefix-list PL_BLOCK\n'
        '!\n'
        'route-map RM_TRANSIT permit 20\n'
        ' match ip address prefix-list PL_BOOST\n'
        ' set local-preference 200\n'
        '!\n'
        'route-map RM_TRANSIT permit 30\n'
        '!\n'
        'route-map RM_DIRECT deny 10\n'
        ' match ip address prefix-list PL_BLOCK\n'
        '!\n'
        'route-map RM_DIRECT permit 20\n'
        '!\n'
    )
    r1 = r1.replace('router bgp 65001', policy_block + 'router bgp 65001')
    r1 = r1.replace(
        ' neighbor 10.0.12.2 remote-as 65002\n',
        ' neighbor 10.0.12.2 remote-as 65002\n'
        ' neighbor 10.0.12.2 route-map RM_TRANSIT in\n'
    )
    r1 = r1.replace(
        ' neighbor 10.0.14.2 remote-as 65003\n',
        ' neighbor 10.0.14.2 remote-as 65003\n'
        ' neighbor 10.0.14.2 route-map RM_DIRECT in\n'
    )

    # Write all corrected configs
    write_config('r1', r1)
    write_config('r2', r2)
    write_config('r3', r3)
    write_config('r4', r4)

    print("Configuration analysis and fixes applied:")
    print("  r1: Added route-maps for prefix filtering and LOCAL_PREF")
    print("  r2: Added update-source lo for iBGP loopback peering")
    print("  r3: Added static route for eBGP multihop, configured next-hop-self")
    print("  r4: Fixed neighbor IP, added static route, configured AS-path prepend")


def generate_diagnosis():
    """Generate the structured diagnosis document."""
    diagnosis = {
        "session_failures": [
            {
                "session": "r2-r3",
                "affected_router": "r2",
                "root_cause": (
                    "r2 peers with r3 using loopback addresses (10.255.0.2 <-> 10.255.0.3) "
                    "but lacks an update-source directive. Without it, r2's BGP TCP connection "
                    "originates from its physical interface IP 10.0.23.1 instead of its loopback "
                    "10.255.0.2. r3's log confirms this: it rejects the incoming connection from "
                    "10.0.23.1 because no configured neighbor matches that source address. "
                    "Adding 'neighbor 10.255.0.3 update-source lo' on r2 ensures TCP uses the "
                    "loopback as the source, matching r3's expected peer address."
                )
            },
            {
                "session": "r1-r4",
                "affected_router": "r4",
                "root_cause": (
                    "r4 is configured with 'neighbor 10.0.14.3 remote-as 65001' but r1's "
                    "interface on the r1-r4 link uses 10.0.14.1 (per the topology addressing). "
                    "10.0.14.3 does not exist on any device, so r4's TCP SYN to that address "
                    "gets 'Connection refused' (errno 111) as shown in r4's debug log. "
                    "Meanwhile r4's log also shows r1 attempting inbound connections from "
                    "10.0.14.1 which r4 rejects because no neighbor is configured for that IP. "
                    "Correcting the neighbor address to 10.0.14.1 resolves both directions."
                )
            },
            {
                "session": "r3-r4",
                "affected_router": "r3 and r4",
                "root_cause": (
                    "r3 and r4 are configured for eBGP multihop peering via loopback addresses "
                    "(10.255.0.3 <-> 10.255.0.4) with ebgp-multihop 3, but neither router has "
                    "a route to the other's loopback address. Both debug logs show 'No route to "
                    "host' (errno 113) when attempting to connect. The physical link between r3 "
                    "(10.0.34.1) and r4 (10.0.34.2) exists but loopbacks are in a different "
                    "subnet and not reachable without explicit routing. Adding static routes on "
                    "both sides (r3: 10.255.0.4/32 via 10.0.34.2, r4: 10.255.0.3/32 via "
                    "10.0.34.1) provides the necessary reachability for the multihop session."
                )
            }
        ],
        "policy_decisions": {
            "prefix_steering": (
                "Used LOCAL_PREF (set local-preference 200) via an inbound route-map on r1's "
                "transit peer (10.0.12.2) with a prefix-list matching only 10.4.1.0/24. "
                "LOCAL_PREF is evaluated before AS-path length in the BGP best path algorithm, "
                "so setting it above the default (100) on the transit-learned route guarantees "
                "r1 prefers the longer transit path for this specific prefix. Weight was "
                "considered but LOCAL_PREF is the standard mechanism for influencing path "
                "selection within an AS and is the most operationally appropriate choice."
            ),
            "prefix_filtering": (
                "Applied inbound route-maps on r1 for both eBGP peers (transit 10.0.12.2 and "
                "direct 10.0.14.2) with a deny clause matching a prefix-list that permits "
                "10.4.3.0/24. The deny clause in the route-map blocks the prefix before it "
                "enters r1's BGP table. A catch-all permit clause follows to allow all other "
                "prefixes. This approach filters at ingress on r1 rather than relying on the "
                "originating AS, ensuring r1 never installs the unwanted prefix regardless of "
                "how peers advertise it."
            ),
            "path_inflation": (
                "Applied an outbound route-map on r4 toward r3 (neighbor 10.255.0.3) that "
                "uses 'set as-path prepend 65003 65003 65003' to add three additional copies "
                "of AS65003 to the AS-path. This makes routes via the transit path (AS65001 -> "
                "AS65002 -> AS65003 x4) appear much longer at upstream vantage points compared "
                "to the direct path (AS65001 -> AS65003), influencing other networks to prefer "
                "the direct peering. AS-path prepending is the standard BGP mechanism for "
                "inter-AS path manipulation without changing the actual routing topology."
            ),
            "ibgp_reachability": (
                "Configured 'neighbor 10.255.0.2 next-hop-self' on r3 for its iBGP client r2. "
                "When r3 reflects eBGP-learned routes from r4 (next-hop 10.0.34.2) to r2, the "
                "original external next-hop is preserved by default. r2 has no route to "
                "10.0.34.2, making these reflected routes unusable. Next-hop-self rewrites the "
                "next-hop to r3's own loopback (10.255.0.3), which r2 already has a static "
                "route to. This is the standard solution for iBGP next-hop reachability in "
                "route-reflector topologies where not all clients have direct paths to external "
                "next-hops."
            )
        }
    }

    with open('/app/diagnosis.json', 'w') as f:
        json.dump(diagnosis, f, indent=2)

    print("Diagnosis document written to /app/diagnosis.json")


if __name__ == '__main__':
    analyze_and_fix()
    generate_diagnosis()
