#!/usr/bin/env python3
"""
WQX 3.0 XML Submission Validator

Validates EPA Water Quality Exchange (WQX) 3.0 XML submission files against:
- Field length constraints from the XSD schema
- Domain value controlled vocabularies
- Conditional business rules from the Flow Configuration Document
- Referential integrity within the document hierarchy

"""

import sys
import json
import csv
import os
from xml.etree import ElementTree as ET


WQX_NS = "http://www.exchangenetwork.net/schema/wqx/3"


def tag(name):
    """Return a namespace-qualified element tag."""
    return f"{{{WQX_NS}}}{name}"


def get_text(elem, child_name):
    """Get text content of a child element, or None if missing/empty."""
    child = elem.find(tag(child_name))
    if child is not None and child.text and child.text.strip():
        return child.text.strip()
    return None


def load_domain_values(domain_dir):
    """Load domain value sets from CSV files."""
    domains = {}

    # ActivityType uses 'Code' column
    at_path = os.path.join(domain_dir, "ActivityType.csv")
    with open(at_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["ActivityTypeCode"] = set()
        for row in reader:
            code = row.get("Code", "").strip()
            if code:
                domains["ActivityTypeCode"].add(code)

    # MonitoringLocationType uses 'Name' column
    mlt_path = os.path.join(domain_dir, "MonitoringLocationType.csv")
    with open(mlt_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["MonitoringLocationTypeName"] = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                domains["MonitoringLocationTypeName"].add(name)

    # ActivityMedia uses 'Name' column
    am_path = os.path.join(domain_dir, "ActivityMedia.csv")
    with open(am_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["ActivityMediaName"] = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                domains["ActivityMediaName"].add(name)

    return domains


def load_constraints(constraints_path):
    """Load field length constraints from JSON file."""
    with open(constraints_path, "r") as f:
        return json.load(f)


def check_field_length(errors, value, field_name, constraints, rule_id, context=""):
    """Check a field value against its maxLength constraint."""
    if value is None:
        return
    spec = constraints.get(field_name)
    if spec is None:
        return
    max_len = spec.get("maxLength")
    if max_len is not None and len(value) > max_len:
        msg = f'{field_name} "{value[:40]}..." exceeds maxLength {max_len} (actual: {len(value)})'
        if context:
            msg = f"{context}: {msg}"
        errors.append({
            "rule_id": rule_id,
            "category": "field_length",
            "message": msg,
        })


def validate(xml_path, domain_dir, constraints_path):
    """Validate a WQX 3.0 XML file and return a list of error dicts."""
    errors = []

    tree = ET.parse(xml_path)
    root = tree.getroot()

    constraints = load_constraints(constraints_path)
    domains = load_domain_values(domain_dir)

    # Find Organization element
    org = root.find(tag("Organization"))
    if org is None:
        if root.tag == tag("Organization"):
            org = root
        else:
            errors.append({
                "rule_id": "STRUCT-001",
                "category": "structural",
                "message": "No Organization element found in document",
            })
            return errors

    # --- OrganizationDescription ---
    org_desc = org.find(tag("OrganizationDescription"))
    if org_desc is not None:
        org_id = get_text(org_desc, "OrganizationIdentifier")
        check_field_length(errors, org_id, "OrganizationIdentifier", constraints, "LEN-001")
        org_name = get_text(org_desc, "OrganizationFormalName")
        check_field_length(errors, org_name, "OrganizationFormalName", constraints, "LEN-005")

    # --- Collect Project identifiers ---
    project_ids = set()
    for project in org.findall(tag("Project")):
        proj_id = get_text(project, "ProjectIdentifier")
        if proj_id:
            project_ids.add(proj_id)
            check_field_length(errors, proj_id, "ProjectIdentifier", constraints, "LEN-004")

    # --- Collect MonitoringLocation identifiers and validate ---
    location_ids = set()
    for loc in org.findall(tag("MonitoringLocation")):
        loc_identity = loc.find(tag("MonitoringLocationIdentity"))
        if loc_identity is None:
            continue

        loc_id = get_text(loc_identity, "MonitoringLocationIdentifier")
        if loc_id:
            location_ids.add(loc_id)
            check_field_length(
                errors, loc_id, "MonitoringLocationIdentifier", constraints, "LEN-003"
            )

        loc_name = get_text(loc_identity, "MonitoringLocationName")
        check_field_length(errors, loc_name, "MonitoringLocationName", constraints, "LEN-006")

        # DOM-002: MonitoringLocationTypeName domain check
        loc_type = get_text(loc_identity, "MonitoringLocationTypeName")
        if loc_type and loc_type not in domains.get("MonitoringLocationTypeName", set()):
            errors.append({
                "rule_id": "DOM-002",
                "category": "domain_value",
                "message": (
                    f'MonitoringLocationTypeName "{loc_type}" is not a valid domain value'
                ),
            })

    # --- Validate Activities ---
    activity_ids = set()
    for activity in org.findall(tag("Activity")):
        act_desc = activity.find(tag("ActivityDescription"))
        if act_desc is None:
            continue

        act_id = get_text(act_desc, "ActivityIdentifier")
        if act_id:
            activity_ids.add(act_id)
            check_field_length(errors, act_id, "ActivityIdentifier", constraints, "LEN-002")

        act_type = get_text(act_desc, "ActivityTypeCode")
        act_media = get_text(act_desc, "ActivityMediaName")

        # DOM-001: ActivityTypeCode domain check
        if act_type and act_type not in domains.get("ActivityTypeCode", set()):
            errors.append({
                "rule_id": "DOM-001",
                "category": "domain_value",
                "message": f'ActivityTypeCode "{act_type}" is not a valid domain value',
            })

        # DOM-003: ActivityMediaName domain check
        if act_media and act_media not in domains.get("ActivityMediaName", set()):
            errors.append({
                "rule_id": "DOM-003",
                "category": "domain_value",
                "message": f'ActivityMediaName "{act_media}" is not a valid domain value',
            })

        # BR-002: Vertical Profile requires depth measures
        if act_type and "Vertical Profile" in act_type:
            top_depth = act_desc.find(tag("ActivityTopDepthHeightMeasure"))
            bottom_depth = act_desc.find(tag("ActivityBottomDepthHeightMeasure"))
            if top_depth is None:
                errors.append({
                    "rule_id": "BR-002",
                    "category": "business_rule",
                    "message": (
                        f'Activity "{act_id}" has Vertical Profile type '
                        f"but missing ActivityTopDepthHeightMeasure"
                    ),
                })
            if bottom_depth is None:
                errors.append({
                    "rule_id": "BR-002",
                    "category": "business_rule",
                    "message": (
                        f'Activity "{act_id}" has Vertical Profile type '
                        f"but missing ActivityBottomDepthHeightMeasure"
                    ),
                })

        # REF-001: MonitoringLocationIdentifier must reference defined location
        ref_loc = get_text(act_desc, "MonitoringLocationIdentifier")
        if ref_loc and ref_loc not in location_ids:
            errors.append({
                "rule_id": "REF-001",
                "category": "referential_integrity",
                "message": (
                    f'Activity "{act_id}" references MonitoringLocationIdentifier '
                    f'"{ref_loc}" which is not defined in this Organization'
                ),
            })

        # REF-002: ProjectIdentifier must reference defined project
        ref_proj = get_text(act_desc, "ProjectIdentifier")
        if ref_proj and ref_proj not in project_ids:
            errors.append({
                "rule_id": "REF-002",
                "category": "referential_integrity",
                "message": (
                    f'Activity "{act_id}" references ProjectIdentifier '
                    f'"{ref_proj}" which is not defined in this Organization'
                ),
            })

        # --- Validate Results within this Activity ---
        for res_idx, result in enumerate(activity.findall(tag("Result"))):
            res_desc = result.find(tag("ResultDescription"))
            if res_desc is None:
                continue

            # LEN-007: CharacteristicName length
            char_name = get_text(res_desc, "CharacteristicName")
            check_field_length(
                errors, char_name, "CharacteristicName", constraints, "LEN-007",
                context=f'Activity "{act_id}" Result[{res_idx}]',
            )

            det_cond = get_text(res_desc, "ResultDetectionConditionText")
            stat_base = get_text(res_desc, "StatisticalBaseCode")

            # BR-001: Detection condition requires quantitation limit
            detection_conditions = {
                "Not Detected",
                "Present Above Quantification Limit",
                "Present Below Quantification Limit",
            }
            if det_cond in detection_conditions:
                has_dql = False
                lab_info = result.find(tag("ResultLabInformation"))
                if lab_info is not None:
                    dql = lab_info.find(tag("ResultDetectionQuantitationLimit"))
                    if dql is not None:
                        dql_type = get_text(dql, "DetectionQuantitationLimitTypeName")
                        dql_measure = dql.find(tag("DetectionQuantitationLimitMeasure"))
                        if dql_type and dql_measure is not None:
                            has_dql = True
                if not has_dql:
                    errors.append({
                        "rule_id": "BR-001",
                        "category": "business_rule",
                        "message": (
                            f'Activity "{act_id}" Result[{res_idx}]: '
                            f'ResultDetectionConditionText is "{det_cond}" '
                            f"but DetectionQuantitationLimit is missing or incomplete"
                        ),
                    })

            # BR-004: StatisticalBaseCode requires StatisticalNValueNumeric
            if stat_base:
                stat_n = get_text(res_desc, "StatisticalNValueNumeric")
                if not stat_n:
                    errors.append({
                        "rule_id": "BR-004",
                        "category": "business_rule",
                        "message": (
                            f'Activity "{act_id}" Result[{res_idx}]: '
                            f'StatisticalBaseCode is "{stat_base}" '
                            f"but StatisticalNValueNumeric is missing"
                        ),
                    })

            # BR-003: Tissue media requires biological identification
            if act_media == "Tissue":
                bio_desc = result.find(tag("BiologicalResultDescription"))
                if bio_desc is None:
                    errors.append({
                        "rule_id": "BR-003",
                        "category": "business_rule",
                        "message": (
                            f'Activity "{act_id}" Result[{res_idx}]: '
                            f'ActivityMediaName is "Tissue" but '
                            f"BiologicalResultDescription is missing"
                        ),
                    })
                else:
                    tissue_name = get_text(bio_desc, "SampleTissueAnatomyName")
                    taxon_name = get_text(bio_desc, "SubjectTaxonomicName")
                    if not tissue_name:
                        errors.append({
                            "rule_id": "BR-003",
                            "category": "business_rule",
                            "message": (
                                f'Activity "{act_id}" Result[{res_idx}]: '
                                f'ActivityMediaName is "Tissue" but '
                                f"SampleTissueAnatomyName is missing in "
                                f"BiologicalResultDescription"
                            ),
                        })
                    if not taxon_name:
                        errors.append({
                            "rule_id": "BR-003",
                            "category": "business_rule",
                            "message": (
                                f'Activity "{act_id}" Result[{res_idx}]: '
                                f'ActivityMediaName is "Tissue" but '
                                f"SubjectTaxonomicName is missing in "
                                f"BiologicalResultDescription"
                            ),
                        })

            # BR-005: Group Summary requires GroupSummaryCount
            bio_desc = result.find(tag("BiologicalResultDescription"))
            if bio_desc is not None:
                bio_intent = get_text(bio_desc, "BiologicalIntentName")
                if bio_intent == "Group Summary":
                    group_count = get_text(bio_desc, "GroupSummaryCount")
                    if not group_count:
                        errors.append({
                            "rule_id": "BR-005",
                            "category": "business_rule",
                            "message": (
                                f'Activity "{act_id}" Result[{res_idx}]: '
                                f'BiologicalIntentName is "Group Summary" '
                                f"but GroupSummaryCount is missing"
                            ),
                        })

    # --- Validate ActivityGroups ---
    for ag in org.findall(tag("ActivityGroup")):
        ag_id = get_text(ag, "ActivityGroupIdentifier")
        for ag_act_ref in ag.findall(tag("ActivityIdentifier")):
            ref_act_id = ag_act_ref.text.strip() if ag_act_ref.text else None
            if ref_act_id and ref_act_id not in activity_ids:
                errors.append({
                    "rule_id": "REF-003",
                    "category": "referential_integrity",
                    "message": (
                        f'ActivityGroup "{ag_id}" references ActivityIdentifier '
                        f'"{ref_act_id}" which is not defined in this Organization'
                    ),
                })

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate.py <xml_file>", file=sys.stderr)
        sys.exit(1)

    xml_path = sys.argv[1]
    domain_dir = "/app/domains"
    constraints_path = "/app/constraints.json"

    errors = validate(xml_path, domain_dir, constraints_path)

    # Build category counts
    categories = {}
    for e in errors:
        cat = e.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    report = {
        "file": os.path.basename(xml_path),
        "valid": len(errors) == 0,
        "errors": errors,
        "error_count": len(errors),
        "error_counts_by_category": categories,
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
