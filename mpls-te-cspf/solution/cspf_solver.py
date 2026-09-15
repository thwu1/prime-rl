#!/usr/bin/env python3
"""
"""

import json
import re
import heapq
import os
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = {'jr': 'http://xml.juniper.net/junos/21.4R3/junos-routing'}


class Link:
    def __init__(self, endpoints, capacity, metric, admin_groups, srlgs):
        self.endpoints = tuple(sorted(endpoints))
        self.capacity = capacity
        self.metric = metric
        self.admin_groups = set(admin_groups)
        self.srlgs = set(srlgs)
        self.reservations = {}

    @property
    def available(self):
        return self.capacity - sum(self.reservations.values())

    @property
    def name(self):
        return f"{self.endpoints[0]}-{self.endpoints[1]}"

    def other_end(self, node):
        return self.endpoints[1] if self.endpoints[0] == node else self.endpoints[0]


class Network:
    def __init__(self, routers, link_data_list):
        self.routers = routers
        self.links = []
        self.adj = defaultdict(list)
        for ld in link_data_list:
            link = Link(ld["endpoints"], ld["capacity"], ld["metric"],
                        ld["admin_groups"], ld["srlgs"])
            self.links.append(link)
            self.adj[link.endpoints[0]].append(link)
            self.adj[link.endpoints[1]].append(link)

    def get_link(self, a, b):
        key = tuple(sorted([a, b]))
        for link in self.links:
            if link.endpoints == key:
                return link
        return None


def parse_ted(path):
    tree = ET.parse(path)
    root = tree.getroot()

    # Navigate into namespace-qualified ted-database-information
    tdi = root.find('jr:ted-database-information', NS)
    if tdi is None:
        # Fallback: root itself might be ted-database-information
        if root.tag.endswith('ted-database-information'):
            tdi = root
        else:
            raise ValueError("Cannot find ted-database-information element")

    id_to_host = {}
    for entry in tdi.findall('jr:ted-database-entry', NS):
        rid = entry.find('jr:ted-database-id', NS).text
        host = entry.find('jr:ted-database-hostname', NS).text
        id_to_host[rid] = host

    seen = set()
    links = []
    for entry in tdi.findall('jr:ted-database-entry', NS):
        from_host = id_to_host[entry.find('jr:ted-database-id', NS).text]
        for lk in entry.findall('jr:ted-link', NS):
            to_host = id_to_host[lk.find('jr:ted-link-to', NS).text]
            key = tuple(sorted([from_host, to_host]))
            if key in seen:
                continue
            seen.add(key)

            metric = int(lk.find('jr:ted-link-te-metric', NS).text)
            bw_bps = int(lk.find('jr:ted-link-maximum-reservable-bandwidth', NS).text)
            capacity = bw_bps // 1_000_000_000

            ag_hex = lk.find('jr:ted-link-admin-group', NS).text
            ag_bits = int(ag_hex, 16)
            admin_groups = {b for b in range(32) if ag_bits & (1 << b)}

            srlgs = set()
            for s in lk.findall('jr:ted-link-srlg', NS):
                srlgs.add(int(s.text))

            links.append({
                "endpoints": key,
                "capacity": capacity,
                "metric": metric,
                "admin_groups": admin_groups,
                "srlgs": srlgs,
            })

    return sorted(id_to_host.values()), links, id_to_host


def parse_configs(configs_dir):
    admin_group_map = {}
    rid_to_host = {}
    lsp_data = defaultdict(lambda: {"constraints": {}})

    for fname in sorted(os.listdir(configs_dir)):
        if not fname.endswith(".conf"):
            continue
        hostname = fname[:-5]

        with open(os.path.join(configs_dir, fname)) as f:
            for line in f:
                line = line.strip()

                m = re.match(r"set interfaces lo0 unit 0 family inet address (\S+)/32", line)
                if m:
                    rid_to_host[m.group(1)] = hostname

                m = re.match(r"set protocols mpls admin-group (\S+) (\d+)", line)
                if m:
                    admin_group_map[m.group(1)] = int(m.group(2))

                m = re.match(r"set protocols mpls label-switched-path (\S+) (.+)", line)
                if m:
                    lsp_name, rest = m.group(1), m.group(2)
                    lsp_data[lsp_name]["source"] = hostname

                    m2 = re.match(r"to (\S+)", rest)
                    if m2:
                        lsp_data[lsp_name]["to_rid"] = m2.group(1)

                    m2 = re.match(r"bandwidth (\S+)", rest)
                    if m2:
                        bw_str = m2.group(1).lower()
                        if bw_str.endswith("g"):
                            lsp_data[lsp_name]["bandwidth"] = int(bw_str[:-1])
                        else:
                            lsp_data[lsp_name]["bandwidth"] = int(bw_str) // 1_000_000_000

                    m2 = re.match(r"setup-priority (\d+)", rest)
                    if m2:
                        lsp_data[lsp_name]["setup_priority"] = int(m2.group(1))

                    m2 = re.match(r"hold-priority (\d+)", rest)
                    if m2:
                        lsp_data[lsp_name]["hold_priority"] = int(m2.group(1))

                    m2 = re.match(r"admin-group include-all (.+)", rest)
                    if m2:
                        lsp_data[lsp_name]["constraints"]["include_all"] = m2.group(1).split()

                    m2 = re.match(r"admin-group include-any (.+)", rest)
                    if m2:
                        lsp_data[lsp_name]["constraints"]["include_any"] = m2.group(1).split()

                    m2 = re.match(r"admin-group exclude (.+)", rest)
                    if m2:
                        lsp_data[lsp_name]["constraints"]["exclude"] = m2.group(1).split()

                    m2 = re.match(r"srlg-diverse (\S+)", rest)
                    if m2:
                        lsp_data[lsp_name]["constraints"]["srlg_diverse_from"] = m2.group(1)

    return admin_group_map, dict(lsp_data), rid_to_host


