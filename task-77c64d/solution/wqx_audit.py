#!/usr/bin/env python3
"""
WQX 3.0 Submission Conformance Analyzer

Parses WQX 3.0 XSD schemas to extract field constraints, validates XML
submissions against all applicable conformance requirements, and generates
structured reports.

"""

import json
import csv
import os
import subprocess
import sys
from xml.etree import ElementTree as ET

WQX_NS = "http://www.exchangenetwork.net/schema/wqx/3"
XSD_NS = "http://www.w3.org/2001/XMLSchema"

SCHEMAS_DIR = "/app/schemas"
DOMAINS_DIR = "/app/domains"
SUBMISSIONS_DIR = "/app/submissions"
REPORTS_DIR = "/app/reports"
SCHEMA_ROOT = os.path.join(SCHEMAS_DIR, "root.xsd")
CONSTRAINTS_OUT = "/app/extracted_constraints.json"


def extract_constraints(schemas_dir):
    """Parse all XSD files to extract element -> constraint mappings.

    Strategy:
    1. Scan all .xsd files for xsd:simpleType definitions with string
       restrictions (maxLength/minLength).
    2. Scan all .xsd files for xsd:element declarations mapping element
       names to their type references.
    3. Correlate element names with their simpleType constraints.
    """
    simple_types = {}
    elements = {}

    for filename in sorted(os.listdir(schemas_dir)):
        if not filename.endswith(".xsd"):
            continue
        filepath = os.path.join(schemas_dir, filename)
        tree = ET.parse(filepath)
        root = tree.getroot()

        for st in root.findall(f"{{{XSD_NS}}}simpleType"):
            name = st.get("name")
            if not name:
                continue
            restriction = st.find(f"{{{XSD_NS}}}restriction")
            if restriction is None:
                continue
            base = restriction.get("base", "")
            if "string" not in base:
                continue
            constraints = {}
            ml = restriction.find(f"{{{XSD_NS}}}maxLength")
            if ml is not None:
                constraints["maxLength"] = int(ml.get("value"))
            mnl = restriction.find(f"{{{XSD_NS}}}minLength")
            if mnl is not None:
                constraints["minLength"] = int(mnl.get("value"))
            if constraints:
                simple_types[name] = constraints

        for elem in root.findall(f"{{{XSD_NS}}}element"):
            name = elem.get("name")
            type_ref = elem.get("type", "")
            if not name or not type_ref:
                continue
            if ":" in type_ref:
                type_ref = type_ref.split(":", 1)[1]
            elements[name] = type_ref

    result = {}
    for elem_name, type_name in elements.items():
        if type_name in simple_types:
            result[elem_name] = dict(simple_types[type_name])
    return result


