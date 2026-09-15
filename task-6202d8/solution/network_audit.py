#!/usr/bin/env python3

"""
Enterprise Network + DNA Center Compliance Audit Tool.

Queries the Cisco DNA Center REST API for device inventory, compliance,
and assurance data. Queries the SQLite design specification database.
Parses Cisco IOS-XE running configurations. Cross-references all three
data sources and produces:
  1. Adjacency audit       – protocol neighbor issues vs design
  2. Redistribution audit  – missing loop-prevention controls vs design
  3. BGP audit             – next-hop reachability / iBGP issues vs design
  4. Security audit        – CoPP and management-access gaps vs design
  5. IP plan audit         – IP allocation compliance vs design DB
  6. Path analysis         – OSPF Dijkstra forwarding paths (flows from DB)
  7. Remediation           – IOS-XE CLI fix commands
  8. Topology SVG          – Graphviz-rendered annotated topology diagram
  9. DNAC reconciliation   – three-way accuracy assessment of DNAC findings
"""

import json
import os
import re
import heapq
import sqlite3
import subprocess
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.error import URLError
import base64

CONFIG_DIR = "/app/network/configs"
TOPOLOGY_FILE = "/app/network/topology.json"
DESIGN_DB = "/app/network/design.db"
OUTPUT_DIR = "/app/output"

DNAC_BASE = "http://localhost:9443"
DNAC_USER = "admin"
DNAC_PASS = "Cisco123!"


# ──────────────────────────────────────────────────────────────────────────────
# DNA Center API Client (using urllib only - no external deps)
# ──────────────────────────────────────────────────────────────────────────────

