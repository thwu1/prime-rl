#!/usr/bin/env python3
"""
E3SM Configuration Intelligence System - Solution

Parses three E3SM configuration sources, builds a SQLite database,
and produces analytical query results.
"""

import json
import sqlite3
import xml.etree.ElementTree as ET


# ── Parsers ──────────────────────────────────────────────────────────


def parse_compsets(path):
    """Parse config_compsets.xml -> {alias: longname}."""
    tree = ET.parse(path)
    root = tree.getroot()
    compsets = {}
    for el in root.findall(".//compset"):
        alias_el = el.find("alias")
        lname_el = el.find("lname")
        if alias_el is not None and lname_el is not None:
            compsets[alias_el.text.strip()] = lname_el.text.strip()
    return compsets


def parse_atm_processes(path):
    """Parse atmosphere process defs from eamxx_namelist_defaults.xml."""
    tree = ET.parse(path)
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    procs = {}
    if apd is None:
        return procs
    for child in apd:
        name = child.tag
        parent = child.get("inherit")
        is_group = parent == "atm_proc_group"
        type_el = child.find("type")
        if type_el is not None and type_el.text and type_el.text.strip() == "group":
            is_group = True
        procs[name] = {"parent": parent, "is_group": is_group}
    return procs


def find_constrained_params(path):
    """Find all parameter names with constraints attribute."""
    tree = ET.parse(path)
    root = tree.getroot()
    params = set()
    for el in root.iter():
        if el.get("constraints"):
            params.add(el.tag)
    return sorted(params)


def parse_suites(path):
    """Parse test_suites.py via exec."""
    with open(path) as f:
        content = f.read()
    ns = {}
    exec(content, ns)
    return ns["_TESTS"]


def resolve_tests(name, suites, cache=None):
    """Recursively resolve all unique tests for a suite."""
    if cache is None:
        cache = {}
    if name in cache:
        return cache[name]
    suite = suites[name]
    tests = set()
    raw = suite.get("tests", ())
    if isinstance(raw, str):
        tests.add(raw)
    else:
        for t in raw:
            tests.add(t)
    inherit = suite.get("inherit")
    if inherit is not None:
        if isinstance(inherit, str):
            parents = [inherit]
        else:
            parents = list(inherit)
        for p in parents:
            tests |= resolve_tests(p, suites, cache)
    cache[name] = tests
    return tests


def compute_depth(name, suites, cache=None):
    """Compute inheritance depth (0 = no parents)."""
    if cache is None:
        cache = {}
    if name in cache:
        return cache[name]
    suite = suites[name]
    inherit = suite.get("inherit")
    if inherit is None:
        cache[name] = 0
        return 0
    if isinstance(inherit, str):
        parents = [inherit]
    else:
        parents = list(inherit)
    if not parents:
        cache[name] = 0
        return 0
    d = 1 + max(compute_depth(p, suites, cache) for p in parents)
    cache[name] = d
    return d


def parse_longname(longname):
    """Parse a compset longname into component slots."""
    slots = ["atm", "lnd", "ice", "ocn", "rof", "glc", "wav"]
    parts = longname.split("_")
    result = {"time": parts[0]}
    for i, slot in enumerate(slots):
        if i + 1 < len(parts):
            part = parts[i + 1]
            if "%" in part:
                model, physics = part.split("%", 1)
            else:
                model, physics = part, None
            result[slot] = {"model": model, "physics": physics}
    if len(parts) > 8:
        bgc_part = parts[8]
        if bgc_part.startswith("BGC%"):
            model, physics = bgc_part.split("%", 1)
            result["bgc"] = {"model": model, "physics": physics}
    return result


# ── Main ─────────────────────────────────────────────────────────────


