#!/usr/bin/env python3
"""OSCAL Multi-Profile Compliance Pipeline Analyzer.

Reads the oscal-cli resolved catalog to determine the authoritative
required control set, analyzes the SSP for compliance gaps, and
cross-references with POAM remediation tracking.
"""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict

OSCAL_NS = "http://csrc.nist.gov/ns/oscal/1.0"


def ns(tag):
    """Return namespaced tag for OSCAL XML."""
    return f"{{{OSCAL_NS}}}{tag}"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def extract_controls_from_resolved(resolved_catalog):
    """Extract a flat index of control-id -> control from the resolved catalog."""
    index = {}
    catalog = resolved_catalog["catalog"]
    for group in catalog.get("groups", []):
        for ctrl in group.get("controls", []):
            index[ctrl["id"]] = ctrl
            for enh in ctrl.get("controls", []):
                index[enh["id"]] = enh
    for ctrl in catalog.get("controls", []):
        index[ctrl["id"]] = ctrl
        for enh in ctrl.get("controls", []):
            index[enh["id"]] = enh
    return index


def get_excluded_controls(profile):
    """Get controls explicitly excluded by any import in the profile."""
    excluded = set()
    for imp in profile["profile"].get("imports", []):
        for exc in imp.get("exclude-controls", []):
            for cid in exc.get("with-ids", []):
                excluded.add(cid)
    return sorted(excluded)


def get_profile_param_assignments(profile):
    """Get parameter value assignments from the profile's modify section."""
    params = {}
    modify = profile["profile"].get("modify", {})
    for sp in modify.get("set-parameters", []):
        params[sp["param-id"]] = sp.get("values", [])
    return params


def get_top_level_statement_items(control):
    """Get IDs of top-level statement items (direct children of statement part)."""
    items = []
    for part in control.get("parts", []):
        if part.get("name") == "statement":
            for child in part.get("parts", []):
                if child.get("name") == "item" and "id" in child:
                    items.append(child["id"])
            if not items and "id" in part:
                items.append(part["id"])
            break
    return items


def map_param_to_control(param_id, control_index):
    """Determine which control a parameter belongs to."""
    for ctrl_id, ctrl in control_index.items():
        for param in ctrl.get("params", []):
            if param["id"] == param_id:
                return ctrl_id
            for prop in param.get("props", []):
                if prop.get("name") == "alt-identifier" and prop.get("value") == param_id:
                    return ctrl_id
    return None


def analyze_ssp(ssp, required_controls, control_index, profile_params):
    """Analyze SSP against resolved profile requirements."""
    valid_components = set()
    for comp in ssp["system-security-plan"].get("system-implementation", {}).get("components", []):
        valid_components.add(comp["uuid"])

    impl_index = defaultdict(lambda: {"statements": set(), "params": set(), "component_refs": set()})
    ctrl_impl = ssp["system-security-plan"].get("control-implementation", {})
    for ir in ctrl_impl.get("implemented-requirements", []):
        ctrl_id = ir["control-id"]
        entry = impl_index[ctrl_id]
        for stmt in ir.get("statements", []):
            entry["statements"].add(stmt["statement-id"])
            for bc in stmt.get("by-components", []):
                entry["component_refs"].add(bc["component-uuid"])
        for sp in ir.get("set-parameters", []):
            entry["params"].add(sp["param-id"])

    implemented_ids = set(impl_index.keys())
    required_set = set(required_controls)

    missing_controls = sorted(required_set - implemented_ids)

    incomplete = {}
    for ctrl_id in sorted(required_set & implemented_ids):
        if ctrl_id not in control_index:
            continue
        catalog_stmts = get_top_level_statement_items(control_index[ctrl_id])
        ssp_stmts = impl_index[ctrl_id]["statements"]
        missing_stmts = [s for s in catalog_stmts if s not in ssp_stmts]
        if missing_stmts:
            incomplete[ctrl_id] = {"missing_statements": missing_stmts}

    param_to_control = {}
    for param_id in profile_params:
        ctrl_id = map_param_to_control(param_id, control_index)
        if ctrl_id:
            param_to_control[param_id] = ctrl_id

    param_gaps = defaultdict(lambda: {"missing": []})
    for param_id, ctrl_id in sorted(param_to_control.items()):
        if ctrl_id in implemented_ids and param_id not in impl_index[ctrl_id]["params"]:
            param_gaps[ctrl_id]["missing"].append(param_id)
    param_gaps = dict(param_gaps)

    extraneous = sorted(implemented_ids - required_set)

    orphaned = set()
    for ctrl_id, entry in impl_index.items():
        for comp_uuid in entry["component_refs"]:
            if comp_uuid not in valid_components:
                orphaned.add(comp_uuid)
    orphaned = sorted(orphaned)

    controls_implemented = len(required_set & implemented_ids)
    controls_required = len(required_set)
    fully_compliant = 0
    for ctrl_id in required_set & implemented_ids:
        if ctrl_id not in incomplete and ctrl_id not in param_gaps:
            fully_compliant += 1
    compliance_pct = round((fully_compliant / controls_required) * 100, 2) if controls_required > 0 else 0.0

    return {
        "missing_controls": missing_controls,
        "incomplete_implementations": incomplete,
        "parameter_gaps": param_gaps,
        "extraneous_controls": extraneous,
        "orphaned_component_refs": orphaned,
        "controls_implemented": controls_implemented,
        "controls_required": controls_required,
        "controls_fully_compliant": fully_compliant,
        "compliance_percentage": compliance_pct,
    }