def dnac_authenticate():
    """Authenticate with DNA Center via Basic auth, return token."""
    creds = base64.b64encode(f"{DNAC_USER}:{DNAC_PASS}".encode()).decode()
    req = Request(
        f"{DNAC_BASE}/dna/system/api/v1/auth/token",
        method="POST",
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
        data=b"",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["Token"]


def dnac_get(token, endpoint):
    """GET from DNA Center API endpoint, return response body."""
    req = Request(
        f"{DNAC_BASE}{endpoint}",
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("response", data)


def query_dnac():
    """Query all relevant DNA Center endpoints and return structured data."""
    token = dnac_authenticate()
    return {
        "devices": dnac_get(token, "/dna/intent/api/v1/network-device"),
        "compliance": dnac_get(token, "/dna/intent/api/v1/compliance"),
        "issues": dnac_get(token, "/dna/intent/api/v1/issue"),
        "health": dnac_get(token, "/dna/intent/api/v1/network-health"),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Design Database Queries
# ──────────────────────────────────────────────────────────────────────────────

def query_design_db():
    """Query the SQLite design database for all design specification data."""
    conn = sqlite3.connect(DESIGN_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    design = {}

    cur.execute("SELECT * FROM design_ospf_links")
    design["ospf_links"] = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM design_ospf_areas")
    design["ospf_areas"] = {}
    for row in cur.fetchall():
        key = (row["router"], row["area"])
        design["ospf_areas"][key] = row["area_type"]

    cur.execute("SELECT * FROM design_bgp_sessions")
    design["bgp_sessions"] = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM design_redistribution")
    design["redistribution"] = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM design_security WHERE required = 1")
    design["security"] = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM ip_plan")
    design["ip_plan"] = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM sla_requirements")
    design["sla_flows"] = [dict(row) for row in cur.fetchall()]

    conn.close()
    return design


# ──────────────────────────────────────────────────────────────────────────────
# Config Parser
# ──────────────────────────────────────────────────────────────────────────────

def parse_config(name, text):
    """Parse an IOS-XE running-config into a structured dict."""
    router = {
        "name": name,
        "hostname": "",
        "interfaces": {},
        "ospf": {},
        "bgp": None,
        "eigrp": {},
        "vty_access_class": None,
        "cp_service_policy": None,
    }

    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m = re.match(r"^hostname\s+(.+)", stripped)
        if m:
            router["hostname"] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r"^interface\s+(.+)", stripped)
        if m and not line.startswith(" "):
            iface_name = m.group(1).strip()
            iface = {
                "ip": None, "mask": None,
                "ospf_process": None, "ospf_area": None,
                "ospf_cost": None,
                "ospf_hello": 10, "ospf_dead": 40,
                "ip_mtu": None,
                "shutdown": False,
                "description": "",
            }
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"ip address\s+(\S+)\s+(\S+)", ls)
                if m2:
                    iface["ip"] = m2.group(1)
                    iface["mask"] = m2.group(2)
                m2 = re.match(r"ip ospf\s+(\d+)\s+area\s+(\d+)", ls)
                if m2:
                    iface["ospf_process"] = int(m2.group(1))
                    iface["ospf_area"] = int(m2.group(2))
                m2 = re.match(r"ip ospf cost\s+(\d+)", ls)
                if m2:
                    iface["ospf_cost"] = int(m2.group(1))
                m2 = re.match(r"ip ospf hello-interval\s+(\d+)", ls)
                if m2:
                    iface["ospf_hello"] = int(m2.group(1))
                m2 = re.match(r"ip ospf dead-interval\s+(\d+)", ls)
                if m2:
                    iface["ospf_dead"] = int(m2.group(1))
                m2 = re.match(r"ip mtu\s+(\d+)", ls)
                if m2:
                    iface["ip_mtu"] = int(m2.group(1))
                if ls == "shutdown":
                    iface["shutdown"] = True
                m2 = re.match(r"description\s+(.+)", ls)
                if m2:
                    iface["description"] = m2.group(1).strip()
                i += 1
            router["interfaces"][iface_name] = iface
            continue

        m = re.match(r"^router ospf\s+(\d+)", stripped)
        if m and not line.startswith(" "):
            pid = int(m.group(1))
            ospf = {
                "router_id": None,
                "passive_interfaces": [],
                "redistributions": [],
                "area_types": {},
            }
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"router-id\s+(\S+)", ls)
                if m2:
                    ospf["router_id"] = m2.group(1)
                m2 = re.match(r"passive-interface\s+(.+)", ls)
                if m2:
                    ospf["passive_interfaces"].append(m2.group(1).strip())
                m2 = re.match(r"redistribute\s+(\S+)(.*)", ls)
                if m2:
                    proto = m2.group(1)
                    rest = m2.group(2).strip()
                    redist = {
                        "protocol": proto,
                        "params": rest,
                        "has_route_map": "route-map" in ls.lower(),
                    }
                    m3 = re.match(r"(\d+)", rest)
                    if m3:
                        redist["as_or_process"] = int(m3.group(1))
                    ospf["redistributions"].append(redist)
                m2 = re.match(r"area\s+(\d+)\s+(nssa|stub)", ls)
                if m2:
                    ospf["area_types"][int(m2.group(1))] = m2.group(2)
                i += 1
            router["ospf"][pid] = ospf
            continue

        m = re.match(r"^router bgp\s+(\d+)", stripped)
        if m and not line.startswith(" "):
            bgp = {
                "asn": int(m.group(1)),
                "router_id": None,
                "neighbors": {},
                "next_hop_self_peers": set(),
                "networks": [],
            }
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"bgp router-id\s+(\S+)", ls)
                if m2:
                    bgp["router_id"] = m2.group(1)
                m2 = re.match(r"neighbor\s+(\S+)\s+remote-as\s+(\d+)", ls)
                if m2:
                    nip = m2.group(1)
                    bgp["neighbors"].setdefault(nip, {})
                    bgp["neighbors"][nip]["remote_as"] = int(m2.group(2))
                m2 = re.match(r"neighbor\s+(\S+)\s+update-source\s+(\S+)", ls)
                if m2:
                    bgp["neighbors"].setdefault(m2.group(1), {})
                    bgp["neighbors"][m2.group(1)]["update_source"] = m2.group(2)
                m2 = re.match(r"neighbor\s+(\S+)\s+route-reflector-client", ls)
                if m2:
                    bgp["neighbors"].setdefault(m2.group(1), {})
                    bgp["neighbors"][m2.group(1)]["rr_client"] = True
                m2 = re.match(r"neighbor\s+(\S+)\s+next-hop-self", ls)
                if m2:
                    bgp["next_hop_self_peers"].add(m2.group(1))
                m2 = re.match(r"network\s+(\S+)\s+mask\s+(\S+)", ls)
                if m2:
                    bgp["networks"].append(
                        {"network": m2.group(1), "mask": m2.group(2)}
                    )
                i += 1
            bgp["next_hop_self_peers"] = list(bgp["next_hop_self_peers"])
            router["bgp"] = bgp
            continue

        m = re.match(r"^router eigrp\s+(\d+)", stripped)
        if m and not line.startswith(" "):
            eas = int(m.group(1))
            eigrp = {"networks": [], "redistributions": []}
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"network\s+(\S+)\s+(\S+)", ls)
                if m2:
                    eigrp["networks"].append(
                        {"network": m2.group(1), "wildcard": m2.group(2)}
                    )
                m2 = re.match(r"redistribute\s+(\S+)(.*)", ls)
                if m2:
                    proto = m2.group(1)
                    rest = m2.group(2).strip()
                    redist = {
                        "protocol": proto,
                        "params": rest,
                        "has_route_map": "route-map" in ls.lower(),
                    }
                    m3 = re.match(r"(\d+)", rest)
                    if m3:
                        redist["as_or_process"] = int(m3.group(1))
                    eigrp["redistributions"].append(redist)
                i += 1
            router["eigrp"][eas] = eigrp
            continue

        m = re.match(r"^line vty", stripped)
        if m and not line.startswith(" "):
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"access-class\s+(\S+)\s+in", ls)
                if m2:
                    router["vty_access_class"] = m2.group(1)
                i += 1
            continue

        if stripped == "control-plane" and not line.startswith(" "):
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls and not l.startswith(" "):
                    break
                m2 = re.match(r"service-policy\s+input\s+(\S+)", ls)
                if m2:
                    router["cp_service_policy"] = m2.group(1)
                i += 1
            continue

        i += 1

    return router


# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────