def main():
    compsets = parse_compsets("/app/config_compsets.xml")
    procs = parse_atm_processes("/app/eamxx_namelist_defaults.xml")
    suites = parse_suites("/app/test_suites.py")

    # ── Build SQLite database ────────────────────────────────────────

    conn = sqlite3.connect("/app/e3sm_config.db")
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS compsets(alias TEXT PRIMARY KEY, longname TEXT)"
    )
    for alias, lname in compsets.items():
        cur.execute(
            "INSERT OR REPLACE INTO compsets VALUES (?, ?)", (alias, lname)
        )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS atm_processes("
        "name TEXT PRIMARY KEY, parent TEXT, is_group INTEGER)"
    )
    for name, info in procs.items():
        cur.execute(
            "INSERT OR REPLACE INTO atm_processes VALUES (?, ?, ?)",
            (name, info["parent"], 1 if info["is_group"] else 0),
        )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS test_suites("
        "name TEXT PRIMARY KEY, direct_test_count INTEGER, inherits_from TEXT)"
    )
    for name, suite in suites.items():
        raw = suite.get("tests", ())
        if isinstance(raw, str):
            count = 1
        else:
            count = len(raw)
        inherit = suite.get("inherit")
        if inherit is None:
            inherits_str = ""
        elif isinstance(inherit, str):
            inherits_str = inherit
        else:
            inherits_str = ",".join(inherit)
        cur.execute(
            "INSERT OR REPLACE INTO test_suites VALUES (?, ?, ?)",
            (name, count, inherits_str),
        )

    conn.commit()
    conn.close()

    # ── Compute query results ────────────────────────────────────────

    results = {}

    # total_compsets
    results["total_compsets"] = len(compsets)

    # atm_process_hierarchy
    results["atm_process_hierarchy"] = {
        name: info["parent"] for name, info in procs.items()
    }

    # num_atm_processes
    results["num_atm_processes"] = len(procs)

    # constrained_params
    results["constrained_params"] = find_constrained_params(
        "/app/eamxx_namelist_defaults.xml"
    )

    # suite_resolved_counts
    test_cache = {}
    results["suite_resolved_counts"] = {
        "e3sm_developer": len(resolve_tests("e3sm_developer", suites, test_cache)),
        "e3sm_integration": len(resolve_tests("e3sm_integration", suites, test_cache)),
        "fates": len(resolve_tests("fates", suites, test_cache)),
    }

    # max_inheritance_depth
    depth_cache = {}
    max_name, max_depth = None, -1
    for name in suites:
        d = compute_depth(name, suites, depth_cache)
        if d > max_depth:
            max_depth = d
            max_name = name
    results["max_inheritance_depth"] = {"suite": max_name, "depth": max_depth}

    # compsets_by_bgc_mode
    bgc_modes = {}
    for alias, lname in compsets.items():
        parts = lname.split("_")
        for p in parts:
            if p.startswith("BGC%"):
                mode = p.split("%", 1)[1]
                bgc_modes.setdefault(mode, []).append(alias)
    results["compsets_by_bgc_mode"] = {m: sorted(v) for m, v in bgc_modes.items()}

    # compset_component_breakdown
    breakdown = {}
    for alias in ["CRYO1850-DISMF", "MPAS_LISIO_JRA1p5", "WCYCLXX2010"]:
        lname = compsets[alias]
        parsed = parse_longname(lname)
        parsed["longname"] = lname
        breakdown[alias] = parsed
    results["compset_component_breakdown"] = breakdown

    # eamxx_default_pipeline
    tree = ET.parse("/app/eamxx_namelist_defaults.xml")
    root = tree.getroot()
    apd = root.find("atmosphere_processes_defaults")
    eamxx = apd.find("eamxx")
    selector_attrs = {"hgrid", "nlev", "COMPSET", "dyn", "ntracers"}
    for el in eamxx:
        if el.tag == "atm_procs_list" and el.text:
            if not any(k in selector_attrs for k in el.attrib):
                results["eamxx_default_pipeline"] = el.text.strip()
                break

    # physics_pipeline_variants
    physics = apd.find("physics")
    variants = {}
    for el in physics:
        if el.tag == "atm_procs_list" and el.text:
            compset = el.get("COMPSET")
            if compset:
                variants[compset] = el.text.strip()
            elif not any(k in selector_attrs for k in el.attrib):
                variants["default"] = el.text.strip()
    results["physics_pipeline_variants"] = variants

    # grid_rad_frequencies
    rrtmgp = apd.find("rrtmgp")
    rad_freqs = {}
    for el in rrtmgp:
        if el.tag == "rad_frequency" and el.text:
            hgrid = el.get("hgrid")
            compset = el.get("COMPSET")
            if hgrid:
                rad_freqs[hgrid] = el.text.strip()
            elif compset:
                rad_freqs[f"COMPSET:{compset}"] = el.text.strip()
    results["grid_rad_frequencies"] = rad_freqs

    # cryo_compsets
    results["cryo_compsets"] = sorted(
        alias for alias, lname in compsets.items() if "MPASSI%DIB" in lname
    )

    # ── Write output ─────────────────────────────────────────────────

    with open("/app/query_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Done!")
    print(f"  total_compsets: {results['total_compsets']}")
    print(f"  num_atm_processes: {results['num_atm_processes']}")
    print(f"  constrained_params: {results['constrained_params']}")
    print(f"  suite_resolved_counts: {results['suite_resolved_counts']}")
    print(f"  max_inheritance_depth: {results['max_inheritance_depth']}")
    print(f"  cryo_compsets: {len(results['cryo_compsets'])} entries")


if __name__ == "__main__":
    main()
