#!/usr/bin/env python3
"""
Hydrofabric network analysis, ngen realization config, and MPI partition
config generator.

"""

import json
import math
import os
import sqlite3
from collections import defaultdict

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
GPKG_PATH = os.path.join(DATA_DIR, "hydrofabric.gpkg")


def load_from_gpkg():
    """Read catchment and nexus data from the GeoPackage database."""
    conn = sqlite3.connect(GPKG_PATH)

    # Discover catchment column names
    cat_info = conn.execute("PRAGMA table_info(catchments)").fetchall()
    cat_cols = [row[1] for row in cat_info]

    id_col = next((c for c in cat_cols if c.lower() == "id"), None)
    if id_col is None:
        id_col = next(
            c for c in cat_cols
            if "id" in c.lower() and c.lower() not in ("fid", "toid")
        )
    area_col = next(c for c in cat_cols if "area" in c.lower())
    toid_col = next(c for c in cat_cols if c.lower() == "toid")

    catchments = {}
    for row in conn.execute(
        f"SELECT [{id_col}], [{area_col}], [{toid_col}] FROM catchments"
    ):
        catchments[row[0]] = {"area": row[1], "toid": row[2]}

    # Discover nexus column names
    nex_info = conn.execute("PRAGMA table_info(nexuses)").fetchall()
    nex_cols = [row[1] for row in nex_info]

    nex_id_col = next((c for c in nex_cols if c.lower() == "id"), None)
    if nex_id_col is None:
        nex_id_col = next(
            c for c in nex_cols
            if "id" in c.lower() and c.lower() not in ("fid", "toid")
        )
    nex_toid_col = next(c for c in nex_cols if c.lower() == "toid")

    nexuses = {}
    for row in conn.execute(
        f"SELECT [{nex_id_col}], [{nex_toid_col}] FROM nexuses"
    ):
        nexuses[row[0]] = {"toid": row[1]}

    conn.close()
    return catchments, nexuses


def build_graph(catchments, nexuses):
    """Build adjacency structures for the bipartite drainage network."""
    nex_sources = defaultdict(list)
    for cid, c in catchments.items():
        nex_sources[c["toid"]].append(cid)

    upstream_cats = defaultdict(set)
    for nid, n in nexuses.items():
        ds = n["toid"]
        if ds in catchments:
            for src in nex_sources[nid]:
                upstream_cats[ds].add(src)

    downstream_cat = {}
    for cid, c in catchments.items():
        nex_id = c["toid"]
        if nex_id in nexuses:
            ds = nexuses[nex_id]["toid"]
            if ds in catchments:
                downstream_cat[cid] = ds

    return dict(nex_sources), dict(upstream_cats), downstream_cat


def find_headwaters(catchments, upstream_cats):
    return sorted(
        c for c in catchments
        if c not in upstream_cats or len(upstream_cats[c]) == 0
    )


def find_outlet(nexuses, catchments):
    for nid, n in nexuses.items():
        if n["toid"] not in catchments:
            return nid
    return None