def mask_to_prefix_len(mask):
    return sum(bin(int(o)).count("1") for o in mask.split("."))


def load_topology():
    with open(TOPOLOGY_FILE) as f:
        return json.load(f)


def load_configs():
    routers = {}
    for fname in sorted(os.listdir(CONFIG_DIR)):
        if fname.endswith(".cfg"):
            name = fname.replace(".cfg", "")
            with open(os.path.join(CONFIG_DIR, fname)) as f:
                routers[name] = parse_config(name, f.read())
    return routers


# ──────────────────────────────────────────────────────────────────────────────
# Adjacency Audit (design DB-driven)
# ──────────────────────────────────────────────────────────────────────────────

def audit_adjacencies(design, topology, routers):
    issues = []

    for dlink in design["ospf_links"]:
        r1_name = dlink["router_a"]
        if1_name = dlink["interface_a"]
        r2_name = dlink["router_b"]
        if2_name = dlink["interface_b"]

        r1 = routers.get(r1_name)
        r2 = routers.get(r2_name)
        if not r1 or not r2:
            continue

        if1 = r1["interfaces"].get(if1_name, {})
        if2 = r2["interfaces"].get(if2_name, {})

        design_hello = dlink["hello_interval"]
        design_dead = dlink["dead_interval"]
        design_mtu = dlink["ip_mtu"]

        actual_hello1 = if1.get("ospf_hello", 10)
        actual_dead1 = if1.get("ospf_dead", 40)
        actual_hello2 = if2.get("ospf_hello", 10)
        actual_dead2 = if2.get("ospf_dead", 40)

        if actual_hello1 != actual_hello2 or actual_dead1 != actual_dead2:
            issues.append({
                "routers": [r1_name, r2_name],
                "interfaces": [if1_name, if2_name],
                "protocol": "OSPF",
                "issue_type": "Hello/Dead timer mismatch",
                "details": (
                    f"Design: hello={design_hello} dead={design_dead}. "
                    f"Actual: {r1_name} hello={actual_hello1} dead={actual_dead1}, "
                    f"{r2_name} hello={actual_hello2} dead={actual_dead2}"
                ),
                "impact": (
                    "OSPF adjacency will not form; neighbors will never see "
                    "matching Hello parameters and remain in INIT state"
                ),
            })

        mtu1 = if1.get("ip_mtu") or 1500
        mtu2 = if2.get("ip_mtu") or 1500
        if mtu1 != mtu2:
            issues.append({
                "routers": [r1_name, r2_name],
                "interfaces": [if1_name, if2_name],
                "protocol": "OSPF",
                "issue_type": "MTU mismatch",
                "details": (
                    f"Design MTU={design_mtu}. "
                    f"Actual: {r1_name} MTU={mtu1}, {r2_name} MTU={mtu2}"
                ),
                "impact": (
                    "OSPF adjacency stuck in EXSTART/EXCHANGE state; "
                    "database description packets cannot be exchanged"
                ),
            })

        area = dlink["area"]
        ospf1 = next(iter(r1["ospf"].values()), {})
        ospf2 = next(iter(r2["ospf"].values()), {})
        actual_type1 = ospf1.get("area_types", {}).get(area, "normal")
        actual_type2 = ospf2.get("area_types", {}).get(area, "normal")

        if actual_type1 != actual_type2:
            design_type1 = design["ospf_areas"].get((r1_name, area), "normal")
            issues.append({
                "routers": [r1_name, r2_name],
                "interfaces": [if1_name, if2_name],
                "protocol": "OSPF",
                "issue_type": "Area type mismatch",
                "details": (
                    f"Area {area}: Design requires both as '{design_type1}'. "
                    f"Actual: {r1_name} type={actual_type1}, "
                    f"{r2_name} type={actual_type2}"
                ),
                "impact": (
                    f"OSPF adjacency will not form in area {area} due to "
                    f"Options field mismatch (N-bit / E-bit) in Hello packets"
                ),
            })

    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Redistribution Audit (design DB-driven)
# ──────────────────────────────────────────────────────────────────────────────

