#!/usr/bin/env python3
"""NOAA-OWP NextGen Hydrofabric Network Analysis Tool.

Operates on a GeoPackage-compatible SQLite database (SQL dump).
Six subcommands: validate, drainage, subset, realize, route-config, graph.
"""


import json
import sys
import argparse
import copy
import sqlite3
from collections import defaultdict, deque

try:
    import yaml
except ImportError:
    yaml = None


def load_from_sql(sql_path):
    """Import SQL dump into in-memory SQLite and return connection + network dict."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(sql_path) as f:
        conn.executescript(f.read())

    flowpaths = [dict(r) for r in conn.execute("SELECT * FROM flowpaths")]
    divides = [dict(r) for r in conn.execute("SELECT * FROM divides")]
    nexuses = [dict(r) for r in conn.execute("SELECT * FROM nexus")]

    for d in divides:
        if "has_flowline" in d:
            d["has_flowline"] = bool(d["has_flowline"])

    network = {"flowpaths": flowpaths, "divides": divides, "nexuses": nexuses}
    return conn, network


def build_indices(network):
    """Build lookup indices for rapid network traversal."""
    fl_by_id = {fl["id"]: fl for fl in network["flowpaths"]}
    div_by_id = {d["divide_id"]: d for d in network["divides"]}
    nex_by_id = {n["id"]: n for n in network["nexuses"]}

    fl_by_toid = defaultdict(list)
    for fl in network["flowpaths"]:
        if fl.get("toid"):
            fl_by_toid[fl["toid"]].append(fl)

    nex_by_cat = defaultdict(list)
    for n in network["nexuses"]:
        if n.get("toid"):
            nex_by_cat[n["toid"]].append(n)

    return fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat


# ---------------------------------------------------------------------------
# VALIDATE
# ---------------------------------------------------------------------------

def cmd_validate(network):
    fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat = build_indices(network)
    violations = []

    # 1. Dangling references: flowpath.toid -> non-existent nexus
    for fl in network["flowpaths"]:
        toid = fl.get("toid", "")
        if toid and toid not in nex_by_id:
            violations.append({
                "type": "dangling_reference",
                "feature_id": fl["id"],
                "message": (f"Flowpath {fl['id']} references nexus {toid} "
                            f"which does not exist in the nexus table")
            })

    # 2. Orphan nexuses: no upstream flowpaths AND downstream target absent
    for nex in network["nexuses"]:
        upstream = fl_by_toid.get(nex["id"], [])
        if len(upstream) == 0:
            toid = nex.get("toid", "")
            if toid and toid not in div_by_id:
                violations.append({
                    "type": "orphan_nexus",
                    "feature_id": nex["id"],
                    "message": (f"Nexus {nex['id']} has no upstream flowpaths "
                                f"and its downstream target {toid} does not "
                                f"exist as a divide")
                })

    # 3. Missing divide cross-reference
    for fl in network["flowpaths"]:
        did = fl.get("divide_id", "")
        if did and did not in div_by_id:
            violations.append({
                "type": "missing_divide",
                "feature_id": fl["id"],
                "message": (f"Flowpath {fl['id']} references divide {did} "
                            f"which does not exist in the divides table")
            })

    # 4. Cycle detection via DFS on the bipartite cat-nex routing graph
    graph = defaultdict(list)
    for fl in network["flowpaths"]:
        cat = fl.get("divide_id", "")
        nex = fl.get("toid", "")
        if cat and nex:
            graph[cat].append(nex)
    for n in network["nexuses"]:
        nex_id = n["id"]
        toid = n.get("toid", "")
        if toid:
            graph[nex_id].append(toid)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    cycles_found = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                idx = path.index(neighbor)
                cycle = path[idx:]
                cycles_found.append(list(cycle))
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    all_nodes = set(graph.keys())
    for targets in graph.values():
        all_nodes.update(targets)

    for node in sorted(all_nodes):
        if color[node] == WHITE:
            dfs(node, [])

    for cycle in cycles_found:
        violations.append({
            "type": "cycle",
            "feature_ids": cycle,
            "message": (f"Cycle detected: {' -> '.join(cycle)} -> {cycle[0]}")
        })

    return {
        "is_valid": len(violations) == 0,
        "violations": violations
    }


# ---------------------------------------------------------------------------
# DRAINAGE
# ---------------------------------------------------------------------------

def cmd_drainage(network):
    fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat = build_indices(network)

    # Identify error features to exclude
    validation = cmd_validate(network)
    error_fl_ids = set()
    cycle_nodes = set()

    for v in validation["violations"]:
        if v["type"] == "cycle":
            cycle_nodes.update(v.get("feature_ids", []))
        elif v["type"] in ("dangling_reference", "missing_divide"):
            error_fl_ids.add(v["feature_id"])

    for fl in network["flowpaths"]:
        did = fl.get("divide_id", "")
        toid = fl.get("toid", "")
        if did in cycle_nodes or toid in cycle_nodes:
            error_fl_ids.add(fl["id"])
        if did and did not in div_by_id:
            error_fl_ids.add(fl["id"])
        if toid and toid not in nex_by_id:
            error_fl_ids.add(fl["id"])

    drainage = {}

    def compute(fl_id, visiting=None):
        if fl_id in drainage:
            return drainage[fl_id]
        if visiting is None:
            visiting = set()
        if fl_id in visiting:
            return 0.0
        visiting = visiting | {fl_id}

        fl = fl_by_id.get(fl_id)
        if not fl:
            return 0.0
        div = div_by_id.get(fl.get("divide_id", ""))
        if not div:
            return 0.0

        own_area = div["areasqkm"]
        upstream_total = 0.0

        cat_id = fl["divide_id"]
        for nex in nex_by_cat.get(cat_id, []):
            for ufl in fl_by_toid.get(nex["id"], []):
                if ufl["id"] not in error_fl_ids:
                    upstream_total += compute(ufl["id"], visiting)

        drainage[fl_id] = round(own_area + upstream_total, 2)
        return drainage[fl_id]

    valid_fls = [fl for fl in network["flowpaths"]
                 if fl["id"] not in error_fl_ids]
    for fl in valid_fls:
        compute(fl["id"])

    return drainage


# ---------------------------------------------------------------------------
# SUBSET
# ---------------------------------------------------------------------------

def cmd_subset(network, nexus_id):
    fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat = build_indices(network)

    if nexus_id not in nex_by_id:
        print(json.dumps({"error": f"Nexus {nexus_id} not found"}),
              file=sys.stderr)
        sys.exit(1)

    subset_fl = set()
    subset_div = set()
    subset_nex = {nexus_id}

    queue = deque([nexus_id])

    while queue:
        nid = queue.popleft()
        for fl in fl_by_toid.get(nid, []):
            if fl["id"] not in subset_fl:
                subset_fl.add(fl["id"])
                cat_id = fl.get("divide_id", "")
                if cat_id:
                    subset_div.add(cat_id)
                    for unex in nex_by_cat.get(cat_id, []):
                        if unex["id"] not in subset_nex:
                            subset_nex.add(unex["id"])
                            queue.append(unex["id"])

    return {
        "flowpaths": [fl for fl in network["flowpaths"]
                       if fl["id"] in subset_fl],
        "divides": [d for d in network["divides"]
                     if d["divide_id"] in subset_div],
        "nexuses": [n for n in network["nexuses"]
                     if n["id"] in subset_nex]
    }


# ---------------------------------------------------------------------------
# REALIZE
# ---------------------------------------------------------------------------

def cmd_realize(network, nexus_id, model_config_path):
    with open(model_config_path) as f:
        model_config = json.load(f)

    subset = cmd_subset(network, nexus_id)

    form_template = model_config["formulation"]

    # Build global formulation (keeps {{id}} placeholders)
    global_form = {
        "name": form_template["name"],
        "params": {
            "model_type_name": form_template["model_type_name"],
            "forcing_file": "",
            "init_config": "",
            "allow_exceed_end_time": True,
            "main_output_variable": form_template["main_output_variable"],
            "modules": copy.deepcopy(form_template["modules"]),
            "uses_forcing_file": False
        }
    }

    # Build per-catchment formulations with {{id}} substituted
    catchments = {}
    for div in subset["divides"]:
        cat_id = div["divide_id"]
        cat_form = copy.deepcopy(global_form)

        for module in cat_form["params"]["modules"]:
            params = module["params"]
            if "init_config" in params:
                params["init_config"] = params["init_config"].replace(
                    "{{id}}", cat_id)

        cat_forcing = copy.deepcopy(model_config["forcing"])
        if "file_pattern" in cat_forcing:
            cat_forcing["file_pattern"] = cat_forcing["file_pattern"].replace(
                "{{id}}", cat_id)

        catchments[cat_id] = {
            "formulations": [cat_form],
            "forcing": cat_forcing
        }

    realization = {
        "global": {
            "formulations": [global_form],
            "forcing": copy.deepcopy(model_config["forcing"])
        },
        "time": copy.deepcopy(model_config["time"]),
        "catchments": catchments
    }

    return realization


# ---------------------------------------------------------------------------
# ROUTE CONFIG
# ---------------------------------------------------------------------------

def cmd_route_config(network, nexus_id, conn):
    """Generate t-route YAML routing configuration for the upstream subset."""
    if yaml is None:
        print("Error: PyYAML is required for route-config", file=sys.stderr)
        sys.exit(1)

    fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat = build_indices(network)

    if nexus_id not in nex_by_id:
        print(json.dumps({"error": f"Nexus {nexus_id} not found"}),
              file=sys.stderr)
        sys.exit(1)

    # Get upstream subset
    subset = cmd_subset(network, nexus_id)
    subset_fl_ids = {fl["id"] for fl in subset["flowpaths"]}

    # Load flowpath attributes from SQLite
    attrs = {}
    for row in conn.execute("SELECT * FROM flowpath_attributes"):
        row_dict = dict(row)
        attrs[row_dict["id"]] = row_dict

    # Build divide_id -> flowpath_id mapping for downstream resolution
    div_to_fl = {}
    for fl in network["flowpaths"]:
        did = fl.get("divide_id")
        if did:
            div_to_fl[did] = fl["id"]

    segments = []
    for fl in subset["flowpaths"]:
        fl_id = fl["id"]
        fl_toid = fl["toid"]

        # Resolve downstream: flowpath -> nexus -> catchment -> downstream flowpath
        downstream = ""
        if fl_toid != nexus_id:
            nex = nex_by_id.get(fl_toid)
            if nex and nex.get("toid"):
                ds_cat = nex["toid"]
                ds_fl = div_to_fl.get(ds_cat)
                if ds_fl and ds_fl in subset_fl_ids:
                    downstream = ds_fl

        fa = attrs.get(fl_id, {})
        segment = {
            "id": fl_id,
            "downstream": downstream,
            "length_m": fa.get("length_m", 0.0),
            "n": fa.get("n", 0.0),
            "So": fa.get("So", 0.0),
            "BtmWdth": fa.get("BtmWdth", 0.0),
            "TopWdth": fa.get("TopWdth", 0.0),
            "TopWdthCC": fa.get("TopWdthCC", 0.0),
            "nCC": fa.get("nCC", 0.0),
            "MusK": fa.get("MusK", 0.0),
            "MusX": fa.get("MusX", 0.0),
            "ChSlp": fa.get("ChSlp", 0.0),
            "Qi": fa.get("Qi", 0.0),
            "Kchan": fa.get("Kchan", 0.0),
            "hydroseq": fl.get("hydroseq", 0)
        }
        segments.append(segment)

    # Sort by hydroseq descending (upstream-first processing order)
    segments.sort(key=lambda s: s["hydroseq"], reverse=True)

    config = {
        "supernetwork_parameters": {
            "title": f"Upstream network of {nexus_id}",
            "geo_file_type": "HYFeaturesNetwork",
            "terminal_nexus": nexus_id,
            "columns": {
                "key": "id",
                "downstream": "toid",
                "dx": "length_m",
                "n": "n",
                "s0": "So",
                "bw": "BtmWdth",
                "tw": "TopWdth",
                "musk": "MusK",
                "musx": "MusX"
            }
        },
        "segments": segments,
        "compute_parameters": {
            "parallel_compute_method": "serial",
            "compute_kernel": "V02-structured",
            "assume_short_ts": True,
            "subnetwork_target_size": 10000
        },
        "output_parameters": {
            "stream_output_directory": "/app/output/",
            "stream_output_time": 1,
            "stream_output_type": ".nc"
        }
    }

    return config


# ---------------------------------------------------------------------------
# GRAPH
# ---------------------------------------------------------------------------

def cmd_graph(network, nexus_id):
    """Generate Graphviz DOT digraph of the upstream subset routing network."""
    fl_by_id, div_by_id, nex_by_id, fl_by_toid, nex_by_cat = build_indices(network)

    if nexus_id not in nex_by_id:
        print(json.dumps({"error": f"Nexus {nexus_id} not found"}),
              file=sys.stderr)
        sys.exit(1)

    subset = cmd_subset(network, nexus_id)
    subset_fl_ids = {fl["id"] for fl in subset["flowpaths"]}
    subset_nex_ids = {n["id"] for n in subset["nexuses"]}

    # Build divide_id -> flowpath_id mapping
    div_to_fl = {}
    for fl in network["flowpaths"]:
        did = fl.get("divide_id")
        if did:
            div_to_fl[did] = fl["id"]

    lines = ["digraph hydrofabric {"]
    lines.append("  rankdir=TB;")

    # Flowpath nodes (shape=box)
    for fl in sorted(subset["flowpaths"], key=lambda x: x["id"]):
        lines.append(f'  "{fl["id"]}" [shape=box];')

    # Nexus nodes (shape=diamond, terminal gets style=bold)
    for nex in sorted(subset["nexuses"], key=lambda x: x["id"]):
        if nex["id"] == nexus_id:
            lines.append(f'  "{nex["id"]}" [shape=diamond,style=bold];')
        else:
            lines.append(f'  "{nex["id"]}" [shape=diamond];')

    # Edges: flowpath -> its downstream nexus
    for fl in sorted(subset["flowpaths"], key=lambda x: x["id"]):
        if fl["toid"] in subset_nex_ids:
            lines.append(f'  "{fl["id"]}" -> "{fl["toid"]}";')

    # Edges: nexus -> downstream flowpath (via nexus.toid -> catchment -> flowpath)
    for nex in sorted(subset["nexuses"], key=lambda x: x["id"]):
        toid = nex.get("toid", "")
        if toid:
            ds_fl = div_to_fl.get(toid)
            if ds_fl and ds_fl in subset_fl_ids:
                lines.append(f'  "{nex["id"]}" -> "{ds_fl}";')

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NOAA-OWP NextGen Hydrofabric Network Analysis Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_val = subparsers.add_parser("validate",
                                   help="Detect topology violations")
    p_val.add_argument("sql_file")

    p_drain = subparsers.add_parser("drainage",
                                     help="Compute total drainage areas")
    p_drain.add_argument("sql_file")

    p_sub = subparsers.add_parser("subset",
                                   help="Extract upstream sub-network")
    p_sub.add_argument("sql_file")
    p_sub.add_argument("nexus_id")

    p_real = subparsers.add_parser("realize",
                                    help="Generate ngen realization config")
    p_real.add_argument("sql_file")
    p_real.add_argument("nexus_id")
    p_real.add_argument("--model-config", required=True)

    p_route = subparsers.add_parser("route-config",
                                     help="Generate t-route YAML config")
    p_route.add_argument("sql_file")
    p_route.add_argument("nexus_id")

    p_graph = subparsers.add_parser("graph",
                                     help="Generate DOT network graph")
    p_graph.add_argument("sql_file")
    p_graph.add_argument("nexus_id")
    p_graph.add_argument("--format", required=True, choices=["dot"])

    args = parser.parse_args()
    conn, network = load_from_sql(args.sql_file)

    if args.command == "validate":
        result = cmd_validate(network)
        print(json.dumps(result, indent=2))
    elif args.command == "drainage":
        result = cmd_drainage(network)
        print(json.dumps(result, indent=2))
    elif args.command == "subset":
        result = cmd_subset(network, args.nexus_id)
        print(json.dumps(result, indent=2))
    elif args.command == "realize":
        result = cmd_realize(network, args.nexus_id, args.model_config)
        print(json.dumps(result, indent=2))
    elif args.command == "route-config":
        result = cmd_route_config(network, args.nexus_id, conn)
        print(yaml.dump(result, default_flow_style=False, sort_keys=False))
    elif args.command == "graph":
        result = cmd_graph(network, args.nexus_id)
        print(result)
    else:
        parser.print_help()
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
