#!/usr/bin/env python3
"""OSCAL Cross-Layer Compliance Reconciler.

Processes OSCAL documents across the full compliance lifecycle:
catalog (XML) -> profile (chained) -> SSP -> assessment results -> POA&M
and produces a structured reconciliation report with ten analysis sections.
"""

import json
import fnmatch
import xml.etree.ElementTree as ET


OSCAL_NS = "http://csrc.nist.gov/ns/oscal/1.0"


def ns(tag):
    return f"{{{OSCAL_NS}}}{tag}"


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Parse XML catalog - extract IDs, param mappings, statement parts
# ═══════════════════════════════════════════════════════════════════════════

def parse_catalog_xml(catalog_path):
    """Parse OSCAL XML catalog to extract control structure.

    Returns:
        all_ids: sorted list of all control IDs (including enhancements)
        param_to_ctrl: dict mapping param-id -> control-id
        ctrl_stmt_parts: dict mapping control-id -> list of top-level statement part IDs
    """
    tree = ET.parse(catalog_path)
    root = tree.getroot()

    all_ids = []
    param_to_ctrl = {}
    ctrl_stmt_parts = {}

    for control in root.iter(ns('control')):
        cid = control.get('id')
        all_ids.append(cid)

        # Collect param-id -> control-id mappings
        for param in control.findall(ns('param')):
            param_to_ctrl[param.get('id')] = cid

        # Collect top-level statement part IDs
        for part in control.findall(ns('part')):
            if part.get('name') == 'statement':
                stmt_parts = []
                for child in part.findall(ns('part')):
                    if child.get('name') == 'item':
                        stmt_parts.append(child.get('id'))
                if stmt_parts:
                    ctrl_stmt_parts[cid] = stmt_parts

    return sorted(all_ids), param_to_ctrl, ctrl_stmt_parts


# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Resolve chained profiles (Moderate -> Low -> Catalog)
# ═══════════════════════════════════════════════════════════════════════════

def resolve_profile_low(catalog_ids, profile_low):
    """Resolve the Low baseline: explicit with-ids selection from catalog."""
    catalog_set = set(catalog_ids)
    included = set()
    for imp in profile_low["profile"]["imports"]:
        for sel in imp.get("include-controls", []):
            for cid in sel.get("with-ids", []):
                if cid in catalog_set:
                    included.add(cid)
    return included


def resolve_profile_moderate(catalog_ids, low_ids, profile_mod):
    """Resolve the Moderate baseline: imports Low (include-all) + catalog selections."""
    catalog_set = set(catalog_ids)
    included = set()

    for imp in profile_mod["profile"]["imports"]:
        href = imp.get("href", "")

        if "include-all" in imp:
            if "profile_low" in href:
                included |= low_ids
            continue

        # Direct catalog import with include-controls
        for sel in imp.get("include-controls", []):
            for cid in sel.get("with-ids", []):
                if cid in catalog_set:
                    included.add(cid)
            for match_obj in sel.get("matching", []):
                pattern = match_obj["pattern"]
                for cid in catalog_ids:
                    if fnmatch.fnmatch(cid, pattern):
                        included.add(cid)

        # Apply exclude-controls
        for exc in imp.get("exclude-controls", []):
            for cid in exc.get("with-ids", []):
                included.discard(cid)

    return sorted(included)


# ═══════════════════════════════════════════════════════════════════════════
# Step 3: SSP multi-dimensional analysis
# ═══════════════════════════════════════════════════════════════════════════

def analyze_ssp(effective_set, ssp, param_to_ctrl, ctrl_stmt_parts, profile_params):
    """Analyze SSP across multiple dimensions against effective baseline and catalog."""
    ssp_data = ssp["system-security-plan"]
    impl_reqs = ssp_data["control-implementation"]["implemented-requirements"]
    implemented_ids = {req["control-id"] for req in impl_reqs}

    # Basic gap analysis
    gaps = sorted(effective_set - implemented_ids)
    stale = sorted(implemented_ids - effective_set)

    # Build implementation index
    impl_map = {}
    for req in impl_reqs:
        impl_map[req["control-id"]] = req

    # Broken component references
    comp_uuids = {c["uuid"] for c in ssp_data["system-implementation"]["components"]}
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

    # Parameter gaps: profile-mandated params missing from SSP implementation
    param_gaps = []
    for param_id in profile_params:
        ctrl_id = param_to_ctrl.get(param_id)
        if ctrl_id and ctrl_id in effective_set and ctrl_id in implemented_ids:
            req = impl_map[ctrl_id]
            ssp_param_ids = {sp["param-id"] for sp in req.get("set-parameters", [])}
            if param_id not in ssp_param_ids:
                param_gaps.append({"control_id": ctrl_id, "param_id": param_id})
    param_gaps.sort(key=lambda x: (x["control_id"], x["param_id"]))

    # Statement coverage gaps: catalog statement parts missing from SSP
    stmt_gaps = []
    for cid in sorted(effective_set & implemented_ids):
        expected = set(ctrl_stmt_parts.get(cid, []))
        if not expected:
            continue
        actual = {stmt["statement-id"] for stmt in impl_map[cid].get("statements", [])}
        missing = sorted(expected - actual)
        if missing:
            stmt_gaps.append({"control_id": cid, "missing_statements": missing})
    stmt_gaps.sort(key=lambda x: x["control_id"])

    return gaps, stale, implemented_ids, broken_refs, param_gaps, stmt_gaps


# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Finding -> Control -> POA&M correlation
# ═══════════════════════════════════════════════════════════════════════════

def build_finding_control_map(assessment, effective_set, implemented_ids, poam):
    """Cross-reference findings with baseline, SSP, and POA&M."""
    results = assessment["assessment-results"]["results"][0]
    findings = results["findings"]

    # Build risk -> POA&M index
    poam_items = poam["plan-of-action-and-milestones"]["poam-items"]
    risk_to_poam = {}
    for item in poam_items:
        status = None
        for prop in item.get("props", []):
            if prop["name"] == "status":
                status = prop["value"]
                break
        for rr in item.get("related-risks", []):
            risk_to_poam[rr["risk-uuid"]] = {"status": status}

    finding_map = []
    for f in findings:
        target_id = f["target"]["target-id"]
        control_id = target_id.replace("_obj", "")
        finding_status = f["target"]["status"]["state"]

        has_poam = False
        poam_status = None
        for rr in f.get("related-risks", []):
            risk_uuid = rr["risk-uuid"]
            if risk_uuid in risk_to_poam:
                has_poam = True
                poam_status = risk_to_poam[risk_uuid]["status"]
                break

        finding_map.append({
            "finding_uuid": f["uuid"],
            "target_control_id": control_id,
            "finding_status": finding_status,
            "control_in_baseline": control_id in effective_set,
            "control_implemented": control_id in implemented_ids,
            "has_poam_entry": has_poam,
            "poam_status": poam_status,
        })

    return sorted(finding_map, key=lambda x: x["finding_uuid"])


# ═══════════════════════════════════════════════════════════════════════════
# Step 5: Untracked risks
# ═══════════════════════════════════════════════════════════════════════════

def find_untracked_risks(assessment, poam):
    """Find assessment risks not referenced by any POA&M item."""
    results = assessment["assessment-results"]["results"][0]
    all_risk_uuids = {r["uuid"] for r in results.get("risks", [])}

    poam_items = poam["plan-of-action-and-milestones"]["poam-items"]
    tracked_risks = set()
    for item in poam_items:
        for rr in item.get("related-risks", []):
            tracked_risks.add(rr["risk-uuid"])

    tracked_real = tracked_risks & all_risk_uuids
    return sorted(all_risk_uuids - tracked_real)


# ═══════════════════════════════════════════════════════════════════════════
# Step 6: Remediation coverage
# ═══════════════════════════════════════════════════════════════════════════

def compute_remediation_coverage(assessment, poam):
    """Compute POA&M coverage metrics."""
    results = assessment["assessment-results"]["results"][0]
    all_risk_uuids = {r["uuid"] for r in results.get("risks", [])}

    poam_items = poam["plan-of-action-and-milestones"]["poam-items"]

    valid = 0
    orphaned = 0
    tracked_risk_uuids = set()

    for item in poam_items:
        item_risks = {rr["risk-uuid"] for rr in item.get("related-risks", [])}
        real_risks = item_risks & all_risk_uuids
        if real_risks:
            valid += 1
            tracked_risk_uuids |= real_risks
        else:
            orphaned += 1

    return {
        "total_poam_items": len(poam_items),
        "valid_poam_items": valid,
        "orphaned_poam_items": orphaned,
        "risks_tracked": len(tracked_risk_uuids),
        "risks_untracked": len(all_risk_uuids - tracked_risk_uuids),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    # Parse catalog XML for full structure
    catalog_ids, param_to_ctrl, ctrl_stmt_parts = parse_catalog_xml("/app/catalog.xml")

    # Load JSON documents
    profile_low = load_json("/app/profile_low.json")
    profile_mod = load_json("/app/profile_moderate.json")
    ssp = load_json("/app/ssp.json")
    assessment = load_json("/app/assessment_results.json")
    poam_data = load_json("/app/poam.json")

    # Get profile-mandated parameters
    modify = profile_mod["profile"].get("modify", {})
    profile_params = {sp["param-id"]: sp.get("values", [])
                      for sp in modify.get("set-parameters", [])}

    # Resolve chained profiles
    low_ids = resolve_profile_low(catalog_ids, profile_low)
    effective = resolve_profile_moderate(catalog_ids, low_ids, profile_mod)
    effective_set = set(effective)

    # Multi-dimensional SSP analysis
    gaps, stale, implemented_ids, broken_refs, param_gaps, stmt_gaps = \
        analyze_ssp(effective_set, ssp, param_to_ctrl, ctrl_stmt_parts, profile_params)

    # Finding correlation
    finding_map = build_finding_control_map(
        assessment, effective_set, implemented_ids, poam_data)

    # Untracked risks
    untracked = find_untracked_risks(assessment, poam_data)

    # Remediation coverage
    coverage = compute_remediation_coverage(assessment, poam_data)

    # Build report
    report = {
        "catalog_control_ids": catalog_ids,
        "effective_controls": effective,
        "implementation_gaps": gaps,
        "stale_implementations": stale,
        "broken_component_refs": broken_refs,
        "parameter_gaps": param_gaps,
        "statement_coverage_gaps": stmt_gaps,
        "finding_control_map": finding_map,
        "untracked_risks": untracked,
        "remediation_coverage": coverage,
    }

    with open("/app/reconciliation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Reconciliation report written to /app/reconciliation_report.json")


if __name__ == "__main__":
    main()