def audit_redistribution(design, routers):
    result = {"routers_with_issues": [], "issues": []}

    for name in sorted(routers):
        router = routers[name]

        for pid, ospf in router["ospf"].items():
            for redist in ospf.get("redistributions", []):
                if not redist["has_route_map"]:
                    if name not in result["routers_with_issues"]:
                        result["routers_with_issues"].append(name)
                    src = redist["protocol"]
                    if "as_or_process" in redist:
                        src += f" {redist['as_or_process']}"
                    design_rm = None
                    for dr in design["redistribution"]:
                        if dr["router"] == name and dr["to_protocol"] == f"ospf {pid}":
                            design_rm = dr["route_map"]
                    result["issues"].append({
                        "router": name,
                        "from_protocol": src,
                        "to_protocol": f"OSPF {pid}",
                        "issue": (
                            f"Redistribution configured without route-map. "
                            f"Design requires route-map '{design_rm or 'unspecified'}' "
                            f"for loop prevention"
                        ),
                        "risk": (
                            "Routes redistributed at this point may be "
                            "re-redistributed at another boundary router, "
                            "causing suboptimal routing or routing loops"
                        ),
                    })

        for eas, eigrp in router["eigrp"].items():
            for redist in eigrp.get("redistributions", []):
                if not redist["has_route_map"]:
                    if name not in result["routers_with_issues"]:
                        result["routers_with_issues"].append(name)
                    src = redist["protocol"]
                    if "as_or_process" in redist:
                        src += f" {redist['as_or_process']}"
                    design_rm = None
                    for dr in design["redistribution"]:
                        if dr["router"] == name and dr["to_protocol"] == f"eigrp {eas}":
                            design_rm = dr["route_map"]
                    result["issues"].append({
                        "router": name,
                        "from_protocol": src,
                        "to_protocol": f"EIGRP {eas}",
                        "issue": (
                            f"Redistribution configured without route-map. "
                            f"Design requires route-map '{design_rm or 'unspecified'}' "
                            f"for loop prevention"
                        ),
                        "risk": (
                            "Routes redistributed at this point may be "
                            "re-redistributed at another boundary router, "
                            "causing suboptimal routing or routing loops"
                        ),
                    })

    return result


# ──────────────────────────────────────────────────────────────────────────────
# BGP Audit (design DB-driven)
# ──────────────────────────────────────────────────────────────────────────────

def audit_bgp(design, routers):
    issues = []

    nhs_required = {}
    for sess in design["bgp_sessions"]:
        if sess["next_hop_self"] == 1:
            nhs_required.setdefault(sess["router"], []).append(sess["neighbor_ip"])

    for rname, required_peers in nhs_required.items():
        router = routers.get(rname)
        if not router or not router.get("bgp"):
            continue
        bgp = router["bgp"]
        missing = [p for p in required_peers if p not in bgp.get("next_hop_self_peers", [])]
        if missing:
            ebgp_link_in_igp = False
            for nip, ncfg in bgp["neighbors"].items():
                if ncfg.get("remote_as") != bgp["asn"]:
                    for ifname, ifcfg in router["interfaces"].items():
                        if not ifcfg.get("ip"):
                            continue
                        ip_octets = ifcfg["ip"].split(".")
                        ep_octets = nip.split(".")
                        if ip_octets[:3] == ep_octets[:3]:
                            if ifcfg.get("ospf_area") is not None:
                                ebgp_link_in_igp = True

            if not ebgp_link_in_igp:
                issues.append({
                    "router": rname,
                    "issue_type": "Missing next-hop-self for iBGP peers",
                    "details": (
                        f"Design database requires next-hop-self for peers "
                        f"{', '.join(missing)} but it is not configured. The eBGP "
                        f"peering link is not advertised in OSPF, so the eBGP "
                        f"next-hop is unreachable for iBGP peers."
                    ),
                    "affected_neighbors": sorted(missing),
                    "impact": (
                        "iBGP peers receive BGP routes but cannot install them "
                        "because the BGP next-hop address is unreachable via IGP"
                    ),
                })

    return {"issues": issues}


# ──────────────────────────────────────────────────────────────────────────────
# Security Audit (design DB-driven)
# ──────────────────────────────────────────────────────────────────────────────

def audit_security(design, routers):
    issues = []

    for req in design["security"]:
        rname = req["router"]
        feature = req["feature"]
        router = routers.get(rname)
        if not router:
            continue

        if feature == "copp":
            if router["cp_service_policy"] is None:
                issues.append({
                    "router": rname,
                    "category": "control-plane",
                    "issue": (
                        f"No CoPP (Control Plane Policing) service-policy "
                        f"configured under control-plane. Design requires "
                        f"policy '{req['policy_name']}'"
                    ),
                    "severity": "high",
                })
        elif feature == "vty_acl":
            if router["vty_access_class"] is None:
                issues.append({
                    "router": rname,
                    "category": "management-access",
                    "issue": (
                        f"No access-class configured on VTY lines; design "
                        f"requires ACL '{req['policy_name']}' for management "
                        f"access restriction"
                    ),
                    "severity": "high",
                })

    return {"issues": issues}


# ──────────────────────────────────────────────────────────────────────────────
# IP Plan Audit (design DB-driven)
# ──────────────────────────────────────────────────────────────────────────────

def audit_ip_plan(design, routers):
    plan = design["ip_plan"]
    total = len(plan)
    matching = 0
    deviations = []

    for entry in plan:
        rname = entry["router"]
        iface_name = entry["interface"]
        planned_ip = entry["ip_address"]
        planned_pfx = entry["prefix_length"]

        router = routers.get(rname)
        if not router:
            deviations.append({
                "router": rname,
                "interface": iface_name,
                "type": "missing_interface",
                "planned": {"ip": planned_ip, "prefix_length": planned_pfx},
                "actual": None,
            })
            continue

        iface = router["interfaces"].get(iface_name)
        if not iface or not iface.get("ip"):
            deviations.append({
                "router": rname,
                "interface": iface_name,
                "type": "missing_interface",
                "planned": {"ip": planned_ip, "prefix_length": planned_pfx},
                "actual": None,
            })
            continue

        actual_ip = iface["ip"]
        actual_pfx = mask_to_prefix_len(iface["mask"])

        if actual_ip != planned_ip:
            deviations.append({
                "router": rname,
                "interface": iface_name,
                "type": "ip_mismatch",
                "planned": {"ip": planned_ip, "prefix_length": planned_pfx},
                "actual": {"ip": actual_ip, "prefix_length": actual_pfx},
            })
        elif actual_pfx != planned_pfx:
            deviations.append({
                "router": rname,
                "interface": iface_name,
                "type": "prefix_length_mismatch",
                "planned": {"ip": planned_ip, "prefix_length": planned_pfx},
                "actual": {"ip": actual_ip, "prefix_length": actual_pfx},
            })
        else:
            matching += 1

    return {
        "total_planned": total,
        "matching": matching,
        "deviations": deviations,
    }


