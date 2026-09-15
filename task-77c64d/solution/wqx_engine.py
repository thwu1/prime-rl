#!/usr/bin/env python3
"""
WQX 3.0 Schema Intelligence and Conformance Engine

Resolves the XSD type hierarchy, analyzes schema evolution from the change log,
discovers conditional validation rules, and validates XML submissions against
all constraint layers.

"""

import json
import csv
import os
import subprocess
import sys
import re
from xml.etree import ElementTree as ET

# ---- Constants ----
WQX_NS = "http://www.exchangenetwork.net/schema/wqx/3"
XSD_NS = "http://www.w3.org/2001/XMLSchema"

SCHEMA_DIR = "/app/schemas"
DOMAIN_DIR = "/app/domains"
SUBMISSION_DIR = "/app/submissions"
CHANGE_LOG_PATH = "/app/change_log.txt"
SCHEMA_ROOT = os.path.join(SCHEMA_DIR, "root.xsd")

REPORTS_DIR = "/app/reports"
TYPE_SYSTEM_OUT = "/app/type_system.json"
EVOLUTION_OUT = "/app/schema_evolution.json"


def wqx(name):
    return f"{{{WQX_NS}}}{name}"


def get_text(elem, child_name):
    child = elem.find(wqx(child_name))
    if child is not None and child.text and child.text.strip():
        return child.text.strip()
    return None


# =====================================================================
# Phase 1: XSD Type System Resolution
# =====================================================================

def build_type_system():
    """Parse all XSD files and resolve the complete type hierarchy."""
    types = {}
    element_type_map = {}

    for fname in sorted(os.listdir(SCHEMA_DIR)):
        if not fname.endswith(".xsd"):
            continue
        tree = ET.parse(os.path.join(SCHEMA_DIR, fname))
        root = tree.getroot()

        # Extract simpleType definitions
        for st in root.findall(f"{{{XSD_NS}}}simpleType"):
            tname = st.get("name")
            if not tname:
                continue
            restriction = st.find(f"{{{XSD_NS}}}restriction")
            if restriction is None:
                continue
            base = restriction.get("base", "")
            restrictions = {}
            for child in restriction:
                facet = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                val = child.get("value")
                if val is not None:
                    try:
                        restrictions[facet] = int(val)
                    except ValueError:
                        restrictions[facet] = val
            # Normalize base type prefix
            if ":" in base:
                prefix, local = base.split(":", 1)
                if prefix in ("xs", "xsd"):
                    base = f"xs:{local}"
            types[tname] = {"base_type": base, "restrictions": restrictions}

        # Extract global element declarations
        for elem in root.findall(f"{{{XSD_NS}}}element"):
            ename = elem.get("name")
            etype = elem.get("type")
            if ename and etype:
                if ":" in etype:
                    etype = etype.split(":", 1)[-1]
                element_type_map[ename] = etype

    # Resolve inheritance chains to primitive types
    for tname in list(types.keys()):
        base = types[tname]["base_type"]
        visited = {tname}
        current = base
        while current in types and current not in visited:
            visited.add(current)
            # Merge inherited restrictions (child restrictions override)
            for k, v in types[current]["restrictions"].items():
                if k not in types[tname]["restrictions"]:
                    types[tname]["restrictions"][k] = v
            current = types[current]["base_type"]
        # Set resolved base type
        if current.startswith("xs:"):
            types[tname]["base_type"] = current

    return {"types": types, "element_type_map": element_type_map}


def extract_constraints(type_system):
    """Derive element → constraint map from the resolved type system."""
    constraints = {}
    types = type_system["types"]
    emap = type_system["element_type_map"]
    for elem_name, type_name in emap.items():
        if type_name in types:
            restr = types[type_name]["restrictions"]
            if restr:
                constraints[elem_name] = dict(restr)
    return constraints


# =====================================================================
# Phase 2: Schema Evolution Analysis
# =====================================================================

def _find_version_date(content, pos):
    """Find the enclosing version header date for a position in the text."""
    preceding = content[:pos]
    matches = list(re.finditer(
        r"\*\*\s*(?:CHANGES\s+(?:PRIOR\s+TO|MADE\s+FOR))\s+([\d/]+)",
        preceding, re.IGNORECASE
    ))
    if matches:
        return matches[-1].group(1).strip()
    return "unknown"


