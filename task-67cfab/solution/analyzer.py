#!/usr/bin/env python3
"""
E3SM Configuration and Test Suite Analyzer.

Parses config_compsets.xml and test_suites.py, answers 7 queries,
and writes results to /app/results.json.
"""

import json
import xml.etree.ElementTree as ET


# ── Component classification rules ───────────────────────────────────

ACTIVE = {
    "atm": {"EAM", "EAMXX", "SCREAM"},
    "lnd": {"ELM", "ELM45"},
    "ice": {"MPASSI", "CICE"},
    "ocn": {"MPASO"},
    "rof": {"MOSART"},
    "glc": {"MALI"},
    "wav": {"WW3"},
}
STUB = {
    "atm": {"SATM"},
    "lnd": {"SLND"},
    "ice": {"SICE"},
    "ocn": {"SOCN"},
    "rof": {"SROF"},
    "glc": {"SGLC"},
    "wav": {"SWAV"},
}
DATA = {
    "atm": {"DATM"},
    "lnd": set(),
    "ice": {"DICE"},
    "ocn": {"DOCN"},
    "rof": {"DROF"},
    "glc": set(),
    "wav": {"DWAV", "XWAV"},
}

SLOTS = ["atm", "lnd", "ice", "ocn", "rof", "glc", "wav"]


def classify(part, slot):
    if "%" in part:
        model, physics = part.split("%", 1)
    else:
        model, physics = part, None
    if model in ACTIVE.get(slot, set()):
        status = "active"
    elif model in STUB.get(slot, set()):
        status = "stub"
    elif model in DATA.get(slot, set()):
        status = "data"
    else:
        status = "active"
    return {"model": model, "physics": physics, "status": status}


def parse_longname(longname):
    parts = longname.split("_")
    result = {"time_period": parts[0]}
    for i, slot in enumerate(SLOTS):
        if i + 1 < len(parts):
            result[slot] = classify(parts[i + 1], slot)
    # Optional BGC slot at position 8
    if len(parts) > 8:
        bgc_part = parts[8]
        if bgc_part.startswith("BGC%"):
            result["bgc"] = classify(bgc_part, "bgc")
    return result


# ── Parsers ──────────────────────────────────────────────────────────

def parse_compsets(path):
    tree = ET.parse(path)
    root = tree.getroot()
    compsets = {}
    for el in root.findall(".//compset"):
        alias_el = el.find("alias")
        lname_el = el.find("lname")
        if alias_el is not None and lname_el is not None:
            compsets[alias_el.text.strip()] = lname_el.text.strip()
    return compsets


def parse_suites(path):
    with open(path) as f:
        content = f.read()
    ns = {}
    exec(content, ns)
    return ns["_TESTS"]


# ── Suite resolution ─────────────────────────────────────────────────

def resolve_tests(suite_name, suites, cache=None):
    if cache is None:
        cache = {}
    if suite_name in cache:
        return cache[suite_name]

    suite = suites[suite_name]
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

    cache[suite_name] = tests
    return tests


def compute_depth(suite_name, suites, cache=None):
    if cache is None:
        cache = {}
    if suite_name in cache:
        return cache[suite_name]

    suite = suites[suite_name]
    inherit = suite.get("inherit")
    if inherit is None:
        cache[suite_name] = 0
        return 0
    if isinstance(inherit, str):
        parents = [inherit]
    else:
        parents = list(inherit)
    if not parents:
        cache[suite_name] = 0
        return 0

    d = 1 + max(compute_depth(p, suites, cache) for p in parents)
    cache[suite_name] = d
    return d


# ── Main ─────────────────────────────────────────────────────────────

def main():
    compsets = parse_compsets("/app/config_compsets.xml")
    suites = parse_suites("/app/test_suites.py")

    # Q1: total_compsets
    total_compsets = len(compsets)

    # Q2: total_suites
    total_suites = len(suites)

    # Q3: compset_components
    target_aliases = ["CRYO1850-DISMF", "BGCEXP_LNDATM_CNPRDCTC_1850", "MPAS_LISIO_JRA1p5"]
    compset_components = {}
    for alias in target_aliases:
        lname = compsets[alias]
        parsed = parse_longname(lname)
        parsed["longname"] = lname
        compset_components[alias] = parsed

    # Q4: suite_test_counts
    test_cache = {}
    suite_test_counts = {}
    for sname in ["e3sm_developer", "e3sm_integration", "fates"]:
        suite_test_counts[sname] = len(resolve_tests(sname, suites, test_cache))

    # Q5: max_inheritance_depth
    depth_cache = {}
    max_name, max_depth = None, -1
    for name in suites:
        d = compute_depth(name, suites, depth_cache)
        if d > max_depth:
            max_depth = d
            max_name = name

    # Q6: cryo_compsets
    cryo = sorted(a for a, l in compsets.items() if "MPASSI%DIB" in l)

    # Q7: bgc_modes
    bgc_modes = {}
    for alias, lname in compsets.items():
        parts = lname.split("_")
        for p in parts:
            if p.startswith("BGC%"):
                mode = p.split("%", 1)[1]
                bgc_modes.setdefault(mode, []).append(alias)
    bgc_modes = {m: sorted(v) for m, v in bgc_modes.items()}

    results = {
        "total_compsets": total_compsets,
        "total_suites": total_suites,
        "compset_components": compset_components,
        "suite_test_counts": suite_test_counts,
        "max_inheritance_depth": {"suite": max_name, "depth": max_depth},
        "cryo_compsets": cryo,
        "bgc_modes": bgc_modes,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("results.json written successfully")
    print(f"  total_compsets: {total_compsets}")
    print(f"  total_suites: {total_suites}")
    print(f"  suite_test_counts: {suite_test_counts}")
    print(f"  max_inheritance_depth: {max_name} (depth {max_depth})")
    print(f"  cryo_compsets: {len(cryo)} entries")
    print(f"  bgc_modes: {list(bgc_modes.keys())}")


if __name__ == "__main__":
    main()