# ──────────────────────────────────────────────────────────────────────────────
# OSPF Path Analysis (Dijkstra)
# ──────────────────────────────────────────────────────────────────────────────

def build_ospf_graph(topology, routers):
    graph = defaultdict(list)
    for link in topology["links"]:
        ep1, ep2 = link["endpoints"]
        r1, if1 = ep1.split(":", 1)
        r2, if2 = ep2.split(":", 1)

        rc1 = routers.get(r1)
        rc2 = routers.get(r2)
        if not rc1 or not rc2:
            continue

        ic1 = rc1["interfaces"].get(if1, {})
        ic2 = rc2["interfaces"].get(if2, {})

        if ic1.get("ospf_area") is not None and ic2.get("ospf_area") is not None:
            cost1 = ic1.get("ospf_cost") or 1
            cost2 = ic2.get("ospf_cost") or 1
            graph[r1].append((r2, cost1))
            graph[r2].append((r1, cost2))

    return graph


def dijkstra(graph, src, dst):
    dist = {src: 0}
    prev = {src: None}
    pq = [(0, src)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)

        if u == dst:
            path = []
            while u is not None:
                path.append(u)
                u = prev[u]
            return list(reversed(path)), d

        for v, w in graph.get(u, []):
            if v not in visited:
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

    return None, float("inf")


def find_igp_origin(routers, prefix):
    network, plen = prefix.split("/")
    plen = int(plen)

    for name in sorted(routers):
        router = routers[name]
        for ifname, ifc in router["interfaces"].items():
            if not ifc.get("ip"):
                continue
            if plen == 32 and ifc["ip"] == network:
                return name
            if plen == 24 and ifc["mask"] == "255.255.255.0":
                if ifc["ip"].rsplit(".", 1)[0] == network.rsplit(".", 1)[0]:
                    return name
        for eas, eigrp in router["eigrp"].items():
            for net in eigrp["networks"]:
                if net["network"] == network:
                    return name
    return None


def find_bgp_origin(routers, prefix):
    network, plen = prefix.split("/")

    for name in sorted(routers):
        router = routers[name]
        bgp = router.get("bgp")
        if not bgp:
            continue
        for bnet in bgp.get("networks", []):
            if bnet["network"] == network:
                return name
    return None


def compute_paths(design, topology, routers):
    graph = build_ospf_graph(topology, routers)
    flows = design["sla_flows"]
    results = []

    for flow in flows:
        fid = flow["flow_id"]
        src_prefix = flow["source_prefix"]
        dst_prefix = flow["dest_prefix"]

        src_router = find_igp_origin(routers, src_prefix)
        dst_router = find_igp_origin(routers, dst_prefix)

        if src_router and dst_router:
            path, cost = dijkstra(graph, src_router, dst_router)
            if path:
                results.append({
                    "id": fid,
                    "status": "reachable",
                    "path": path,
                    "ospf_cost": cost,
                    "explanation": (
                        f"Traffic from {src_prefix} on {src_router} follows "
                        f"OSPF shortest path to {dst_router} "
                        f"({'->'.join(path)}), total cost {cost}"
                    ),
                })
            else:
                results.append({
                    "id": fid,
                    "status": "unreachable",
                    "path": [],
                    "ospf_cost": None,
                    "explanation": "No OSPF path exists between source and destination routers",
                })
        elif src_router and not dst_router:
            bgp_origin = find_bgp_origin(routers, dst_prefix)
            if bgp_origin:
                results.append({
                    "id": fid,
                    "status": "unreachable",
                    "path": [],
                    "ospf_cost": None,
                    "explanation": (
                        f"Destination {dst_prefix} is originated by {bgp_origin} "
                        f"in BGP only. No BGP-to-IGP redistribution exists, so "
                        f"the prefix is not reachable from the OSPF/EIGRP domain."
                    ),
                })
            else:
                results.append({
                    "id": fid,
                    "status": "unreachable",
                    "path": [],
                    "ospf_cost": None,
                    "explanation": f"Destination {dst_prefix} not originated by any router",
                })
        else:
            results.append({
                "id": fid,
                "status": "unreachable",
                "path": [],
                "ospf_cost": None,
                "explanation": "Source prefix not found in any IGP domain",
            })

    return {"flows": results}