def parse_evolution():
    """Parse the WQX Schema Change Log into structured evolution data."""
    with open(CHANGE_LOG_PATH, "r") as f:
        content = f.read()

    # Count version sections
    version_headers = re.findall(
        r"\*\*\s*(?:CHANGES\s+(?:PRIOR\s+TO|MADE\s+FOR))\s+[\d/]+",
        content, re.IGNORECASE
    )
    total_sections = len(version_headers)

    # ---- Field length changes ----
    field_length_changes = []
    seen_fl = set()

    def add_fl(field, from_len, to_len, pos):
        key = (field, to_len)
        if key not in seen_fl:
            seen_fl.add(key)
            field_length_changes.append({
                "field": field,
                "from_length": from_len,
                "to_length": to_len,
                "date": _find_version_date(content, pos)
            })

    # "Increased X maxLength from Y to Z"
    for m in re.finditer(
        r"(?:Increased|Changed)\s+([\w]+)\s+(?:maxLength|maxlength)\s+(?:from\s+)?(\d+)\s+to\s+(\d+)",
        content, re.IGNORECASE
    ):
        add_fl(m.group(1), int(m.group(2)), int(m.group(3)), m.start())

    # "Increased X from Y to Z" or "... from Y string to Z string"
    for m in re.finditer(
        r"Increased\s+([\w]+)\s+from\s+(\d+)\s+(?:string\s+)?to\s+(\d+)",
        content, re.IGNORECASE
    ):
        add_fl(m.group(1), int(m.group(2)), int(m.group(3)), m.start())

    # "Increased X length from Y to Z"
    for m in re.finditer(
        r"Increased\s+([\w]+)\s+length\s+from\s+(\d+)\s+to\s+(\d+)",
        content, re.IGNORECASE
    ):
        add_fl(m.group(1), int(m.group(2)), int(m.group(3)), m.start())

    # "Changed maxlength of X from Y to Z"
    for m in re.finditer(
        r"Changed\s+maxlength\s+of\s+([\w]+)\s+from\s+(\d+)\s+to\s+(\d+)",
        content, re.IGNORECASE
    ):
        add_fl(m.group(1), int(m.group(2)), int(m.group(3)), m.start())

    # "Changed X maxlength to Y characters"
    for m in re.finditer(
        r"[Cc]hanged\s+([\w]+)\s+maxlength\s+to\s+(\d+)\s+characters",
        content
    ):
        add_fl(m.group(1), 0, int(m.group(2)), m.start())

    # "Increased X maxLength from Y to Z" (alt: maxlength, mixed case)
    for m in re.finditer(
        r"Increased\s+([\w]+)\s+maxLength\s+from\s+(\d+)\s+to\s+(\d+)",
        content
    ):
        add_fl(m.group(1), int(m.group(2)), int(m.group(3)), m.start())

    # "Refactored X data type from ... to string maxLength Y"
    for m in re.finditer(
        r"Refactored\s+([\w]+)\s+data\s+type\s+from\s+\w+\s+to\s+string\s+maxLength\s+(\d+)",
        content, re.IGNORECASE
    ):
        add_fl(m.group(1), 0, int(m.group(2)), m.start())

    # ---- Element renames ----
    element_renames = []
    seen_rn = set()

    skip_words = {
        "minoccurs", "maxoccurs", "the", "name", "all", "result", "be",
        "no", "optional", "required", "minlength", "0", "1", "unbounded",
        "true", "false", "value", "it", "type", "not", "file", "was",
        "longer", "data", "schema", "base", "from"
    }

    def add_rn(old, new, pos):
        if old.lower() in skip_words or new.lower() in skip_words:
            return
        if len(old) < 3 or len(new) < 3:
            return
        if not old[0].isupper() or not new[0].isupper():
            return
        key = (old, new)
        if key not in seen_rn:
            seen_rn.add(key)
            element_renames.append({
                "old_name": old,
                "new_name": new,
                "date": _find_version_date(content, pos)
            })

    # "Changed X to Y"
    for m in re.finditer(r"Changed\s+([\w]+)\s+to\s+([\w]+)", content):
        add_rn(m.group(1), m.group(2), m.start())

    # "Renamed X to Y"
    for m in re.finditer(r"Renamed\s+([\w]+)\s+to\s+([\w]+)", content):
        add_rn(m.group(1), m.group(2), m.start())

    # "Updated element X to Y" (various forms including "Updated element, type, and definition X to Y")
    for m in re.finditer(
        r"Updated\s+element[^\n]*?([A-Z][\w]+)\s+to\s+([A-Z][\w]+)",
        content
    ):
        add_rn(m.group(1), m.group(2), m.start())

    # "Changed the name of 'X' to 'Y'" or similar
    for m in re.finditer(
        r'Changed\s+the\s+name\s+of\s+["\']?([\w]+)["\']?\s+to\s+["\']?([\w]+)',
        content
    ):
        add_rn(m.group(1), m.group(2), m.start())

    # ---- Business rules ----
    business_rules = []

    for m in re.finditer(
        r"(?:Schematron|Business\s+Rule)[:\s]+\s*(.*?)(?:\n|$)",
        content, re.IGNORECASE
    ):
        desc = m.group(1).strip()
        if desc and len(desc) > 5:
            business_rules.append({
                "date": _find_version_date(content, m.start()),
                "description": desc
            })

    return {
        "total_version_sections": total_sections,
        "field_length_changes": field_length_changes,
        "element_renames": element_renames,
        "business_rules": business_rules
    }


