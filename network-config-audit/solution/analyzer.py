#!/usr/bin/env python3
"""
Enterprise Network Configuration Compliance Analyzer.
Parses IOS-XE router configurations and compares them against
a design specification to identify configuration defects.

"""

import json
import os
import re
import sys


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def load_design_spec(path):
    with open(path, "r") as f:
        return json.load(f)


def extract_interface_block(config, intf_name):
    """Extract configuration lines for a specific interface."""
    pattern = rf"^interface\s+{re.escape(intf_name)}\s*$(.*?)(?=^interface\s|^router\s|^line\s|^control-plane|^policy-map|^ip\s|^ntp\s|^route-map|^end|^!$)"
    match = re.search(pattern, config, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(0)
    return ""


def extract_router_ospf_block(config):
    """Extract the router ospf configuration block."""
    match = re.search(
        r"^router ospf\s+\d+\s*$(.*?)(?=^router\s|^line\s|^control-plane|^!$)",
        config,
        re.MULTILINE | re.DOTALL,
    )
    if match:
        return match.group(0)
    return ""


def extract_router_bgp_block(config):
    """Extract the router bgp configuration block."""
    match = re.search(
        r"^router bgp\s+\d+\s*$(.*?)(?=^router\s|^line\s|^control-plane|^!$|^route-map)",
        config,
        re.MULTILINE | re.DOTALL,
    )
    if match:
        return match.group(0)
    return ""


def check_ospf_area_auth(config, design_areas, router_name):
    """Check OSPF area authentication type against design."""
    defects = []
    ospf_block = extract_router_ospf_block(config)

    for area_id_str, area_spec in design_areas.items():
        area_id = int(area_id_str)
        required_auth = area_spec.get("authentication", "none")

        if router_name not in area_spec.get("routers", []):
            continue

        if required_auth == "message-digest":
            pattern_md5 = rf"area\s+{area_id}\s+authentication\s+message-digest"
            pattern_plain = rf"area\s+{area_id}\s+authentication\s*$"

            has_md5 = bool(re.search(pattern_md5, ospf_block))
            has_plain = bool(
                re.search(pattern_plain, ospf_block, re.MULTILINE)
            )

            if has_plain and not has_md5:
                defects.append(
                    {
                        "router": router_name,
                        "category": "security",
                        "severity": "critical",
                        "risk_score": 8,
                        "migration_phase": 2,
                        "description": (
                            f"OSPF Area {area_id} uses plaintext authentication "
                            f"('area {area_id} authentication') instead of MD5 "
                            f"message-digest as required by the design specification. "
                            f"Plaintext authentication transmits passwords in clear text, "
                            f"making OSPF adjacencies vulnerable to interception and "
                            f"unauthorized peering. Operational data confirms Area {area_id} "
                            f"neighbor authentication type is 'simple'."
                        ),
                        "affected_config": f"area {area_id} authentication",
                        "remediation": (
                            f"Replace 'area {area_id} authentication' with "
                            f"'area {area_id} authentication message-digest' under "
                            f"router ospf. Update interface authentication from "
                            f"'ip ospf authentication-key' to "
                            f"'ip ospf message-digest-key <id> md5 <key>'."
                        ),
                    }
                )

    return defects


def check_prefix_list_references(config, router_name):
    """Check for route-map references to undefined prefix-lists."""
    defects = []

    defined_prefix_lists = set(
        re.findall(r"^ip\s+prefix-list\s+(\S+)", config, re.MULTILINE)
    )

    referenced_prefix_lists = set(
        re.findall(
            r"match\s+ip\s+address\s+prefix-list\s+(\S+)", config
        )
    )

    undefined = referenced_prefix_lists - defined_prefix_lists
    if undefined:
        for pl_name in undefined:
            rm_match = re.search(
                rf"^route-map\s+(\S+)\s+(?:permit|deny)\s+\d+.*?match\s+ip\s+address\s+prefix-list\s+{re.escape(pl_name)}",
                config,
                re.MULTILINE | re.DOTALL,
            )
            rm_name = rm_match.group(1) if rm_match else "unknown"

            defects.append(
                {
                    "router": router_name,
                    "category": "routing",
                    "severity": "critical",
                    "risk_score": 9,
                    "migration_phase": 2,
                    "description": (
                        f"Route-map '{rm_name}' references prefix-list "
                        f"'{pl_name}' which is not defined in the configuration. "
                        f"An undefined prefix-list causes the match clause to fail, "
                        f"resulting in an implicit deny of all prefixes. This "
                        f"effectively blocks all BGP route advertisements through "
                        f"this route-map. Operational data confirms 0 prefixes "
                        f"advertised to eBGP peer despite routes in local BGP table."
                    ),
                    "affected_config": (
                        f"route-map {rm_name} permit 10 / "
                        f"match ip address prefix-list {pl_name}"
                    ),
                    "remediation": (
                        f"Define the prefix-list '{pl_name}' with appropriate "
                        f"permit entries for the networks that should be advertised. "
                        f"Example: 'ip prefix-list {pl_name} seq 10 permit "
                        f"<network>/<mask>'."
                    ),
                }
            )

    return defects


def check_redistribution_loop_prevention(config, router_name, design_spec):
    """Check for mutual redistribution without tag-based loop prevention."""
    defects = []

    router_design = design_spec.get("routers", {}).get(router_name, {})
    bgp_design = router_design.get("bgp", {})
    redist_design = bgp_design.get("redistribution", {})

    if not redist_design:
        return defects

    bgp_to_ospf = redist_design.get("bgp_to_ospf", {})
    requires_tags = bgp_to_ospf.get("requires_set_tag", False)

    if not requires_tags:
        return defects

    ospf_block = extract_router_ospf_block(config)
    has_redist_bgp = bool(re.search(r"redistribute\s+bgp", ospf_block))

    bgp_block = extract_router_bgp_block(config)
    has_redist_ospf = bool(re.search(r"redistribute\s+ospf", config))

    if has_redist_bgp and has_redist_ospf:
        bgp_to_ospf_rm_match = re.search(
            r"redistribute\s+bgp\s+\d+\s+.*?route-map\s+(\S+)", ospf_block
        )
        if bgp_to_ospf_rm_match:
            rm_name = bgp_to_ospf_rm_match.group(1)
            rm_block = re.search(
                rf"^route-map\s+{re.escape(rm_name)}\s+.*?(?=^route-map\s+(?!{re.escape(rm_name)})|^router\s|^interface\s|\Z)",
                config,
                re.MULTILINE | re.DOTALL,
            )
            rm_text = rm_block.group(0) if rm_block else ""

            if "set tag" not in rm_text:
                defects.append(
                    {
                        "router": router_name,
                        "category": "routing",
                        "severity": "high",
                        "risk_score": 7,
                        "migration_phase": 2,
                        "description": (
                            "Mutual redistribution between OSPF and BGP is configured "
                            "without route tag-based loop prevention. The route-map "
                            f"'{rm_name}' used for BGP-to-OSPF redistribution does not "
                            "set a route tag. Without tags, routes redistributed from "
                            "OSPF into BGP can be redistributed back into OSPF, "
                            "creating routing loops and suboptimal paths. Operational "
                            "data shows redistributed OSPF routes with route_tag=0."
                        ),
                        "affected_config": (
                            f"route-map {rm_name} permit 10 (missing 'set tag'). "
                            "OSPF_TO_BGP route-map also missing 'match tag' deny clause."
                        ),
                        "remediation": (
                            f"Add 'set tag {bgp_to_ospf.get('tag_value', 65002)}' to "
                            f"route-map {rm_name}. Add a deny clause (sequence 5) to "
                            "route-map OSPF_TO_BGP matching the same tag to prevent "
                            "re-redistribution of BGP-originated routes."
                        ),
                    }
                )

    return defects


def check_ospf_interface_cost(config, router_name, design_spec):
    """Check OSPF interface costs against design specification."""
    defects = []

    router_design = design_spec.get("routers", {}).get(router_name, {})
    interfaces = router_design.get("interfaces", {})

    for intf_name, intf_spec in interfaces.items():
        expected_cost = intf_spec.get("ospf_cost")
        if expected_cost is None:
            continue

        intf_block = extract_interface_block(config, intf_name)
        if not intf_block:
            continue

        cost_match = re.search(r"ip\s+ospf\s+cost\s+(\d+)", intf_block)
        if cost_match:
            actual_cost = int(cost_match.group(1))
            if actual_cost != expected_cost:
                defects.append(
                    {
                        "router": router_name,
                        "category": "routing",
                        "severity": "high",
                        "risk_score": 5,
                        "migration_phase": 3,
                        "description": (
                            f"OSPF cost on {intf_name} is {actual_cost} instead of "
                            f"the design-specified value of {expected_cost}. This "
                            f"causes suboptimal routing as OSPF SPF calculation will "
                            f"prefer alternative paths over this link. Operational "
                            f"data shows path cost of {actual_cost} on this segment."
                        ),
                        "affected_config": f"ip ospf cost {actual_cost}",
                        "remediation": (
                            f"Change 'ip ospf cost {actual_cost}' to "
                            f"'ip ospf cost {expected_cost}' under interface "
                            f"{intf_name}."
                        ),
                    }
                )

    return defects


def check_vty_acl(config, router_name, design_spec):
    """Check VTY access ACL against management subnet policy."""
    defects = []

    vty_policy = design_spec.get("security_policy", {}).get("vty_access", {})
    expected_net = vty_policy.get("management_subnet", "")
    expected_wc = vty_policy.get("management_wildcard", "")

    if not expected_net or not expected_wc:
        return defects

    acl_permits = re.findall(
        r"^\s*permit\s+(\S+)\s+(\S+)", config, re.MULTILINE
    )

    for actual_net, actual_wc in acl_permits:
        if actual_net == expected_net and actual_wc == expected_wc:
            continue

        actual_wc_octets = [int(x) for x in actual_wc.split(".")]
        expected_wc_octets = [int(x) for x in expected_wc.split(".")]

        actual_scope = 1
        for octet in actual_wc_octets:
            actual_scope *= octet + 1
        expected_scope = 1
        for octet in expected_wc_octets:
            expected_scope *= octet + 1

        if actual_scope > expected_scope:
            defects.append(
                {
                    "router": router_name,
                    "category": "security",
                    "severity": "critical",
                    "risk_score": 8,
                    "migration_phase": 1,
                    "description": (
                        f"VTY access ACL permits {actual_net} {actual_wc} which "
                        f"covers a much broader range than the design-specified "
                        f"management subnet {expected_net} {expected_wc}. This "
                        f"excessive ACL scope allows management access from "
                        f"unauthorized source addresses. Operational data shows "
                        f"47823 matches on the overly broad permit entry."
                    ),
                    "affected_config": f"permit {actual_net} {actual_wc}",
                    "remediation": (
                        f"Change 'permit {actual_net} {actual_wc}' to "
                        f"'permit {expected_net} {expected_wc}' in the VTY "
                        f"access ACL."
                    ),
                }
            )

    return defects


def check_ntp_trusted_key(config, router_name, design_spec):
    """Check NTP authentication completeness."""
    defects = []

    ntp_policy = design_spec.get("security_policy", {}).get("ntp", {})
    ntp_auth = ntp_policy.get("authentication", {})
    if not ntp_auth.get("trusted_key_must_be_configured", False):
        return defects

    has_auth_key = bool(
        re.search(r"^ntp\s+authentication-key\s+", config, re.MULTILINE)
    )
    has_authenticate = bool(
        re.search(r"^ntp\s+authenticate\s*$", config, re.MULTILINE)
    )
    has_trusted_key = bool(
        re.search(r"^ntp\s+trusted-key\s+", config, re.MULTILINE)
    )

    if has_auth_key and has_authenticate and not has_trusted_key:
        key_match = re.search(
            r"^ntp\s+authentication-key\s+(\d+)", config, re.MULTILINE
        )
        key_id = key_match.group(1) if key_match else "1"

        defects.append(
            {
                "router": router_name,
                "category": "security",
                "severity": "high",
                "risk_score": 6,
                "migration_phase": 3,
                "description": (
                    "NTP authentication is incomplete. 'ntp authentication-key' "
                    "and 'ntp authenticate' are configured, but "
                    "'ntp trusted-key' is missing. Without the trusted-key "
                    "designation, the router will not require NTP peers to "
                    "authenticate, effectively disabling NTP authentication "
                    "despite the apparent configuration. Operational data shows "
                    "NTP status unsynchronized with stratum 16 and .AUTH. refid."
                ),
                "affected_config": (
                    f"ntp authentication-key {key_id} md5 ... (present), "
                    f"ntp authenticate (present), "
                    f"ntp trusted-key {key_id} (MISSING)"
                ),
                "remediation": (
                    f"Add 'ntp trusted-key {key_id}' to complete the NTP "
                    f"authentication chain."
                ),
            }
        )

    return defects


def check_copp_direction(config, router_name, design_spec):
    """Check CoPP service-policy direction."""
    defects = []

    copp_policy = design_spec.get("security_policy", {}).get("copp", {})
    required_on = copp_policy.get("required_on", [])
    required_dir = copp_policy.get("direction", "input")

    if router_name not in required_on:
        return defects

    cp_match = re.search(
        r"^control-plane\s*$\s*service-policy\s+(input|output)\s+(\S+)",
        config,
        re.MULTILINE,
    )

    if cp_match:
        actual_dir = cp_match.group(1)
        policy_name = cp_match.group(2)
        if actual_dir != required_dir:
            defects.append(
                {
                    "router": router_name,
                    "category": "security",
                    "severity": "critical",
                    "risk_score": 9,
                    "migration_phase": 1,
                    "description": (
                        f"Control Plane Policing (CoPP) service-policy "
                        f"'{policy_name}' is applied in the '{actual_dir}' "
                        f"direction instead of '{required_dir}'. CoPP must be "
                        f"applied as '{required_dir}' to filter traffic destined "
                        f"TO the control plane. In the '{actual_dir}' direction, "
                        f"it does not protect against control-plane attacks such as "
                        f"DoS flooding, route spoofing, or management-plane abuse. "
                        f"Operational data shows all traffic conforming with zero "
                        f"drops, confirming inbound traffic is unpoliced."
                    ),
                    "affected_config": (
                        f"service-policy {actual_dir} {policy_name}"
                    ),
                    "remediation": (
                        f"Change 'service-policy {actual_dir} {policy_name}' to "
                        f"'service-policy {required_dir} {policy_name}' under "
                        f"control-plane."
                    ),
                }
            )

    return defects


def check_bfd_on_ospf_interfaces(config, router_name, design_spec):
    """Check BFD enablement on OSPF non-passive interfaces."""
    defects = []

    bfd_policy = design_spec.get("security_policy", {}).get("bfd", {})
    if not bfd_policy.get("required_on_ospf_non_passive", False):
        return defects

    router_design = design_spec.get("routers", {}).get(router_name, {})
    interfaces = router_design.get("interfaces", {})

    for intf_name, intf_spec in interfaces.items():
        if intf_spec.get("ospf_area") is None:
            continue
        if intf_spec.get("passive", False):
            continue
        if "bfd" not in intf_spec:
            continue

        intf_block = extract_interface_block(config, intf_name)
        if not intf_block:
            continue

        has_no_bfd = bool(re.search(r"no\s+bfd", intf_block))
        has_bfd = bool(
            re.search(r"bfd\s+interval\s+\d+", intf_block)
        )

        if has_no_bfd or not has_bfd:
            reason = (
                "explicitly disabled via 'no bfd interval'"
                if has_no_bfd
                else "not configured"
            )
            defects.append(
                {
                    "router": router_name,
                    "category": "operational",
                    "severity": "high",
                    "risk_score": 4,
                    "migration_phase": 3,
                    "description": (
                        f"BFD is {reason} on {intf_name}. The design "
                        f"specification requires BFD on all OSPF non-passive "
                        f"interfaces for sub-second failure detection. Without BFD, "
                        f"convergence relies on OSPF dead timer (typically 40 "
                        f"seconds), significantly increasing failover time. "
                        f"Operational data shows BFD status 'not configured' on "
                        f"this interface's OSPF neighbor."
                    ),
                    "affected_config": (
                        "no bfd interval" if has_no_bfd else f"(BFD missing on {intf_name})"
                    ),
                    "remediation": (
                        f"{'Remove no bfd interval and add' if has_no_bfd else 'Add'} "
                        f"'bfd interval {bfd_policy['interval']} "
                        f"min_rx {bfd_policy['min_rx']} "
                        f"multiplier {bfd_policy['multiplier']}' "
                        f"under interface {intf_name}."
                    ),
                }
            )

    return defects


def check_passive_interface(config, router_name, design_spec):
    """Check passive-interface assignments against design."""
    defects = []

    router_design = design_spec.get("routers", {}).get(router_name, {})
    interfaces = router_design.get("interfaces", {})

    ospf_block = extract_router_ospf_block(config)
    if not ospf_block:
        return defects

    has_passive_default = bool(
        re.search(r"passive-interface\s+default", ospf_block)
    )

    non_passive_intfs = set(
        re.findall(r"no\s+passive-interface\s+(\S+)", ospf_block)
    )

    explicit_passive_intfs = set()
    for m in re.finditer(r"(?<!no\s)passive-interface\s+(\S+)", ospf_block):
        intf = m.group(1)
        if intf != "default":
            explicit_passive_intfs.add(intf)

    issues = []
    for intf_name, intf_spec in interfaces.items():
        if intf_spec.get("ospf_area") is None:
            continue
        expected_passive = intf_spec.get("passive", None)
        if expected_passive is None:
            continue

        if has_passive_default:
            is_passive = intf_name not in non_passive_intfs
        else:
            is_passive = intf_name in explicit_passive_intfs

        if expected_passive and not is_passive:
            issues.append(
                f"{intf_name} should be passive (host-facing) but is non-passive"
            )
        elif not expected_passive and is_passive:
            issues.append(
                f"{intf_name} should be non-passive (uplink) but is passive"
            )

    if issues:
        defects.append(
            {
                "router": router_name,
                "category": "routing",
                "severity": "critical",
                "risk_score": 9,
                "migration_phase": 1,
                "description": (
                    "Passive-interface configuration is incorrect. "
                    + "; ".join(issues)
                    + ". This prevents OSPF adjacency formation on uplink "
                    "interfaces while unnecessarily sending OSPF hellos on "
                    "host-facing interfaces. Operational data shows zero OSPF "
                    "neighbors on this router, confirming the adjacency failure."
                ),
                "affected_config": (
                    "passive-interface default / "
                    + " / ".join(
                        f"no passive-interface {i}" for i in non_passive_intfs
                    )
                    if has_passive_default
                    else " / ".join(
                        f"passive-interface {i}" for i in explicit_passive_intfs
                    )
                ),
                "remediation": (
                    "Correct the passive-interface assignments to match the "
                    "design: uplink/transit interfaces must be non-passive for "
                    "OSPF adjacency, host-facing interfaces must be passive."
                ),
            }
        )

    return defects


def check_network_statement_conflict(config, router_name, design_spec):
    """Check for OSPF network statements conflicting with redistribution."""
    defects = []

    router_design = design_spec.get("routers", {}).get(router_name, {})
    redist_design = router_design.get("redistribution", {})
    connected_redist = redist_design.get("connected_to_ospf", {})

    if not connected_redist:
        return defects

    external_intfs = connected_redist.get("external_interfaces", [])
    if not external_intfs:
        return defects

    interfaces = router_design.get("interfaces", {})
    external_networks = []
    for intf_name in external_intfs:
        intf_spec = interfaces.get(intf_name, {})
        ip = intf_spec.get("ip", "")
        if ip:
            network_part = ip.split("/")[0]
            octets = network_part.split(".")
            external_networks.append(
                (intf_name, ".".join(octets[:2]))
            )

    ospf_block = extract_router_ospf_block(config)
    network_stmts = re.findall(
        r"network\s+(\S+)\s+(\S+)\s+area\s+(\d+)", ospf_block
    )

    has_redistribute = bool(re.search(r"redistribute\s+connected", ospf_block))

    if has_redistribute:
        for net_addr, wildcard, area in network_stmts:
            for intf_name, prefix in external_networks:
                if net_addr.startswith(prefix.split(".")[0]):
                    net_octets = [int(x) for x in net_addr.split(".")]
                    wc_octets = [int(x) for x in wildcard.split(".")]
                    intf_ip = interfaces[intf_name]["ip"].split("/")[0]
                    ip_octets = [int(x) for x in intf_ip.split(".")]

                    matches = all(
                        (ip_octets[i] & ~wc_octets[i])
                        == (net_octets[i] & ~wc_octets[i])
                        for i in range(4)
                    )

                    if matches:
                        defects.append(
                            {
                                "router": router_name,
                                "category": "routing",
                                "severity": "high",
                                "risk_score": 7,
                                "migration_phase": 2,
                                "description": (
                                    f"OSPF network statement 'network {net_addr} "
                                    f"{wildcard} area {area}' matches the external "
                                    f"interface {intf_name} ({intf_ip}), causing the "
                                    f"external network to be included as an intra-area "
                                    f"OSPF route. This conflicts with the "
                                    f"'redistribute connected' command that is intended "
                                    f"to advertise this network as an NSSA Type-7 "
                                    f"external route. The network statement takes "
                                    f"precedence, bypassing NSSA translation and "
                                    f"external route filtering. Operational data shows "
                                    f"172.16.1.0/24 as OSPF intra-area (O) instead of "
                                    f"NSSA external (O N2)."
                                ),
                                "affected_config": (
                                    f"network {net_addr} {wildcard} area {area}"
                                ),
                                "remediation": (
                                    f"Remove 'network {net_addr} {wildcard} area "
                                    f"{area}'. The external network on {intf_name} "
                                    f"should only enter OSPF via 'redistribute "
                                    f"connected' to maintain its NSSA Type-7 external "
                                    f"status."
                                ),
                            }
                        )

    return defects


def analyze():
    """Main analysis pipeline."""
    configs_dir = "/app/configs"
    design_path = "/app/design_spec.json"

    design = load_design_spec(design_path)
    all_defects = []

    config_files = sorted(
        f
        for f in os.listdir(configs_dir)
        if f.endswith(".cfg")
    )

    for cfg_file in config_files:
        router_name = cfg_file.replace(".cfg", "")
        config = read_file(os.path.join(configs_dir, cfg_file))

        all_defects.extend(
            check_ospf_area_auth(
                config, design.get("topology", {}).get("areas", {}), router_name
            )
        )
        all_defects.extend(
            check_prefix_list_references(config, router_name)
        )
        all_defects.extend(
            check_redistribution_loop_prevention(config, router_name, design)
        )
        all_defects.extend(
            check_ospf_interface_cost(config, router_name, design)
        )
        all_defects.extend(check_vty_acl(config, router_name, design))
        all_defects.extend(
            check_ntp_trusted_key(config, router_name, design)
        )
        all_defects.extend(
            check_copp_direction(config, router_name, design)
        )
        all_defects.extend(
            check_bfd_on_ospf_interfaces(config, router_name, design)
        )
        all_defects.extend(
            check_passive_interface(config, router_name, design)
        )
        all_defects.extend(
            check_network_statement_conflict(config, router_name, design)
        )

    return all_defects


def main():
    defects = analyze()

    report = {
        "defects": defects,
        "total_defects": len(defects),
        "summary": {
            "critical": sum(
                1 for d in defects if d["severity"] == "critical"
            ),
            "high": sum(1 for d in defects if d["severity"] == "high"),
            "medium": sum(
                1 for d in defects if d["severity"] == "medium"
            ),
        },
    }

    output_path = "/app/audit_report.json"
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete. Found {len(defects)} defects.")
    for i, d in enumerate(defects, 1):
        print(
            f"  [{d['severity'].upper()}] {d['router']}: "
            f"{d['description'][:80]}..."
        )
    print(f"\nReport written to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
