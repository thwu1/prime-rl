#!/usr/bin/env python3
"""
Solve BGP dual-homed traffic engineering design task.
Analyzes topology and requirements to generate complete FRR configurations.

Design decisions:
- Outbound TE: local-preference (propagates AS-wide via iBGP, unlike weight
  which is local to the receiving router)
- Inbound TE: AS-path prepending (influences external AS path selection
  without requiring config changes on the peer)
- Selective advertisement: prefix-list-based route-maps (precise per-prefix
  control; implicit deny doubles as transit prevention)
- Route reflection: eliminates iBGP full-mesh requirement with R3 as RR
- Next-hop-self: required on border routers so eBGP next-hops (external IPs)
  are rewritten to the border router's loopback before reflection
"""

import os

CONFIG_DIR = "/app/configs"
CUSTOMER_ASN = 65100
ISPA_ASN = 65200
ISPB_ASN = 65300

ROUTERS = {
    "r1": {
        "asn": CUSTOMER_ASN,
        "rid": "10.255.0.1",
        "lo": "10.255.0.1/32",
        "ifaces": [("eth0", "10.0.13.1/24"), ("eth1", "10.0.14.1/24")],
        "ospf_nets": ["10.255.0.1/32", "10.0.13.0/24"],
        "ibgp": [("10.255.0.3", CUSTOMER_ASN)],
        "ebgp": [("10.0.14.4", ISPA_ASN)],
    },
    "r2": {
        "asn": CUSTOMER_ASN,
        "rid": "10.255.0.2",
        "lo": "10.255.0.2/32",
        "ifaces": [("eth0", "10.0.23.2/24"), ("eth1", "10.0.25.2/24")],
        "ospf_nets": ["10.255.0.2/32", "10.0.23.0/24"],
        "ibgp": [("10.255.0.3", CUSTOMER_ASN)],
        "ebgp": [("10.0.25.5", ISPB_ASN)],
    },
    "r3": {
        "asn": CUSTOMER_ASN,
        "rid": "10.255.0.3",
        "lo": "10.255.0.3/32",
        "ifaces": [("eth0", "10.0.13.3/24"), ("eth1", "10.0.23.3/24")],
        "ospf_nets": ["10.255.0.3/32", "10.0.13.0/24", "10.0.23.0/24"],
        "ibgp": [("10.255.0.1", CUSTOMER_ASN), ("10.255.0.2", CUSTOMER_ASN)],
        "ebgp": [],
        "rr_clients": ["10.255.0.1", "10.255.0.2"],
        "networks": ["10.100.0.0/22", "10.100.0.0/24", "10.100.1.0/24",
                      "10.100.2.0/24", "10.100.3.0/24"],
    },
    "r4": {
        "asn": ISPA_ASN,
        "rid": "10.255.1.4",
        "lo": "10.255.1.4/32",
        "ifaces": [("eth0", "10.0.14.4/24")],
        "ospf_nets": [],
        "ibgp": [],
        "ebgp": [("10.0.14.1", CUSTOMER_ASN)],
        "networks": ["203.0.113.0/24", "192.0.2.0/24"],
    },
    "r5": {
        "asn": ISPB_ASN,
        "rid": "10.255.2.5",
        "lo": "10.255.2.5/32",
        "ifaces": [("eth0", "10.0.25.5/24")],
        "ospf_nets": [],
        "ibgp": [],
        "ebgp": [("10.0.25.2", CUSTOMER_ASN)],
        "networks": ["198.51.100.0/24", "192.0.2.0/24"],
    },
}

# Selective advertisement: which prefixes each border router sends
R1_ALLOWED = ["10.100.0.0/22", "10.100.0.0/24", "10.100.1.0/24"]
R2_ALLOWED = ["10.100.0.0/22", "10.100.2.0/24", "10.100.3.0/24"]
AGG_PREFIX = "10.100.0.0/22"
PREPEND_COUNT = 3
LOCPREF = 200


def gen_config(name):
    """Generate complete FRR config for a router from topology data."""
    r = ROUTERS[name]
    lines = ["frr defaults traditional", f"hostname {name}", "!"]

    # Interface blocks (preserve skeleton addressing)
    lines += ["interface lo", f" ip address {r['lo']}", "!"]
    for iface, addr in r["ifaces"]:
        lines += [f"interface {iface}", f" ip address {addr}", "!"]

    # Policy objects for border routers
    if name == "r1":
        # Separate prefix-list for aggregate (prepend target) vs specifics
        lines += [
            f"ip prefix-list AGG_ONLY seq 5 permit {AGG_PREFIX}",
            "ip prefix-list R1_EXPORT seq 5 permit 10.100.0.0/24",
            "ip prefix-list R1_EXPORT seq 10 permit 10.100.1.0/24",
            "!",
            # Inbound: set local-pref for outbound TE (AS-wide propagation)
            "route-map ISPA_IN permit 10",
            f" set local-preference {LOCPREF}",
            "!",
            # Outbound: prepend aggregate, permit specifics, implicit deny rest
            "route-map ISPA_OUT permit 10",
            " match ip address prefix-list AGG_ONLY",
            " set as-path prepend " + " ".join([str(CUSTOMER_ASN)] * PREPEND_COUNT),
            "!",
            "route-map ISPA_OUT permit 20",
            " match ip address prefix-list R1_EXPORT",
            "!",
        ]
    elif name == "r2":
        for i, pfx in enumerate(R2_ALLOWED):
            lines.append(f"ip prefix-list R2_EXPORT seq {(i+1)*5} permit {pfx}")
        lines += [
            "!",
            "route-map ISPB_OUT permit 10",
            " match ip address prefix-list R2_EXPORT",
            "!",
        ]

    # OSPF block
    if r["ospf_nets"]:
        lines += ["router ospf", f" ospf router-id {r['rid']}"]
        for net in r["ospf_nets"]:
            lines.append(f" network {net} area 0")
        lines.append("!")

    # BGP block
    lines += [f"router bgp {r['asn']}", f" bgp router-id {r['rid']}",
              " no bgp ebgp-requires-policy"]
    for peer, asn in r["ibgp"]:
        lines += [f" neighbor {peer} remote-as {asn}",
                  f" neighbor {peer} update-source lo"]
    for peer, asn in r["ebgp"]:
        lines.append(f" neighbor {peer} remote-as {asn}")
    lines.append(" !")

    # Address-family
    lines.append(" address-family ipv4 unicast")
    for net in r.get("networks", []):
        lines.append(f"  network {net}")
    for client in r.get("rr_clients", []):
        lines.append(f"  neighbor {client} route-reflector-client")
    # Next-hop-self on border routers toward RR
    if r["ebgp"] and r["ibgp"]:
        for peer, _ in r["ibgp"]:
            lines.append(f"  neighbor {peer} next-hop-self")
    # Route-map applications
    if name == "r1":
        lines += [
            "  neighbor 10.0.14.4 route-map ISPA_IN in",
            "  neighbor 10.0.14.4 route-map ISPA_OUT out",
        ]
    elif name == "r2":
        lines.append("  neighbor 10.0.25.5 route-map ISPB_OUT out")

    lines += [" exit-address-family", "!"]
    return "\n".join(lines) + "\n"


def main():
    for name in ROUTERS:
        config = gen_config(name)
        path = os.path.join(CONFIG_DIR, f"{name}.conf")
        with open(path, "w") as f:
            f.write(config)
        print(f"Generated {path} ({len(config)} bytes)")


if __name__ == "__main__":
    main()
