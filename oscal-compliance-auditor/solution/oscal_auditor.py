#!/usr/bin/env python3
"""OSCAL Profile Resolution and SSP Compliance Gap Analyzer.

Resolves an OSCAL profile against its source catalog, then audits a System
Security Plan for compliance gaps across six dimensions.
"""

import json
import fnmatch


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect_all_control_ids(catalog):
    """Extract every control ID from the catalog, including nested enhancements."""
    ids = []
    for group in catalog["catalog"]["groups"]:
        for ctrl in group.get("controls", []):
            ids.append(ctrl["id"])
            for enh in ctrl.get("controls", []):
                ids.append(enh["id"])
    return ids


def build_control_map(catalog):
    """Map control ID -> control object for fast lookup."""
    cmap = {}
    for group in catalog["catalog"]["groups"]:
        for ctrl in group.get("controls", []):
            cmap[ctrl["id"]] = ctrl
            for enh in ctrl.get("controls", []):
                cmap[enh["id"]] = enh
    return cmap


def resolve_profile(catalog, profile):
    """Resolve profile imports against catalog to produce the effective control set.

    Steps:
    1. For each import, collect controls matching any include-controls entry
       (union of with-ids and glob-style matching patterns).
    2. Remove controls matching any exclude-controls entry.
    3. Return the sorted list of resolved control IDs.
    """
    all_ids = collect_all_control_ids(catalog)
    included = set()

    for imp in profile["profile"]["imports"]:
        # Union of all include-controls entries
        for sel in imp.get("include-controls", []):
            for cid in sel.get("with-ids", []):
                if cid in set(all_ids):
                    included.add(cid)
            for match_obj in sel.get("matching", []):
                pattern = match_obj["pattern"]
                for cid in all_ids:
                    if fnmatch.fnmatch(cid, pattern):
                        included.add(cid)

        # Remove exclude-controls
        for exc in imp.get("exclude-controls", []):
            for cid in exc.get("with-ids", []):
                included.discard(cid)

    return sorted(included)


def get_profile_param_ids(profile):
    """Return a dict mapping param-id -> control-id for all profile set-parameters."""
    modify = profile["profile"].get("modify", {})
    return {sp["param-id"]: sp.get("values", [])
            for sp in modify.get("set-parameters", [])}


def get_component_uuids(ssp):
    """Collect all component UUIDs from the SSP's system-implementation."""
    return {comp["uuid"]
            for comp in ssp["system-security-plan"]["system-implementation"]["components"]}


def get_top_level_statement_ids(control):
    """Return the IDs of a control's top-level statement parts.

    Top-level means the direct children of the 'statement' part,
    NOT their nested sub-parts.
    """
    ids = []
    for part in control.get("parts", []):
        if part["name"] == "statement":
            for child in part.get("parts", []):
                ids.append(child["id"])
    return ids


def map_params_to_controls(control_map):
    """Build a mapping from param-id -> control-id using catalog data."""
    p2c = {}
    for cid, ctrl in control_map.items():
        for param in ctrl.get("params", []):
            p2c[param["id"]] = cid
    return p2c


def analyze(catalog, profile, ssp, resolved_ids):
    """Run the full compliance gap analysis."""
    control_map = build_control_map(catalog)
    comp_uuids = get_component_uuids(ssp)
    profile_params = get_profile_param_ids(profile)
    param_to_ctrl = map_params_to_controls(control_map)

    resolved_set = set(resolved_ids)

    # Index SSP implemented-requirements by control-id
    impl_reqs = ssp["system-security-plan"]["control-implementation"]["implemented-requirements"]
    implemented_set = set()
    impl_map = {}
    for req in impl_reqs:
        cid = req["control-id"]
        implemented_set.add(cid)
        impl_map[cid] = req

    # 1. Missing implementations
    missing = sorted(resolved_set - implemented_set)

    # 2. Orphaned implementations
    orphaned = sorted(implemented_set - resolved_set)

    # 3. Broken component references
    broken_refs = []
    for req in impl_reqs:
        for stmt in req.get("statements", []):
            for bc in stmt.get("by-components", []):
                if bc["component-uuid"] not in comp_uuids:
                    broken_refs.append({
                        "control_id": req["control-id"],
                        "statement_id": stmt["statement-id"],
                        "component_uuid": bc["component-uuid"]
                    })
    broken_refs.sort(key=lambda x: (x["control_id"], x["statement_id"]))

    # 4. Parameter gaps
    param_gaps = []
    for param_id in profile_params:
        ctrl_id = param_to_ctrl.get(param_id)
        if ctrl_id and ctrl_id in resolved_set and ctrl_id in implemented_set:
            req = impl_map[ctrl_id]
            ssp_param_ids = {sp["param-id"] for sp in req.get("set-parameters", [])}
            if param_id not in ssp_param_ids:
                param_gaps.append({"control_id": ctrl_id, "param_id": param_id})
    param_gaps.sort(key=lambda x: (x["control_id"], x["param_id"]))

    # 5. Statement coverage gaps
    stmt_gaps = []
    for cid in sorted(resolved_set & implemented_set):
        ctrl = control_map.get(cid)
        if not ctrl:
            continue
        expected = set(get_top_level_statement_ids(ctrl))
        if not expected:
            continue
        actual = {stmt["statement-id"] for stmt in impl_map[cid].get("statements", [])}
        missing_stmts = sorted(expected - actual)
        if missing_stmts:
            stmt_gaps.append({
                "control_id": cid,
                "missing_statements": missing_stmts
            })
    stmt_gaps.sort(key=lambda x: x["control_id"])

    return {
        "resolved_control_ids": resolved_ids,
        "missing_implementations": missing,
        "orphaned_implementations": orphaned,
        "broken_component_refs": broken_refs,
        "parameter_gaps": param_gaps,
        "statement_coverage_gaps": stmt_gaps
    }


def main():
    catalog = load_json("/app/catalog.json")
    profile = load_json("/app/profile.json")
    ssp = load_json("/app/ssp.json")

    resolved_ids = resolve_profile(catalog, profile)
    report = analyze(catalog, profile, ssp, resolved_ids)

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