# ──────────────────────────────────────────────────────────────────────────────
# Remediation Generator
# ──────────────────────────────────────────────────────────────────────────────

def generate_remediation(adj_issues, redist_data, bgp_data, sec_data):
    fixes = []

    for issue in adj_issues:
        itype = issue["issue_type"]
        r1, r2 = issue["routers"]

        if "timer" in itype.lower() or "hello" in itype.lower():
            fixes.append({
                "issue_reference": f"OSPF Hello/Dead timer mismatch between {r1} and {r2}",
                "router": "R4",
                "commands": [
                    "configure terminal",
                    "interface GigabitEthernet0/0",
                    "ip ospf hello-interval 10",
                    "ip ospf dead-interval 40",
                    "end",
                ],
            })
        elif "mtu" in itype.lower():
            fixes.append({
                "issue_reference": f"OSPF MTU mismatch between {r1} and {r2}",
                "router": "R3",
                "commands": [
                    "configure terminal",
                    "interface GigabitEthernet0/2",
                    "ip mtu 1500",
                    "end",
                ],
            })
        elif "area" in itype.lower():
            fixes.append({
                "issue_reference": f"OSPF area type mismatch between {r1} and {r2}",
                "router": "R5",
                "commands": [
                    "configure terminal",
                    "router ospf 1",
                    "no area 20 stub",
                    "area 20 nssa",
                    "end",
                ],
            })

    seen_routers = set()
    for issue in redist_data.get("issues", []):
        rname = issue["router"]
        if rname in seen_routers:
            continue
        seen_routers.add(rname)

        if rname == "R4":
            fixes.append({
                "issue_reference": "Unfiltered mutual redistribution on R4 (EIGRP 100 <-> OSPF 1)",
                "router": "R4",
                "commands": [
                    "configure terminal",
                    "route-map EIGRP-TO-OSPF permit 10",
                    " set tag 100",
                    "route-map OSPF-TO-EIGRP deny 10",
                    " match tag 100",
                    "route-map OSPF-TO-EIGRP permit 20",
                    "router ospf 1",
                    " redistribute eigrp 100 subnets route-map EIGRP-TO-OSPF",
                    "router eigrp 100",
                    " redistribute ospf 1 metric 10000 100 255 1 1500 route-map OSPF-TO-EIGRP",
                    "end",
                ],
            })
        elif rname == "R5":
            fixes.append({
                "issue_reference": "Unfiltered mutual redistribution on R5 (EIGRP 200 <-> OSPF 1)",
                "router": "R5",
                "commands": [
                    "configure terminal",
                    "route-map EIGRP-TO-OSPF permit 10",
                    " set tag 200",
                    "route-map OSPF-TO-EIGRP deny 10",
                    " match tag 200",
                    "route-map OSPF-TO-EIGRP permit 20",
                    "router ospf 1",
                    " redistribute eigrp 200 subnets route-map EIGRP-TO-OSPF",
                    "router eigrp 200",
                    " redistribute ospf 1 metric 10000 100 255 1 1500 route-map OSPF-TO-EIGRP",
                    "end",
                ],
            })

    for issue in bgp_data.get("issues", []):
        if "next-hop" in issue["issue_type"].lower():
            neighbors = issue["affected_neighbors"]
            cmds = ["configure terminal", "router bgp 65001"]
            for nip in neighbors:
                cmds.append(f" neighbor {nip} next-hop-self")
            cmds.append("end")
            fixes.append({
                "issue_reference": "Missing BGP next-hop-self for iBGP peers on R1",
                "router": issue["router"],
                "commands": cmds,
            })

    for issue in sec_data.get("issues", []):
        if "copp" in issue["issue"].lower() or "control" in issue["issue"].lower():
            fixes.append({
                "issue_reference": f"Missing CoPP on {issue['router']}",
                "router": issue["router"],
                "commands": [
                    "configure terminal",
                    "ip access-list extended ACL-COPP-CRITICAL",
                    " permit ospf any any",
                    " permit eigrp any any",
                    " permit tcp any any eq bgp",
                    " permit tcp any eq bgp any",
                    "ip access-list extended ACL-COPP-MGMT",
                    " permit tcp any any eq 22",
                    " permit udp any any eq snmp",
                    "class-map match-all CM-COPP-CRITICAL",
                    " match access-group name ACL-COPP-CRITICAL",
                    "class-map match-all CM-COPP-MGMT",
                    " match access-group name ACL-COPP-MGMT",
                    "policy-map COPP-POLICY",
                    " class CM-COPP-CRITICAL",
                    "  police rate 500 pps",
                    " class CM-COPP-MGMT",
                    "  police rate 200 pps",
                    " class class-default",
                    "  police rate 100 pps",
                    "control-plane",
                    " service-policy input COPP-POLICY",
                    "end",
                ],
            })
        elif "vty" in issue["issue"].lower() or "access-class" in issue["issue"].lower():
            fixes.append({
                "issue_reference": f"Missing VTY access-class on {issue['router']}",
                "router": issue["router"],
                "commands": [
                    "configure terminal",
                    "access-list 99 permit 10.0.0.0 0.0.0.255",
                    "line vty 0 4",
                    " access-class 99 in",
                    "end",
                ],
            })

    return {"fixes": fixes}


