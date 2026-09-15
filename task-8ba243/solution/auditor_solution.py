#!/usr/bin/env python3
"""
VXLAN-EVPN Fabric Configuration Drift Auditor
Compares switch running configs against a YAML source-of-truth data model.

"""

import ipaddress
import json
import os
import re
import sys
from pathlib import Path

import yaml


# ============================================================
# IP helpers
# ============================================================

def peer_ip_of(cidr):
    """Given an IP/31, return the other host address in the /31 subnet."""
    ip_str, prefix = cidr.split("/")
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = list(net.hosts())
    ip = ipaddress.ip_address(ip_str)
    return str(hosts[1] if ip == hosts[0] else hosts[0])


# ============================================================
# Build expected state from YAML model
# ============================================================

def build_expected_states(model):
    """Derive the expected configuration state for every device."""
    fabric = model["fabric"]
    spine_asn = fabric["bgp"]["spine_asn"]
    tenants = fabric["tenants"]

    # Map leaf name -> pair info
    leaf_lookup = {}
    for pair in fabric["leaf_pairs"]:
        for member in pair["members"]:
            leaf_lookup[member["name"]] = {"pair": pair, "member": member}

    states = {}

    # --- Spines ---
    for spine in fabric["spines"]:
        name = spine["name"]
        st = {
            "hostname": name,
            "is_spine": True,
            "bgp_asn": spine_asn,
            "loopback0": spine["loopback0"],
            "router_id": spine["loopback0"].split("/")[0],
            "interfaces": {},
            "bgp_overlay_neighbors": {},
            "bgp_underlay_neighbors": {},
        }

        for intf in spine["interfaces"]:
            st["interfaces"][intf["name"]] = intf["ip"]
            # Underlay peer = other end of /31
            p_ip = peer_ip_of(intf["ip"])
            p_asn = leaf_lookup[intf["peer"]]["pair"]["asn"]
            st["bgp_underlay_neighbors"][p_ip] = p_asn

        # Overlay peers = all leaf loopback0 IPs
        for pair in fabric["leaf_pairs"]:
            for member in pair["members"]:
                lo0_ip = member["loopback0"].split("/")[0]
                st["bgp_overlay_neighbors"][lo0_ip] = pair["asn"]

        states[name] = st

    # --- Leaves ---
    for pair in fabric["leaf_pairs"]:
        for member in pair["members"]:
            name = member["name"]
            st = {
                "hostname": name,
                "is_spine": False,
                "bgp_asn": pair["asn"],
                "loopback0": member["loopback0"],
                "loopback1": member["loopback1"],
                "router_id": member["loopback0"].split("/")[0],
                "interfaces": {},
                "bgp_overlay_neighbors": {},
                "bgp_underlay_neighbors": {},
                "vxlan_source": "Loopback1",
                "vlan_vni_map": {},
                "vrf_vni_map": {},
                "mlag_domain_id": pair["mlag_domain_id"],
                "mlag_interfaces": list(member["mlag_interfaces"]),
                "mlag_peer_address": peer_ip_of(member["mlag_ip"]),
                "vrf_route_targets": {},
            }

            # Derive leaf P2P IPs and underlay neighbors from spine interfaces
            for spine in fabric["spines"]:
                for intf in spine["interfaces"]:
                    if intf["peer"] == name:
                        leaf_ip = peer_ip_of(intf["ip"])
                        st["interfaces"][intf["peer_intf"]] = f"{leaf_ip}/31"
                        spine_ip = intf["ip"].split("/")[0]
                        st["bgp_underlay_neighbors"][spine_ip] = spine_asn

            # Overlay peers = all spine loopback0s
            for spine in fabric["spines"]:
                lo0 = spine["loopback0"].split("/")[0]
                st["bgp_overlay_neighbors"][lo0] = spine_asn

            # Tenant VLAN/VNI + VRF
            for tenant in tenants:
                for vlan in tenant["vlans"]:
                    if vlan["id"] in pair["vlans"]:
                        st["vlan_vni_map"][vlan["id"]] = vlan["vni"]
                if tenant["name"] in pair["vrfs"]:
                    vni = tenant["vrf_vni"]
                    st["vrf_vni_map"][tenant["name"]] = vni
                    st["vrf_route_targets"][tenant["name"]] = f"{vni}:{vni}"

            states[name] = st

    return states