def run_schema_validation(schema_path, xml_path):
    """Run xmllint --noout --schema and return whether valid."""
    try:
        proc = subprocess.run(
            ["xmllint", "--noout", "--schema", schema_path, xml_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def load_domain_values(domain_dir):
    """Load domain value sets from CSV files."""
    domains = {}

    at_path = os.path.join(domain_dir, "ActivityType.csv")
    with open(at_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["ActivityTypeCode"] = set()
        for row in reader:
            code = row.get("Code", "").strip()
            if code:
                domains["ActivityTypeCode"].add(code)

    mlt_path = os.path.join(domain_dir, "MonitoringLocationType.csv")
    with open(mlt_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["MonitoringLocationTypeName"] = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                domains["MonitoringLocationTypeName"].add(name)

    am_path = os.path.join(domain_dir, "ActivityMedia.csv")
    with open(am_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        domains["ActivityMediaName"] = set()
        for row in reader:
            name = row.get("Name", "").strip()
            if name:
                domains["ActivityMediaName"].add(name)

    return domains


def tag(name):
    return f"{{{WQX_NS}}}{name}"


def get_text(elem, child_name):
    child = elem.find(tag(child_name))
    if child is not None and child.text and child.text.strip():
        return child.text.strip()
    return None


def validate_xml(xml_path, constraints, domains):
    """Validate a WQX XML file and return violations list."""
    violations = []

    tree = ET.parse(xml_path)
    root = tree.getroot()

    org = root.find(tag("Organization"))
    if org is None:
        if root.tag == tag("Organization"):
            org = root
        else:
            return violations

    def check_length(value, field_name):
        if value is None:
            return
        spec = constraints.get(field_name)
        if spec is None:
            return
        max_len = spec.get("maxLength")
        if max_len is not None and len(value) > max_len:
            violations.append(
                {
                    "category": "field_length",
                    "element": field_name,
                    "detail": f"Value length {len(value)} exceeds maxLength {max_len}",
                }
            )

    # OrganizationDescription
    org_desc = org.find(tag("OrganizationDescription"))
    if org_desc is not None:
        check_length(
            get_text(org_desc, "OrganizationIdentifier"), "OrganizationIdentifier"
        )
        check_length(
            get_text(org_desc, "OrganizationFormalName"), "OrganizationFormalName"
        )

    # Collect Project IDs
    project_ids = set()
    for project in org.findall(tag("Project")):
        pid = get_text(project, "ProjectIdentifier")
        if pid:
            project_ids.add(pid)
            check_length(pid, "ProjectIdentifier")

    # Collect MonitoringLocation IDs and validate
    location_ids = set()
    for loc in org.findall(tag("MonitoringLocation")):
        loc_identity = loc.find(tag("MonitoringLocationIdentity"))
        if loc_identity is None:
            continue

        lid = get_text(loc_identity, "MonitoringLocationIdentifier")
        if lid:
            location_ids.add(lid)
            check_length(lid, "MonitoringLocationIdentifier")

        lname = get_text(loc_identity, "MonitoringLocationName")
        check_length(lname, "MonitoringLocationName")

        ltype = get_text(loc_identity, "MonitoringLocationTypeName")
        if ltype and ltype not in domains.get("MonitoringLocationTypeName", set()):
            violations.append(
                {
                    "category": "domain_value",
                    "element": "MonitoringLocationTypeName",
                    "detail": f'Value "{ltype}" is not in the allowed domain values',
                }
            )

    # Validate Activities
    activity_ids = set()
    for activity in org.findall(tag("Activity")):
        act_desc = activity.find(tag("ActivityDescription"))
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
            violations.append(
                {
                    "category": "domain_value",
                    "element": "ActivityTypeCode",
                    "detail": f'Value "{act_type}" is not in the allowed domain values',
                }
            )

        # Domain: ActivityMediaName
        if act_media and act_media not in domains.get("ActivityMediaName", set()):
            violations.append(
                {
                    "category": "domain_value",
                    "element": "ActivityMediaName",
                    "detail": f'Value "{act_media}" is not in the allowed domain values',
                }
            )

        # BR-002: Vertical Profile depth measures
        if act_type and "Vertical Profile" in act_type:
            if act_desc.find(tag("ActivityTopDepthHeightMeasure")) is None:
                violations.append(
                    {
                        "category": "business_rule",
                        "element": "ActivityTopDepthHeightMeasure",
                        "detail": "Vertical Profile activity missing ActivityTopDepthHeightMeasure",
                    }
                )
            if act_desc.find(tag("ActivityBottomDepthHeightMeasure")) is None:
                violations.append(
                    {
                        "category": "business_rule",
                        "element": "ActivityBottomDepthHeightMeasure",
                        "detail": "Vertical Profile activity missing ActivityBottomDepthHeightMeasure",
                    }
                )

        # Referential integrity: MonitoringLocationIdentifier
        ref_loc = get_text(act_desc, "MonitoringLocationIdentifier")
        if ref_loc and ref_loc not in location_ids:
            violations.append(
                {
                    "category": "referential_integrity",
                    "element": "MonitoringLocationIdentifier",
                    "detail": f'Activity references undefined MonitoringLocation "{ref_loc}"',
                }
            )

        # Referential integrity: ProjectIdentifier(s)
        for proj_elem in act_desc.findall(tag("ProjectIdentifier")):
            ref_proj = proj_elem.text.strip() if proj_elem.text else None
            if ref_proj and ref_proj not in project_ids:
                violations.append(
                    {
                        "category": "referential_integrity",
                        "element": "ProjectIdentifier",
                        "detail": f'Activity references undefined Project "{ref_proj}"',
                    }
                )

        # Validate Results
        for result in activity.findall(tag("Result")):
            res_desc = result.find(tag("ResultDescription"))
            if res_desc is None:
                continue

            char_name = get_text(res_desc, "CharacteristicName")
            check_length(char_name, "CharacteristicName")

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
                        dql_measure = dql.find(
                            tag("DetectionQuantitationLimitMeasure")
                        )
                        if dql_type and dql_measure is not None:
                            has_dql = True
                if not has_dql:
                    violations.append(
                        {
                            "category": "business_rule",
                            "element": "ResultDetectionQuantitationLimit",
                            "detail": f'Detection condition "{det_cond}" requires complete quantitation limit',
                        }
                    )

            # BR-004: Statistical base requires N value
            if stat_base:
                stat_n = get_text(res_desc, "StatisticalNValueNumeric")
                if not stat_n:
                    violations.append(
                        {
                            "category": "business_rule",
                            "element": "StatisticalNValueNumeric",
                            "detail": f'StatisticalBaseCode "{stat_base}" requires StatisticalNValueNumeric',
                        }
                    )

            # BR-003: Tissue media requires biological identification
            if act_media == "Tissue":
                bio_desc = result.find(tag("BiologicalResultDescription"))
                if bio_desc is None:
                    violations.append(
                        {
                            "category": "business_rule",
                            "element": "BiologicalResultDescription",
                            "detail": "Tissue activity Result missing BiologicalResultDescription",
                        }
                    )
                else:
                    tissue_name = get_text(bio_desc, "SampleTissueAnatomyName")
                    taxon_name = get_text(bio_desc, "SubjectTaxonomicName")
                    if not tissue_name:
                        violations.append(
                            {
                                "category": "business_rule",
                                "element": "SampleTissueAnatomyName",
                                "detail": "Tissue activity Result missing non-empty SampleTissueAnatomyName",
                            }
                        )
                    if not taxon_name:
                        violations.append(
                            {
                                "category": "business_rule",
                                "element": "SubjectTaxonomicName",
                                "detail": "Tissue activity Result missing non-empty SubjectTaxonomicName",
                            }
                        )

            # BR-005: Group Summary requires count
            bio_desc = result.find(tag("BiologicalResultDescription"))
            if bio_desc is not None:
                bio_intent = get_text(bio_desc, "BiologicalIntentName")
                if bio_intent == "Group Summary":
                    group_count = get_text(bio_desc, "GroupSummaryCount")
                    if not group_count:
                        violations.append(
                            {
                                "category": "business_rule",
                                "element": "GroupSummaryCount",
                                "detail": "Group Summary requires non-empty GroupSummaryCount",
                            }
                        )

    # ActivityGroups
    for ag in org.findall(tag("ActivityGroup")):
        for ag_act_ref in ag.findall(tag("ActivityIdentifier")):
            ref_act_id = ag_act_ref.text.strip() if ag_act_ref.text else None
            if ref_act_id and ref_act_id not in activity_ids:
                violations.append(
                    {
                        "category": "referential_integrity",
                        "element": "ActivityIdentifier",
                        "detail": f'ActivityGroup references undefined Activity "{ref_act_id}"',
                    }
                )

    return violations


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Extract constraints from XSD
    constraints = extract_constraints(SCHEMAS_DIR)
    with open(CONSTRAINTS_OUT, "w") as f:
        json.dump(constraints, f, indent=2, sort_keys=True)
    print(f"Extracted {len(constraints)} field constraints from XSD schemas", file=sys.stderr)

    # Load domain values
    domains = load_domain_values(DOMAINS_DIR)

    # Validate each submission
    for filename in sorted(os.listdir(SUBMISSIONS_DIR)):
        if not filename.endswith(".xml"):
            continue

        xml_path = os.path.join(SUBMISSIONS_DIR, filename)

        # Structural validation against XSD schema
        schema_valid = run_schema_validation(SCHEMA_ROOT, xml_path)

        # Semantic validation
        violations = validate_xml(xml_path, constraints, domains)

        # Build category counts
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
        print(f"  {filename}: {status} (schema={schema_valid}, errors={total_errors})", file=sys.stderr)

    print("Analysis complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