def compute_strahler(catchments, upstream_cats):
    orders = {}

    def _order(cid):
        if cid in orders:
            return orders[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            orders[cid] = 1
            return 1
        up_orders = [_order(u) for u in ups]
        mx = max(up_orders)
        cnt = sum(1 for o in up_orders if o == mx)
        orders[cid] = mx + 1 if cnt >= 2 else mx
        return orders[cid]

    for cid in catchments:
        _order(cid)
    return orders


def compute_shreve(catchments, upstream_cats):
    magnitudes = {}

    def _mag(cid):
        if cid in magnitudes:
            return magnitudes[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            magnitudes[cid] = 1
            return 1
        magnitudes[cid] = sum(_mag(u) for u in ups)
        return magnitudes[cid]

    for cid in catchments:
        _mag(cid)
    return magnitudes


def compute_bifurcation_ratio(orders):
    order_counts = defaultdict(int)
    for o in orders.values():
        order_counts[o] += 1
    sorted_orders = sorted(order_counts.keys())

    if len(sorted_orders) < 2:
        return 1.0

    ratios = []
    for i in range(len(sorted_orders) - 1):
        n_i = order_counts[sorted_orders[i]]
        n_ip1 = order_counts[sorted_orders[i + 1]]
        ratios.append(n_i / n_ip1)

    return sum(ratios) / len(ratios)


def compute_cumulative_areas(catchments, upstream_cats):
    cumulative = {}

    def _cum(cid):
        if cid in cumulative:
            return cumulative[cid]
        area = catchments[cid]["area"]
        for u in upstream_cats.get(cid, set()):
            area += _cum(u)
        cumulative[cid] = area
        return area

    for cid in catchments:
        _cum(cid)
    return cumulative


def compute_contributing_areas(nexuses, nex_sources, cumulative):
    contributing = {}
    for nid in nexuses:
        srcs = nex_sources.get(nid, [])
        contributing[nid] = round(sum(cumulative[s] for s in srcs), 6)
    return contributing


def compute_longest_path(catchments, upstream_cats):
    path_len = {}
    path_trace = {}

    def _longest(cid):
        if cid in path_len:
            return path_len[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            path_len[cid] = 1
            path_trace[cid] = [cid]
            return 1
        best_l, best_u = 0, None
        for u in sorted(ups):
            l = _longest(u)
            if l > best_l:
                best_l = l
                best_u = u
        path_len[cid] = best_l + 1
        path_trace[cid] = path_trace[best_u] + [cid]
        return path_len[cid]

    for cid in catchments:
        _longest(cid)

    max_len = max(path_len.values())
    best_cat = None
    for cid in sorted(catchments.keys()):
        if path_len[cid] == max_len:
            best_cat = cid
            break

    return max_len, path_trace[best_cat]


def generate_realization_config():
    """Generate a valid ngen bmi_multi realization configuration."""
    # Inspect forcing files to determine time range
    forcing_dir = os.path.join(DATA_DIR, "forcing")
    forcing_files = [f for f in os.listdir(forcing_dir) if f.endswith(".csv")]
    start_time = None
    end_time = None
    if forcing_files:
        import csv
        fpath = os.path.join(forcing_dir, sorted(forcing_files)[0])
        with open(fpath) as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
            if rows:
                start_time = rows[0][0]
                end_time = rows[-1][0]

    if start_time is None:
        start_time = "2015-12-01 00:00:00"
        end_time = "2015-12-01 23:00:00"

    config = {
        "global": {
            "formulations": [
                {
                    "name": "bmi_multi",
                    "params": {
                        "model_type_name": "bmi_multi_pet_cfe",
                        "main_output_variable": "Q_OUT",
                        "modules": [
                            {
                                "name": "bmi_c",
                                "params": {
                                    "model_type_name": "PET",
                                    "library_file": "/usr/lib/ngen/libpetbmi.so",
                                    "init_config": "/app/config/pet_bmi_config.txt",
                                    "registration_function": "register_bmi_pet",
                                    "main_output_variable": "water_potential_evaporation_flux",
                                    "uses_forcing_file": False,
                                    "allow_exceed_end_time": True,
                                    "variables_names_map": {
                                        "TMP_2maboveground": "TMP_2maboveground",
                                        "SPFH_2maboveground": "SPFH_2maboveground",
                                        "PRES_surface": "PRES_surface",
                                        "DLWRF_surface": "DLWRF_surface",
                                        "DSWRF_surface": "DSWRF_surface",
                                        "UGRD_10maboveground": "UGRD_10maboveground",
                                        "VGRD_10maboveground": "VGRD_10maboveground",
                                    },
                                },
                            },
                            {
                                "name": "bmi_c",
                                "params": {
                                    "model_type_name": "CFE",
                                    "library_file": "/usr/lib/ngen/libcfebmi.so",
                                    "init_config": "/app/config/cfe_bmi_config.txt",
                                    "registration_function": "register_bmi",
                                    "main_output_variable": "Q_OUT",
                                    "uses_forcing_file": False,
                                    "allow_exceed_end_time": True,
                                    "variables_names_map": {
                                        "atmosphere_water__liquid_equivalent_precipitation_rate": "precip_rate",
                                        "water_potential_evaporation_flux": "water_potential_evaporation_flux",
                                    },
                                },
                            },
                        ],
                    },
                }
            ],
            "forcing": {
                "file_pattern": ".*{{id}}.*.csv",
                "path": "/app/data/forcing/",
            },
        },
        "time": {
            "start_time": start_time,
            "end_time": end_time,
            "output_interval": 3600,
        },
    }
    return config


def generate_partition_config(catchments, nexuses, nex_sources, upstream_cats,
                              downstream_cat, num_partitions=4):
    all_cats = set(catchments.keys())
    max_per_partition = 6

    children = defaultdict(list)
    for cid in all_cats:
        ds = downstream_cat.get(cid)
        if ds:
            children[ds].append(cid)

    roots = [c for c in all_cats if c not in downstream_cat]

    subtree_size = {}

    def _size(cid):
        if cid in subtree_size:
            return subtree_size[cid]
        subtree_size[cid] = 1 + sum(_size(ch) for ch in children.get(cid, []))
        return subtree_size[cid]

    for r in roots:
        _size(r)

    groups = []

    def _collect(node):
        child_results = []
        for ch in sorted(children.get(node, []),
                         key=lambda c: subtree_size.get(c, 0)):
            child_results.append(_collect(ch))

        total = 1 + sum(len(cr) for cr in child_results)
        if total <= max_per_partition:
            merged = [node]
            for cr in child_results:
                merged.extend(cr)
            return merged

        children_total = sum(len(cr) for cr in child_results)
        if children_total <= max_per_partition and children_total > 0:
            merged_children = []
            for cr in child_results:
                merged_children.extend(cr)
            groups.append(merged_children)
            return [node]

        child_results.sort(key=len)
        current = [node]
        for cr in child_results:
            if len(current) + len(cr) <= max_per_partition:
                current.extend(cr)
            else:
                groups.append(cr)
        return current

    for root in roots:
        result = _collect(root)
        groups.append(result)

    while len(groups) > num_partitions:
        groups.sort(key=len)
        groups[0].extend(groups[1])
        groups.pop(1)

    while len(groups) < num_partitions:
        groups.sort(key=len, reverse=True)
        g = groups[0]
        mid = len(g) // 2
        groups[0] = g[:mid]
        groups.insert(1, g[mid:])

    cat_partition = {}
    partitions = [[] for _ in range(num_partitions)]
    for pid, grp in enumerate(groups):
        for cid in grp:
            cat_partition[cid] = pid
            partitions[pid].append(cid)

    nex_partition = {}
    for nid, n in nexuses.items():
        ds = n["toid"]
        if ds in cat_partition:
            nex_partition[nid] = cat_partition[ds]
        else:
            srcs = nex_sources.get(nid, [])
            if srcs:
                nex_partition[nid] = cat_partition[srcs[0]]
            else:
                nex_partition[nid] = 0

    remote = set()
    for nid in nexuses:
        np = nex_partition[nid]
        for src in nex_sources.get(nid, []):
            if cat_partition[src] != np:
                remote.add(nid)
                break

    partition_data = []
    for pid in range(num_partitions):
        p_cats = sorted(partitions[pid])
        p_nexs = sorted(nid for nid, p in nex_partition.items() if p == pid)
        partition_data.append({
            "id": pid,
            "catchment_ids": p_cats,
            "nexus_ids": p_nexs,
        })

    return {
        "num_partitions": num_partitions,
        "partitions": partition_data,
        "remote_nexuses": sorted(remote),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    catchments, nexuses = load_from_gpkg()
    nex_sources, upstream_cats, downstream_cat = build_graph(catchments, nexuses)

    # Network analysis
    headwaters = find_headwaters(catchments, upstream_cats)
    outlet = find_outlet(nexuses, catchments)
    total_area = round(sum(c["area"] for c in catchments.values()), 6)
    orders = compute_strahler(catchments, upstream_cats)
    max_order = max(orders.values())
    magnitudes = compute_shreve(catchments, upstream_cats)
    rb = compute_bifurcation_ratio(orders)
    cumulative = compute_cumulative_areas(catchments, upstream_cats)
    contributing = compute_contributing_areas(nexuses, nex_sources, cumulative)
    longest_len, longest_path = compute_longest_path(catchments, upstream_cats)

    network_analysis = {
        "headwater_catchments": headwaters,
        "outlet_nexus": outlet,
        "total_drainage_area_sqkm": total_area,
        "strahler_orders": orders,
        "max_strahler_order": max_order,
        "shreve_magnitudes": magnitudes,
        "bifurcation_ratio": rb,
        "contributing_areas": contributing,
        "longest_flow_path": {
            "length": longest_len,
            "path": longest_path,
        },
    }

    with open(os.path.join(OUTPUT_DIR, "network_analysis.json"), "w") as f:
        json.dump(network_analysis, f, indent=2)

    # Realization config
    realization_config = generate_realization_config()
    with open(os.path.join(OUTPUT_DIR, "realization_config.json"), "w") as f:
        json.dump(realization_config, f, indent=2)

    # Partition config
    partition_config = generate_partition_config(
        catchments, nexuses, nex_sources, upstream_cats, downstream_cat
    )
    with open(os.path.join(OUTPUT_DIR, "partition_config.json"), "w") as f:
        json.dump(partition_config, f, indent=2)


if __name__ == "__main__":
    main()