# ============================================================
# Parse an EOS running-config
# ============================================================

def parse_eos_config(text):
    """Extract structured state from EOS configuration text."""
    st = {
        "hostname": None,
        "bgp_asn": None,
        "router_id": None,
        "interfaces": {},
        "bgp_neighbors": {},
        "vxlan_source": None,
        "vlan_vni_map": {},
        "vrf_vni_map": {},
        "mlag_domain_id": None,
        "mlag_member_intfs": [],
        "vrf_route_targets": {},
    }

    lines = text.split("\n")

    # Hostname
    for line in lines:
        m = re.match(r"^hostname\s+(\S+)", line)
        if m:
            st["hostname"] = m.group(1)
            break

    # Interfaces (including Vxlan1)
    i = 0
    while i < len(lines):
        m = re.match(r"^interface\s+(.+)", lines[i])
        if m:
            intf_name = m.group(1).strip()
            intf_data = {}
            i += 1
            while i < len(lines):
                s = lines[i].strip()
                if s == "!" or (lines[i] and not lines[i][0].isspace()):
                    break
                ip_m = re.match(r"ip address\s+(\S+)", s)
                if ip_m:
                    intf_data["ip"] = ip_m.group(1)
                cg_m = re.match(r"channel-group\s+(\d+)", s)
                if cg_m:
                    intf_data["channel_group"] = int(cg_m.group(1))
                    st["mlag_member_intfs"].append(intf_name)
                vs_m = re.match(r"vxlan source-interface\s+(\S+)", s)
                if vs_m:
                    st["vxlan_source"] = vs_m.group(1)
                vv_m = re.match(r"vxlan vlan\s+(\d+)\s+vni\s+(\d+)", s)
                if vv_m:
                    st["vlan_vni_map"][int(vv_m.group(1))] = int(vv_m.group(2))
                vrf_m = re.match(r"vxlan vrf\s+(\S+)\s+vni\s+(\d+)", s)
                if vrf_m:
                    st["vrf_vni_map"][vrf_m.group(1)] = int(vrf_m.group(2))
                i += 1
            st["interfaces"][intf_name] = intf_data
            continue
        i += 1

    # BGP
    i = 0
    while i < len(lines):
        m = re.match(r"^router bgp\s+(\d+)", lines[i])
        if m:
            st["bgp_asn"] = int(m.group(1))
            i += 1
            in_vrf = None
            while i < len(lines):
                s = lines[i].strip()
                # End of router bgp block
                if lines[i] and not lines[i][0].isspace() and s != "!":
                    break
                if re.match(r"router-id\s+", s):
                    st["router_id"] = s.split()[-1]
                # Top-level BGP neighbors
                nbr_m = re.match(r"neighbor\s+(\S+)\s+remote-as\s+(\d+)", s)
                if nbr_m and in_vrf is None:
                    st["bgp_neighbors"][nbr_m.group(1)] = int(nbr_m.group(2))
                # VRF sub-section
                vrf_m = re.match(r"vrf\s+(\S+)", s)
                if vrf_m and not s.startswith("neighbor"):
                    in_vrf = vrf_m.group(1)
                    st["vrf_route_targets"][in_vrf] = {"import": [], "export": []}
                if in_vrf:
                    rt_m = re.match(r"route-target\s+(import|export)\s+evpn\s+(\S+)", s)
                    if rt_m:
                        st["vrf_route_targets"][in_vrf][rt_m.group(1)].append(
                            rt_m.group(2)
                        )
                i += 1
            continue
        i += 1

    # MLAG
    i = 0
    while i < len(lines):
        if lines[i].strip() == "mlag configuration":
            i += 1
            while i < len(lines):
                s = lines[i].strip()
                if s == "!" or (lines[i] and not lines[i][0].isspace()):
                    break
                dm = re.match(r"domain-id\s+(\S+)", s)
                if dm:
                    st["mlag_domain_id"] = dm.group(1)
                i += 1
            continue
        i += 1

    return st


# ============================================================
# Compare expected vs actual → findings
# ============================================================