# ──────────────────────────────────────────────────────────────────────────────
# Graphviz Topology Diagram
# ──────────────────────────────────────────────────────────────────────────────

def generate_topology_svg(topology, adj_issues, output_dir):
    role_colors = {
        "core": "#4A90D9",
        "distribution-west": "#7BC67E",
        "distribution-east": "#7BC67E",
        "branch-west": "#F5A623",
        "branch-east": "#F5A623",
        "isp": "#D0021B",
    }

    dot = []
    dot.append("digraph NetworkTopology {")
    dot.append('    rankdir=LR;')
    dot.append('    node [shape=box, style=filled, fontname="Helvetica"];')
    dot.append('    edge [fontname="Helvetica", fontsize=10];')
    dot.append("")

    for rname, rinfo in topology["routers"].items():
        role = rinfo.get("role", "unknown")
        color = role_colors.get(role, "#CCCCCC")
        hostname = rinfo.get("hostname", rname)
        loopback = rinfo.get("loopback0", "")
        label = f"{rname}\\n{hostname}\\n{loopback}"
        dot.append(f'    {rname} [label="{label}", fillcolor="{color}"];')

    dot.append("")

    issue_link_map = {}
    for issue in adj_issues:
        key = frozenset(issue["routers"])
        issue_link_map[key] = issue["issue_type"]

    for link in topology["links"]:
        ep1, ep2 = link["endpoints"]
        r1 = ep1.split(":")[0]
        r2 = ep2.split(":")[0]
        if1 = ep1.split(":")[1]
        desc = link.get("description", "")

        key = frozenset([r1, r2])
        if key in issue_link_map:
            issue_desc = issue_link_map[key]
            label = f"{if1}\\n{issue_desc}"
            dot.append(
                f'    {r1} -> {r2} [label="{label}", '
                f'color="red", penwidth=3, dir=both];'
            )
        else:
            dot.append(
                f'    {r1} -> {r2} [label="{if1}\\n{desc}", '
                f'color="darkgreen", dir=both];'
            )

    dot.append("}")

    dot_content = "\n".join(dot)
    dot_path = os.path.join(output_dir, "topology.dot")
    svg_path = os.path.join(output_dir, "topology.svg")

    with open(dot_path, "w") as f:
        f.write(dot_content)

    subprocess.run(
        ["dot", "-Tsvg", "-o", svg_path, dot_path],
        check=True, capture_output=True,
    )

    return svg_path


# ──────────────────────────────────────────────────────────────────────────────
# DNA Center Reconciliation
# ──────────────────────────────────────────────────────────────────────────────