# =====================================================================
# Phase 3: Domain Value Loading
# =====================================================================

def load_domains():
    """Load controlled vocabulary sets from CSV files."""
    domains = {}

    # ActivityType CSV
    at_path = os.path.join(DOMAIN_DIR, "ActivityType.csv")
    with open(at_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        vals = set()
        for row in reader:
            code = row.get("Code", "").strip()
            if code:
                vals.add(code)
        domains["ActivityTypeCode"] = vals

    # MonitoringLocationType CSV
    mlt_path = os.path.join(DOMAIN_DIR, "MonitoringLocationType.csv")
    with open(mlt_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        vals = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                vals.add(name)
        domains["MonitoringLocationTypeName"] = vals

    # ActivityMedia CSV
    am_path = os.path.join(DOMAIN_DIR, "ActivityMedia.csv")
    with open(am_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        vals = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                vals.add(name)
        domains["ActivityMediaName"] = vals

    return domains


# =====================================================================
# Phase 4: Schema Validation (xmllint)
# =====================================================================

def run_schema_validation(schema_path, xml_path):
    """Run xmllint --noout --schema to check structural validity."""
    try:
        proc = subprocess.run(
            ["xmllint", "--noout", "--schema", schema_path, xml_path],
            capture_output=True, text=True, timeout=30
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# =====================================================================
# Phase 5: Multi-Layer Conformance Validation
# =====================================================================

def validate_submission(xml_path, constraints, domains):
    """Validate a WQX XML file against all constraint layers."""
    violations = []

    tree = ET.parse(xml_path)
    root = tree.getroot()

    org = root.find(wqx("Organization"))
    if org is None:
        if root.tag == wqx("Organization"):
            org = root
        else:
            return violations

    # --- Helper to check field length ---
    def check_length(value, field_name):
        if value is None:
            return
        spec = constraints.get(field_name)
        if spec is None:
            return
        max_len = spec.get("maxLength")
        if max_len is not None and len(value) > max_len:
            violations.append({
                "category": "field_length",
                "element": field_name,
                "detail": f"Value length {len(value)} exceeds maxLength {max_len}"
            })

    # --- Organization Description ---
    org_desc = org.find(wqx("OrganizationDescription"))
    if org_desc is not None:
        check_length(get_text(org_desc, "OrganizationIdentifier"), "OrganizationIdentifier")
        check_length(get_text(org_desc, "OrganizationFormalName"), "OrganizationFormalName")

    # --- Collect Project IDs ---
    project_ids = set()
    for project in org.findall(wqx("Project")):
        pid = get_text(project, "ProjectIdentifier")
        if pid:
            project_ids.add(pid)
            check_length(pid, "ProjectIdentifier")

    # --- Collect MonitoringLocation IDs ---
    location_ids = set()
    for loc in org.findall(wqx("MonitoringLocation")):
        loc_id_elem = loc.find(wqx("MonitoringLocationIdentity"))
        if loc_id_elem is None:
            continue
        lid = get_text(loc_id_elem, "MonitoringLocationIdentifier")
        if lid:
            location_ids.add(lid)
            check_length(lid, "MonitoringLocationIdentifier")
        lname = get_text(loc_id_elem, "MonitoringLocationName")
        check_length(lname, "MonitoringLocationName")
        ltype = get_text(loc_id_elem, "MonitoringLocationTypeName")
        if ltype and ltype not in domains.get("MonitoringLocationTypeName", set()):
            violations.append({
                "category": "domain_value",
                "element": "MonitoringLocationTypeName",
                "detail": f'Value "{ltype}" is not in the allowed domain values'
            })

    # --- Validate Activities ---
    activity_ids = set()
    for activity in org.findall(wqx("Activity")):
        act_desc = activity.find(wqx("ActivityDescription"))
        if act_desc is None:
            continue

        act_id = get_text(act_desc, "ActivityIdentifier")
        if act_id:
            activity_ids.add(act_id)
            check_length(act_id, "ActivityIdentifier")

        act_type = get_text(act_desc, "ActivityTypeCode")
        act_media = get_text(act_desc, "ActivityMediaName")

        # Domain: ActivityTypeCode
        if act_type and act_type not in domains.get("ActivityTypeCode", set()):
            violations.append({
                "category": "domain_value",
                "element": "ActivityTypeCode",
                "detail": f'Value "{act_type}" is not in the allowed domain values'
            })

        # Domain: ActivityMediaName
        if act_media and act_media not in domains.get("ActivityMediaName", set()):
            violations.append({
                "category": "domain_value",
                "element": "ActivityMediaName",
                "detail": f'Value "{act_media}" is not in the allowed domain values'
            })

        # BR-002: Vertical Profile requires depth measures
        if act_type and "Vertical Profile" in act_type:
            if act_desc.find(wqx("ActivityTopDepthHeightMeasure")) is None:
                violations.append({
                    "category": "business_rule",
                    "element": "ActivityTopDepthHeightMeasure",
                    "detail": "Vertical Profile activity missing ActivityTopDepthHeightMeasure"
                })
            if act_desc.find(wqx("ActivityBottomDepthHeightMeasure")) is None:
                violations.append({
                    "category": "business_rule",
                    "element": "ActivityBottomDepthHeightMeasure",
                    "detail": "Vertical Profile activity missing ActivityBottomDepthHeightMeasure"
                })

        # Referential integrity: MonitoringLocationIdentifier
        ref_loc = get_text(act_desc, "MonitoringLocationIdentifier")
        if ref_loc and ref_loc not in location_ids:
            violations.append({
                "category": "referential_integrity",
                "element": "MonitoringLocationIdentifier",
                "detail": f'Activity references undefined MonitoringLocation "{ref_loc}"'
            })

        # Referential integrity: ProjectIdentifier(s)
        for proj_elem in act_desc.findall(wqx("ProjectIdentifier")):
            ref_proj = proj_elem.text.strip() if proj_elem.text else None
            if ref_proj and ref_proj not in project_ids:
                violations.append({
                    "category": "referential_integrity",
                    "element": "ProjectIdentifier",
                    "detail": f'Activity references undefined Project "{ref_proj}"'
                })

        # --- Validate Results within this Activity ---
        for result in activity.findall(wqx("Result")):
            res_desc = result.find(wqx("ResultDescription"))
            if res_desc is None:
                continue

            char_name = get_text(res_desc, "CharacteristicName")
            check_length(char_name, "CharacteristicName")

            det_cond = get_text(res_desc, "ResultDetectionConditionText")
            stat_base = get_text(res_desc, "StatisticalBaseCode")

            # BR-001: Detection condition requires quantitation limit
            detection_triggers = {
                "Not Detected",
                "Present Above Quantification Limit",
                "Present Below Quantification Limit",
            }
            if det_cond in detection_triggers:
                has_dql = False
                lab_info = result.find(wqx("ResultLabInformation"))
                if lab_info is not None:
                    dql = lab_info.find(wqx("ResultDetectionQuantitationLimit"))
                    if dql is not None:
                        dql_type = get_text(dql, "DetectionQuantitationLimitTypeName")
                        dql_measure = dql.find(wqx("DetectionQuantitationLimitMeasure"))
                        if dql_type and dql_measure is not None:
                            has_dql = True
                if not has_dql:
                    violations.append({
                        "category": "business_rule",
                        "element": "ResultDetectionQuantitationLimit",
                        "detail": f'Detection condition "{det_cond}" requires complete quantitation limit'
                    })

            # BR-004: Statistical base requires N value
            if stat_base:
                stat_n = get_text(res_desc, "StatisticalNValueNumeric")
                if not stat_n:
                    violations.append({
                        "category": "business_rule",
                        "element": "StatisticalNValueNumeric",
                        "detail": f'StatisticalBaseCode "{stat_base}" requires StatisticalNValueNumeric'
                    })

            # BR-003: Tissue media requires biological identification
            if act_media == "Tissue":
                bio_desc = result.find(wqx("BiologicalResultDescription"))
                if bio_desc is None:
                    violations.append({
                        "category": "business_rule",
                        "element": "BiologicalResultDescription",
                        "detail": "Tissue activity Result missing BiologicalResultDescription"
                    })
                else:
                    tissue_name = get_text(bio_desc, "SampleTissueAnatomyName")
                    taxon_name = get_text(bio_desc, "SubjectTaxonomicName")
                    if not tissue_name:
                        violations.append({
                            "category": "business_rule",
                            "element": "SampleTissueAnatomyName",
                            "detail": "Tissue activity Result missing non-empty SampleTissueAnatomyName"
                        })
                    if not taxon_name:
                        violations.append({
                            "category": "business_rule",
                            "element": "SubjectTaxonomicName",
                            "detail": "Tissue activity Result missing non-empty SubjectTaxonomicName"
                        })

            # BR-005: Group Summary requires count
            bio_desc = result.find(wqx("BiologicalResultDescription"))
            if bio_desc is not None:
                bio_intent = get_text(bio_desc, "BiologicalIntentName")
                if bio_intent == "Group Summary":
                    group_count = get_text(bio_desc, "GroupSummaryCount")
                    if not group_count:
                        violations.append({
                            "category": "business_rule",
                            "element": "GroupSummaryCount",
                            "detail": "Group Summary requires non-empty GroupSummaryCount"
                        })

    # --- ActivityGroups ---
    for ag in org.findall(wqx("ActivityGroup")):
        for ag_act_ref in ag.findall(wqx("ActivityIdentifier")):
            ref_act_id = ag_act_ref.text.strip() if ag_act_ref.text else None
            if ref_act_id and ref_act_id not in activity_ids:
                violations.append({
                    "category": "referential_integrity",
                    "element": "ActivityIdentifier",
                    "detail": f'ActivityGroup references undefined Activity "{ref_act_id}"'
                })

    return violations


# =====================================================================
# Main
# =====================================================================

def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Phase 1: Build type system
    print("Phase 1: Resolving XSD type system...", file=sys.stderr)
    type_system = build_type_system()
    with open(TYPE_SYSTEM_OUT, "w") as f:
        json.dump(type_system, f, indent=2, sort_keys=True)
    print(f"  {len(type_system['types'])} types, "
          f"{len(type_system['element_type_map'])} element mappings",
          file=sys.stderr)

    # Derive element constraints from type system
    constraints = extract_constraints(type_system)

    # Phase 2: Parse schema evolution
    print("Phase 2: Analyzing schema evolution...", file=sys.stderr)
    evolution = parse_evolution()
    with open(EVOLUTION_OUT, "w") as f:
        json.dump(evolution, f, indent=2)
    print(f"  {evolution['total_version_sections']} version sections, "
          f"{len(evolution['field_length_changes'])} length changes, "
          f"{len(evolution['element_renames'])} renames, "
          f"{len(evolution['business_rules'])} business rules",
          file=sys.stderr)

    # Phase 3: Load domain values
    domains = load_domains()

    # Phase 4: Validate submissions
    print("Phase 4: Validating submissions...", file=sys.stderr)
    for filename in sorted(os.listdir(SUBMISSION_DIR)):
        if not filename.endswith(".xml"):
            continue
        xml_path = os.path.join(SUBMISSION_DIR, filename)

        schema_valid = run_schema_validation(SCHEMA_ROOT, xml_path)
        violations = validate_submission(xml_path, constraints, domains)

        category_counts = {}
        for v in violations:
            cat = v["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        total_errors = len(violations)
        report = {
            "file": filename,
            "schema_valid": schema_valid,
            "valid": schema_valid is True and total_errors == 0,
            "total_errors": total_errors,
            "violations": violations,
            "category_counts": category_counts,
        }

        report_path = os.path.join(REPORTS_DIR, f"{filename}.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        status = "VALID" if report["valid"] else "INVALID"
        print(f"  {filename}: {status} (schema={schema_valid}, errors={total_errors})",
              file=sys.stderr)

    print("Analysis complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