def compare_device(expected, actual):
    """Return list of drift findings for one device."""
    dev = expected["hostname"]
    findings = []

    # --- Interface IPs (P2P links) ---
    for intf, exp_ip in expected.get("interfaces", {}).items():
        act_ip = actual["interfaces"].get(intf, {}).get("ip")
        if act_ip and act_ip != exp_ip:
            findings.append({
                "device": dev,
                "section": "interface",
                "description": f"Interface {intf} has wrong IP address",
                "expected": exp_ip,
                "actual": act_ip,
            })

    # --- Loopback0 ---
    if "loopback0" in expected:
        exp_lo = expected["loopback0"]
        act_lo = actual["interfaces"].get("Loopback0", {}).get("ip")
        if act_lo and act_lo != exp_lo:
            findings.append({
                "device": dev,
                "section": "interface",
                "description": "Loopback0 has wrong IP address",
                "expected": exp_lo,
                "actual": act_lo,
            })

    # --- BGP overlay neighbors ---
    for nbr, exp_as in expected.get("bgp_overlay_neighbors", {}).items():
        act_as = actual["bgp_neighbors"].get(nbr)
        if act_as is None:
            findings.append({
                "device": dev,
                "section": "bgp",
                "description": f"Missing BGP overlay neighbor {nbr}",
                "expected": str(exp_as),
                "actual": "missing",
            })
        elif act_as != exp_as:
            findings.append({
                "device": dev,
                "section": "bgp",
                "description": f"BGP overlay neighbor {nbr} has wrong remote-as",
                "expected": str(exp_as),
                "actual": str(act_as),
            })

    # --- BGP underlay neighbors ---
    for nbr, exp_as in expected.get("bgp_underlay_neighbors", {}).items():
        act_as = actual["bgp_neighbors"].get(nbr)
        if act_as is None:
            findings.append({
                "device": dev,
                "section": "bgp",
                "description": f"Missing BGP underlay neighbor {nbr}",
                "expected": str(exp_as),
                "actual": "missing",
            })
        elif act_as != exp_as:
            findings.append({
                "device": dev,
                "section": "bgp",
                "description": f"BGP underlay neighbor {nbr} has wrong remote-as",
                "expected": str(exp_as),
                "actual": str(act_as),
            })

    # --- VXLAN source interface ---
    if "vxlan_source" in expected:
        if actual["vxlan_source"] != expected["vxlan_source"]:
            findings.append({
                "device": dev,
                "section": "vxlan",
                "description": "Wrong VXLAN tunnel source interface",
                "expected": expected["vxlan_source"],
                "actual": actual["vxlan_source"] or "not configured",
            })

    # --- VLAN-VNI mappings ---
    for vid, exp_vni in expected.get("vlan_vni_map", {}).items():
        act_vni = actual["vlan_vni_map"].get(vid)
        if act_vni is None:
            findings.append({
                "device": dev,
                "section": "vxlan",
                "description": f"Missing VXLAN VNI mapping for VLAN {vid}",
                "expected": str(exp_vni),
                "actual": "missing",
            })
        elif act_vni != exp_vni:
            findings.append({
                "device": dev,
                "section": "vxlan",
                "description": f"Wrong VXLAN VNI for VLAN {vid}",
                "expected": str(exp_vni),
                "actual": str(act_vni),
            })

    # --- MLAG domain-id ---
    if "mlag_domain_id" in expected:
        if actual["mlag_domain_id"] != expected["mlag_domain_id"]:
            findings.append({
                "device": dev,
                "section": "mlag",
                "description": "Wrong MLAG domain-id",
                "expected": expected["mlag_domain_id"],
                "actual": actual["mlag_domain_id"] or "not configured",
            })

    # --- MLAG member interfaces ---
    if "mlag_interfaces" in expected:
        exp_set = set(expected["mlag_interfaces"])
        act_set = set(actual["mlag_member_intfs"])
        if exp_set != act_set:
            findings.append({
                "device": dev,
                "section": "mlag",
                "description": "Wrong MLAG peer-link member interfaces",
                "expected": ",".join(sorted(exp_set)),
                "actual": ",".join(sorted(act_set)),
            })

    # --- VRF route-targets ---
    if "vrf_route_targets" in expected:
        for vrf, exp_rt in expected["vrf_route_targets"].items():
            act_rt_data = actual["vrf_route_targets"].get(vrf, {})
            act_import = act_rt_data.get("import", [])
            act_export = act_rt_data.get("export", [])
            if exp_rt not in act_import or exp_rt not in act_export:
                bad = act_import[0] if act_import else (
                    act_export[0] if act_export else "missing"
                )
                findings.append({
                    "device": dev,
                    "section": "vrf",
                    "description": f"Wrong VRF {vrf} route-target",
                    "expected": exp_rt,
                    "actual": bad,
                })

    return findings