def dijkstra(network, source, dest, allowed_links):
    pq = [(0, 0, (source,), source)]
    visited = set()
    while pq:
        cost, hops, path, node = heapq.heappop(pq)
        if node in visited:
            continue
        visited.add(node)
        if node == dest:
            return cost, list(path)
        for link in network.adj[node]:
            if link not in allowed_links:
                continue
            nb = link.other_end(node)
            if nb in visited:
                continue
            heapq.heappush(pq, (cost + link.metric, hops + 1, path + (nb,), nb))
    return None, None


def query_nms(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pricing = {}
    for row in conn.execute("SELECT link_key, cost_per_gbps_month FROM link_pricing"):
        pricing[row["link_key"]] = row["cost_per_gbps_month"]

    risk_scores = {}
    for row in conn.execute("SELECT srlg_id, risk_score FROM srlg_risk_scores"):
        risk_scores[row["srlg_id"]] = row["risk_score"]

    customers = {}
    for row in conn.execute("SELECT lsp_name, customer, sla_tier FROM customer_circuits"):
        customers[row["lsp_name"]] = {"customer": row["customer"], "sla_tier": row["sla_tier"]}

    conn.close()
    return pricing, risk_scores, customers


def generate_topology(network, established, lsp_results):
    lines = [
        'digraph topology {',
        '    rankdir=LR;',
        '    node [shape=circle, style=filled, fillcolor=lightblue, fontsize=14];',
    ]

    for router in network.routers:
        lines.append(f'    {router} [label="{router}"];')

    for link in network.links:
        a, b = link.endpoints
        reserved = link.capacity - link.available
        label = f"{reserved}/{link.capacity}G"
        color = "red" if link.available == 0 else "orange" if reserved > 0 else "gray"
        lines.append(f'    {a} -> {b} [label="{label}", color={color}, dir=none, penwidth=2];')

    palette = ["blue", "green", "purple", "cyan", "magenta", "darkgreen", "brown"]
    ci = 0
    for r in lsp_results:
        if r["status"] == "established" and len(r["path"]) > 1:
            path = r["path"]
            for i in range(len(path) - 1):
                lines.append(
                    f'    {path[i]} -> {path[i+1]} '
                    f'[label="{r["name"]}", color={palette[ci % len(palette)]}, '
                    f'style=dashed, penwidth=1, constraint=false];'
                )
            ci += 1

    lines.append('}')

    dot_content = '\n'.join(lines)
    with open("/app/topology.dot", "w") as f:
        f.write(dot_content)

    subprocess.run(
        ["dot", "-Tsvg", "/app/topology.dot", "-o", "/app/topology.svg"],
        check=True,
    )


def solve():
    routers, link_data, ted_id_map = parse_ted("/app/ted_database.xml")
    network = Network(routers, link_data)

    ag_map, lsp_data, cfg_id_map = parse_configs("/app/configs")
    rid_to_host = {**ted_id_map, **cfg_id_map}

    pricing, risk_scores, customers = query_nms("/app/nms.db")

    with open("/app/lsp_order.txt") as f:
        lsp_order = [line.strip() for line in f if line.strip()]

    established = {}
    lsp_results = []

    for lsp_name in lsp_order:
        info = lsp_data[lsp_name]
        source = info["source"]
        dest = rid_to_host[info["to_rid"]]
        bw = info["bandwidth"]
        constraints = info.get("constraints", {})
        setup_pri = info["setup_priority"]
        hold_pri = info["hold_priority"]

        allowed = set(network.links)

        if "include_all" in constraints:
            required = {ag_map[n] for n in constraints["include_all"]}
            allowed = {l for l in allowed if required.issubset(l.admin_groups)}

        if "include_any" in constraints:
            any_of = {ag_map[n] for n in constraints["include_any"]}
            allowed = {l for l in allowed if l.admin_groups & any_of}

        if "exclude" in constraints:
            excluded = {ag_map[n] for n in constraints["exclude"]}
            allowed = {l for l in allowed if not (l.admin_groups & excluded)}

        if "srlg_diverse_from" in constraints:
            ref_name = constraints["srlg_diverse_from"]
            if ref_name in established:
                ref_srlgs = set()
                for link in established[ref_name]["links"]:
                    ref_srlgs |= link.srlgs
                allowed = {l for l in allowed if not (l.srlgs & ref_srlgs)}

        bw_ok = {l for l in allowed if l.available >= bw}
        cost, path = dijkstra(network, source, dest, bw_ok)

        if path is not None:
            path_links = []
            for i in range(len(path) - 1):
                link = network.get_link(path[i], path[i + 1])
                link.reservations[lsp_name] = bw
                path_links.append(link)
            established[lsp_name] = {
                "path": path, "links": path_links, "bandwidth": bw,
                "setup_priority": setup_pri, "hold_priority": hold_pri,
            }
            lsp_results.append({"name": lsp_name, "status": "established",
                                "path": path, "cost": cost})
            continue

        preemptable = {n: i for n, i in established.items()
                       if i["hold_priority"] > setup_pri}

        if not preemptable:
            lsp_results.append({"name": lsp_name, "status": "failed",
                                "path": [], "cost": 0})
            continue

        eff_ok = set()
        for link in allowed:
            eff = link.available
            for pn, pi in preemptable.items():
                if link in pi["links"]:
                    eff += pi["bandwidth"]
            if eff >= bw:
                eff_ok.add(link)

        cost, path = dijkstra(network, source, dest, eff_ok)

        if path is None:
            lsp_results.append({"name": lsp_name, "status": "failed",
                                "path": [], "cost": 0})
            continue

        path_links = [network.get_link(path[i], path[i + 1])
                      for i in range(len(path) - 1)]

        preempted = set()
        for link in sorted(path_links, key=lambda l: l.name):
            while link.available < bw:
                candidates = [(pn, pi) for pn, pi in preemptable.items()
                              if pn not in preempted and link in pi["links"]]
                if not candidates:
                    break
                candidates.sort(key=lambda x: (-x[1]["hold_priority"], x[0]))
                victim_name, victim_info = candidates[0]
                preempted.add(victim_name)
                for vl in victim_info["links"]:
                    del vl.reservations[victim_name]

        for link in path_links:
            link.reservations[lsp_name] = bw

        established[lsp_name] = {
            "path": path, "links": path_links, "bandwidth": bw,
            "setup_priority": setup_pri, "hold_priority": hold_pri,
        }
        lsp_results.append({"name": lsp_name, "status": "established",
                            "path": path, "cost": cost})

        for pn in preempted:
            del established[pn]
            for r in lsp_results:
                if r["name"] == pn:
                    r["status"] = "preempted"
                    r["path"] = []
                    r["cost"] = 0
                    r["preempted_by"] = lsp_name

    # Link utilization
    link_util = {}
    for link in network.links:
        reserved = link.capacity - link.available
        link_util[link.name] = {
            "capacity": link.capacity,
            "reserved": reserved,
            "available": link.available,
        }

    # Billing summary from NMS data
    billing_summary = []
    for r in lsp_results:
        lsp_name = r["name"]
        cust = customers.get(lsp_name, {"customer": "Unknown", "sla_tier": "unknown"})
        if r["status"] == "established":
            path = r["path"]
            path_cost = sum(
                pricing.get(
                    f"{min(path[i], path[i+1])}-{max(path[i], path[i+1])}", 0
                )
                for i in range(len(path) - 1)
            )
            bw = established[lsp_name]["bandwidth"]
            billing_summary.append({
                "lsp_name": lsp_name,
                "customer": cust["customer"],
                "sla_tier": cust["sla_tier"],
                "bandwidth_gbps": bw,
                "monthly_cost_usd": bw * path_cost,
            })
        else:
            billing_summary.append({
                "lsp_name": lsp_name,
                "customer": cust["customer"],
                "sla_tier": cust["sla_tier"],
                "bandwidth_gbps": 0,
                "monthly_cost_usd": 0,
            })

    # Risk assessment from NMS data
    risk_assessment = []
    for r in lsp_results:
        lsp_name = r["name"]
        if r["status"] == "established":
            path_srlgs = set()
            for link in established[lsp_name]["links"]:
                path_srlgs |= link.srlgs
            sorted_srlgs = sorted(path_srlgs)
            max_risk = max(
                (risk_scores.get(s, 0.0) for s in path_srlgs), default=0.0
            )
            risk_assessment.append({
                "lsp_name": lsp_name,
                "path_srlgs": sorted_srlgs,
                "max_risk_score": max_risk,
            })
        else:
            risk_assessment.append({
                "lsp_name": lsp_name,
                "path_srlgs": [],
                "max_risk_score": 0.0,
            })

    # Generate Graphviz topology diagram
    generate_topology(network, established, lsp_results)

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump({
            "lsp_results": lsp_results,
            "link_utilization": link_util,
            "billing_summary": billing_summary,
            "risk_assessment": risk_assessment,
        }, f, indent=2)


if __name__ == "__main__":
    solve()