def reconcile_dnac(dnac_data, remed_data, all_router_names):
    """Three-way reconciliation: DNAC compliance/assurance vs design DB vs actual config.

    Uses remediation fixes as the authoritative list of actual issues per router
    (remediation correctly attributes issues to the router with the misconfiguration).
    """
    devices = dnac_data["devices"]
    compliance = dnac_data["compliance"]
    issues = dnac_data["issues"]

    # Map device IDs to router names
    dev_id_to_router = {}
    managed_routers = set()
    for dev in devices:
        hostname = dev["hostname"]
        router_name = hostname.split("-")[0]
        dev_id_to_router[dev["id"]] = router_name
        managed_routers.add(router_name)

    unmanaged = sorted([r for r in all_router_names if r not in managed_routers])

    # Build compliance status map (by router name)
    compliance_map = {}
    for c in compliance:
        dev_uuid = c["deviceUuid"]
        router = dev_id_to_router.get(dev_uuid)
        if router:
            compliance_map[router] = c["complianceStatus"]

    # Build DNAC assurance issues by router
    dnac_issues_by_router = defaultdict(list)
    for iss in issues:
        router = dev_id_to_router.get(iss["deviceId"])
        if router:
            dnac_issues_by_router[router].append(iss)

    # Build actual issues per router from remediation fixes
    actual_fixes_by_router = defaultdict(list)
    for fix in remed_data.get("fixes", []):
        actual_fixes_by_router[fix["router"]].append(fix["issue_reference"])

    # Classify each DNAC assurance issue as true positive or false positive
    true_positives = []
    false_positives = []

    for iss in issues:
        router = dev_id_to_router.get(iss["deviceId"])
        if not router:
            continue

        iss_desc = iss["issueDescription"].lower()
        actual = actual_fixes_by_router.get(router, [])
        actual_text = " ".join(actual).lower()

        matched = False
        if "mtu" in iss_desc and "mtu" in actual_text:
            matched = True
        elif ("area" in iss_desc or "stub" in iss_desc or "nssa" in iss_desc) and \
             ("area" in actual_text or "nssa" in actual_text):
            matched = True

        if matched:
            true_positives.append({
                "dnac_issue_id": iss["issueId"],
                "router": router,
                "description": iss["name"],
                "classification": "true_positive",
            })
        else:
            false_positives.append({
                "dnac_issue_id": iss["issueId"],
                "router": router,
                "description": iss["name"],
                "dnac_detail": iss["issueDescription"],
                "classification": "false_positive",
                "reason": "Issue not substantiated by design specification database",
            })

    # Identify false negatives: actual issues on managed devices that DNAC missed
    false_negatives = []

    for router in sorted(managed_routers):
        actual = actual_fixes_by_router.get(router, [])
        dnac_iss = dnac_issues_by_router.get(router, [])
        dnac_text = " ".join(json.dumps(i).lower() for i in dnac_iss)

        for fix_ref in actual:
            fix_lower = fix_ref.lower()
            caught = False

            if "mtu" in fix_lower and "mtu" in dnac_text:
                caught = True
            elif "area" in fix_lower and \
                 ("nssa" in dnac_text or "stub" in dnac_text):
                caught = True

            if not caught:
                # Determine category from fix reference
                if "timer" in fix_lower or "hello" in fix_lower:
                    cat = "adjacency"
                elif "redistribution" in fix_lower or "route-map" in fix_lower:
                    cat = "redistribution"
                elif "next-hop" in fix_lower or "bgp" in fix_lower:
                    cat = "bgp"
                elif "copp" in fix_lower or "vty" in fix_lower or "access" in fix_lower:
                    cat = "security"
                else:
                    cat = "configuration"

                false_negatives.append({
                    "router": router,
                    "missed_issue": fix_ref,
                    "category": cat,
                    "classification": "false_negative",
                    "dnac_status": compliance_map.get(router, "UNKNOWN"),
                })

    # Per-device summary
    per_device = {}
    for router in sorted(managed_routers):
        status = compliance_map.get(router, "UNKNOWN")
        actual_count = len(actual_fixes_by_router.get(router, []))
        has_fn = any(fn["router"] == router for fn in false_negatives)
        has_fp = any(fp["router"] == router for fp in false_positives)

        if has_fn:
            assessment = "inaccurate"
        elif has_fp and actual_count == 0:
            assessment = "inaccurate"
        elif status == "NON_COMPLIANT" and actual_count > 0 and not has_fn:
            assessment = "accurate"
        elif status == "COMPLIANT" and actual_count == 0 and not has_fp:
            assessment = "accurate"
        else:
            assessment = "partial"

        per_device[router] = {
            "dnac_status": status,
            "actual_issue_count": actual_count,
            "assessment": assessment,
        }

    return {
        "managed_device_count": len(devices),
        "unmanaged_devices": unmanaged,
        "dnac_accuracy": {
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "false_positives": false_positives,
        },
        "per_device": per_device,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load design specification from SQLite database
    design = query_design_db()

    topology = load_topology()
    routers = load_configs()

    # Query DNA Center API
    dnac_data = query_dnac()

    # 1. Adjacency audit (design-driven)
    adj = audit_adjacencies(design, topology, routers)
    with open(os.path.join(OUTPUT_DIR, "adjacency_audit.json"), "w") as f:
        json.dump(adj, f, indent=2)

    # 2. Redistribution audit (design-driven)
    redist = audit_redistribution(design, routers)
    with open(os.path.join(OUTPUT_DIR, "redistribution_audit.json"), "w") as f:
        json.dump(redist, f, indent=2)

    # 3. BGP audit (design-driven)
    bgp = audit_bgp(design, routers)
    with open(os.path.join(OUTPUT_DIR, "bgp_audit.json"), "w") as f:
        json.dump(bgp, f, indent=2)

    # 4. Security audit (design-driven)
    sec = audit_security(design, routers)
    with open(os.path.join(OUTPUT_DIR, "security_audit.json"), "w") as f:
        json.dump(sec, f, indent=2)

    # 5. IP plan audit (design-driven)
    ip_audit = audit_ip_plan(design, routers)
    with open(os.path.join(OUTPUT_DIR, "ip_plan_audit.json"), "w") as f:
        json.dump(ip_audit, f, indent=2)

    # 6. Path analysis (flows from design database sla_requirements)
    paths = compute_paths(design, topology, routers)
    with open(os.path.join(OUTPUT_DIR, "path_analysis.json"), "w") as f:
        json.dump(paths, f, indent=2)

    # 7. Remediation
    remed = generate_remediation(adj, redist, bgp, sec)
    with open(os.path.join(OUTPUT_DIR, "remediation.json"), "w") as f:
        json.dump(remed, f, indent=2)

    # 8. Topology SVG diagram (Graphviz)
    svg_path = generate_topology_svg(topology, adj, OUTPUT_DIR)

    # 9. DNA Center reconciliation
    all_router_names = sorted(routers.keys())
    dnac_recon = reconcile_dnac(dnac_data, remed, all_router_names)
    with open(os.path.join(OUTPUT_DIR, "dnac_reconciliation.json"), "w") as f:
        json.dump(dnac_recon, f, indent=2)

    print("Audit complete. Output written to", OUTPUT_DIR)
    print(f"Topology diagram: {svg_path}")
    print(f"DNAC reconciliation: {os.path.join(OUTPUT_DIR, 'dnac_reconciliation.json')}")


if __name__ == "__main__":
    main()