# ============================================================
# Fix config text
# ============================================================

def fix_config(text, expected, actual):
    """Apply corrections to config text so it matches expected state."""
    lines = text.split("\n")

    # --- Fix interface IPs (P2P links) ---
    for intf, exp_ip in expected.get("interfaces", {}).items():
        act_ip = actual["interfaces"].get(intf, {}).get("ip")
        if act_ip and act_ip != exp_ip:
            in_sect = False
            for idx, line in enumerate(lines):
                if re.match(rf"^interface\s+{re.escape(intf)}\s*$", line):
                    in_sect = True
                elif in_sect:
                    if line.strip() == "!" or (line and not line[0].isspace()):
                        break
                    if act_ip in line:
                        lines[idx] = line.replace(act_ip, exp_ip)

    # --- Fix Loopback0 IP ---
    if "loopback0" in expected:
        act_lo = actual["interfaces"].get("Loopback0", {}).get("ip")
        if act_lo and act_lo != expected["loopback0"]:
            in_sect = False
            for idx, line in enumerate(lines):
                if re.match(r"^interface\s+Loopback0\s*$", line):
                    in_sect = True
                elif in_sect:
                    if line.strip() == "!" or (line and not line[0].isspace()):
                        break
                    if act_lo in line:
                        lines[idx] = line.replace(act_lo, expected["loopback0"])

    # --- Fix BGP overlay neighbor remote-as ---
    for nbr, exp_as in expected.get("bgp_overlay_neighbors", {}).items():
        act_as = actual["bgp_neighbors"].get(nbr)
        if act_as is not None and act_as != exp_as:
            old = f"neighbor {nbr} remote-as {act_as}"
            new = f"neighbor {nbr} remote-as {exp_as}"
            for idx, line in enumerate(lines):
                if old in line:
                    lines[idx] = line.replace(old, new)

    # --- Insert missing BGP underlay neighbors ---
    for nbr, exp_as in expected.get("bgp_underlay_neighbors", {}).items():
        act_as = actual["bgp_neighbors"].get(nbr)
        if act_as is None:
            # Find last "neighbor <IP> remote-as <ASN>" line and insert after it
            insert_after = None
            for idx, line in enumerate(lines):
                if re.match(r"\s+neighbor\s+\d+\.\d+\.\d+\.\d+\s+remote-as\s+\d+", line):
                    insert_after = idx
            if insert_after is not None:
                lines.insert(insert_after + 1,
                             f"   neighbor {nbr} peer group IPv4-UNDERLAY-PEERS")
                lines.insert(insert_after + 2,
                             f"   neighbor {nbr} remote-as {exp_as}")

    # --- Fix VXLAN source interface ---
    if "vxlan_source" in expected:
        act_src = actual.get("vxlan_source")
        if act_src and act_src != expected["vxlan_source"]:
            old = f"vxlan source-interface {act_src}"
            new = f"vxlan source-interface {expected['vxlan_source']}"
            for idx, line in enumerate(lines):
                if old in line:
                    lines[idx] = line.replace(old, new)

    # --- Fix wrong VLAN-VNI values ---
    for vid, exp_vni in expected.get("vlan_vni_map", {}).items():
        act_vni = actual["vlan_vni_map"].get(vid)
        if act_vni is not None and act_vni != exp_vni:
            old = f"vxlan vlan {vid} vni {act_vni}"
            new = f"vxlan vlan {vid} vni {exp_vni}"
            for idx, line in enumerate(lines):
                if old in line:
                    lines[idx] = line.replace(old, new)

    # --- Insert missing VLAN-VNI mappings ---
    for vid, exp_vni in expected.get("vlan_vni_map", {}).items():
        if vid not in actual["vlan_vni_map"]:
            # Insert before the vrf vni line in the Vxlan1 section
            for idx, line in enumerate(lines):
                if "vxlan vrf" in line:
                    lines.insert(idx, f"   vxlan vlan {vid} vni {exp_vni}")
                    break

    # --- Fix MLAG domain-id ---
    if "mlag_domain_id" in expected:
        act_did = actual.get("mlag_domain_id")
        if act_did and act_did != expected["mlag_domain_id"]:
            old = f"domain-id {act_did}"
            new = f"domain-id {expected['mlag_domain_id']}"
            for idx, line in enumerate(lines):
                if old in line:
                    lines[idx] = line.replace(old, new)

    # --- Fix MLAG member interfaces ---
    if "mlag_interfaces" in expected:
        exp_set = set(expected["mlag_interfaces"])
        act_set = set(actual["mlag_member_intfs"])
        if exp_set != act_set:
            wrong = act_set - exp_set
            missing = exp_set - act_set

            # Remove wrong member interface sections
            new_lines = []
            skip = False
            for line in lines:
                if skip:
                    if line.strip() == "!":
                        skip = False
                        # skip the trailing ! of removed section
                        continue
                    if line and not line[0].isspace():
                        skip = False
                        new_lines.append(line)
                    continue
                remove = False
                for wm in wrong:
                    if re.match(rf"^interface\s+{re.escape(wm)}\s*$", line):
                        remove = True
                        break
                if remove:
                    skip = True
                    continue
                new_lines.append(line)
            lines = new_lines

            # Fix missing members: replace content of their interface section
            for mm in missing:
                for idx, line in enumerate(lines):
                    if re.match(rf"^interface\s+{re.escape(mm)}\s*$", line):
                        # Find end of this section
                        end = idx + 1
                        while end < len(lines) and lines[end].startswith("   ") and lines[end].strip() != "!":
                            end += 1
                        # Determine peer name
                        hostname = expected["hostname"]
                        if hostname.endswith("a"):
                            peer = hostname[:-1] + "b"
                        else:
                            peer = hostname[:-1] + "a"
                        new_section = [
                            f"   description MLAG_PEER_{peer.upper()}_{mm}",
                            "   channel-group 1000 mode active",
                        ]
                        lines[idx + 1:end] = new_section
                        break

    # --- Fix VRF route-targets ---
    if "vrf_route_targets" in expected:
        for vrf, exp_rt in expected["vrf_route_targets"].items():
            act_data = actual["vrf_route_targets"].get(vrf, {})
            for direction in ("import", "export"):
                for art in act_data.get(direction, []):
                    if art != exp_rt:
                        old = f"route-target {direction} evpn {art}"
                        new = f"route-target {direction} evpn {exp_rt}"
                        for idx, line in enumerate(lines):
                            if old in line:
                                lines[idx] = line.replace(old, new)

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def main():
    # Load source-of-truth model
    with open("/app/fabric.yaml") as f:
        model = yaml.safe_load(f)

    expected_states = build_expected_states(model)
    all_findings = []

    os.makedirs("/app/configs_fixed", exist_ok=True)

    for cfg_path in sorted(Path("/app/configs").glob("*.cfg")):
        device_name = cfg_path.stem
        if device_name not in expected_states:
            print(f"WARNING: No expected state for {device_name}, skipping")
            continue

        config_text = cfg_path.read_text()
        actual = parse_eos_config(config_text)
        expected = expected_states[device_name]
        findings = compare_device(expected, actual)
        all_findings.extend(findings)

        # Generate fixed config
        fixed = fix_config(config_text, expected, actual)
        Path(f"/app/configs_fixed/{cfg_path.name}").write_text(fixed)
        print(f"  {device_name}: {len(findings)} finding(s)")

    # Write drift report
    with open("/app/drift_report.json", "w") as f:
        json.dump(all_findings, f, indent=2)

    print(f"\nTotal drift findings: {len(all_findings)}")
    print("Drift report written to /app/drift_report.json")
    print("Corrected configs written to /app/configs_fixed/")


if __name__ == "__main__":
    main()