def parse_poam_xml(poam_path):
    """Parse OSCAL POAM XML, extracting items with control references and risk status."""
    tree = ET.parse(poam_path)
    root = tree.getroot()

    obs_index = {}
    for obs in root.findall(ns("observation")):
        obs_uuid = obs.get("uuid")
        ctrl_id = None
        for prop in obs.findall(ns("prop")):
            if prop.get("name") == "control-id":
                ctrl_id = prop.get("value")
        if obs_uuid and ctrl_id:
            obs_index[obs_uuid] = ctrl_id

    risk_index = {}
    for risk in root.findall(ns("risk")):
        risk_uuid = risk.get("uuid")
        status_elem = risk.find(ns("status"))
        status = status_elem.text if status_elem is not None else "unknown"
        if risk_uuid:
            risk_index[risk_uuid] = status

    poam_items = []
    for item in root.findall(ns("poam-item")):
        poam_uuid = item.get("uuid")
        title_elem = item.find(ns("title"))
        title = title_elem.text if title_elem is not None else ""

        status = "unknown"
        for prop in item.findall(ns("prop")):
            if prop.get("name") == "status":
                status = prop.get("value")

        ctrl_id = None
        related_obs = item.find(ns("related-observation"))
        if related_obs is not None:
            obs_uuid = related_obs.get("observation-uuid")
            ctrl_id = obs_index.get(obs_uuid)

        risk_status = "unknown"
        related_risk = item.find(ns("related-risk"))
        if related_risk is not None:
            risk_uuid = related_risk.get("risk-uuid")
            risk_status = risk_index.get(risk_uuid, "unknown")

        poam_items.append({
            "poam_uuid": poam_uuid,
            "control_id": ctrl_id,
            "title": title,
            "status": status,
            "risk_status": risk_status,
        })

    return poam_items


def build_remediation_tracking(poam_items, gap_analysis):
    """Cross-reference POAM items with gap analysis results."""
    missing = set(gap_analysis["missing_controls"])
    incomplete = set(gap_analysis["incomplete_implementations"].keys())
    param_gaps_set = set(gap_analysis["parameter_gaps"].keys())

    all_gaps = missing | incomplete | param_gaps_set

    for item in poam_items:
        ctrl_id = item["control_id"]
        if ctrl_id in missing:
            item["gap_type"] = "missing_control"
        elif ctrl_id in incomplete:
            item["gap_type"] = "incomplete_statements"
        elif ctrl_id in param_gaps_set:
            item["gap_type"] = "parameter_gap"
        else:
            item["gap_type"] = "unknown"

    poam_control_ids = {item["control_id"] for item in poam_items if item["control_id"]}
    gaps_with_poam = sorted(all_gaps & poam_control_ids)
    gaps_without_poam = sorted(all_gaps - poam_control_ids)

    in_progress = sum(1 for item in poam_items if item["status"] == "in-progress")
    completed = sum(1 for item in poam_items if item["status"] == "completed")
    risk_accepted = sum(1 for item in poam_items if item["status"] == "risk-accepted")

    return {
        "poam_items": poam_items,
        "gaps_with_poam": gaps_with_poam,
        "gaps_without_poam": gaps_without_poam,
        "total_poam_items": len(poam_items),
        "remediation_in_progress": in_progress,
        "remediation_completed": completed,
        "risk_accepted": risk_accepted,
    }


def main():
    # Read the oscal-cli resolved catalog for the authoritative required control set
    resolved = load_json("/app/resolved_catalog.json")
    control_index = extract_controls_from_resolved(resolved)
    required_controls = sorted(control_index.keys())

    # Read org profile for excluded controls list and parameter assignments
    profile = load_json("/app/org_profile.json")
    excluded_controls = get_excluded_controls(profile)
    profile_params = get_profile_param_assignments(profile)

    # Read SSP and analyze against resolved requirements
    ssp = load_json("/app/system_ssp.json")
    analysis = analyze_ssp(ssp, required_controls, control_index, profile_params)

    # Parse POAM XML and cross-reference with gap analysis
    poam_items = parse_poam_xml("/app/poam.xml")
    gap_data = {
        "missing_controls": analysis["missing_controls"],
        "incomplete_implementations": analysis["incomplete_implementations"],
        "parameter_gaps": analysis["parameter_gaps"],
    }
    remediation = build_remediation_tracking(poam_items, gap_data)

    report = {
        "resolved_profile": {
            "required_controls": required_controls,
            "total_required": len(required_controls),
            "excluded_controls": excluded_controls,
        },
        "gap_analysis": {
            "missing_controls": analysis["missing_controls"],
            "incomplete_implementations": analysis["incomplete_implementations"],
            "parameter_gaps": analysis["parameter_gaps"],
            "extraneous_controls": analysis["extraneous_controls"],
            "orphaned_component_refs": analysis["orphaned_component_refs"],
        },
        "compliance_summary": {
            "controls_implemented": analysis["controls_implemented"],
            "controls_required": analysis["controls_required"],
            "controls_fully_compliant": analysis["controls_fully_compliant"],
            "compliance_percentage": analysis["compliance_percentage"],
        },
        "remediation_tracking": remediation,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit report written to /app/audit_report.json")
    print(f"Required controls: {len(required_controls)}")
    print(f"Compliance: {analysis['compliance_percentage']}%")
    print(f"POAM items tracked: {len(poam_items)}")


if __name__ == "__main__":
    main()
