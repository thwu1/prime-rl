#!/usr/bin/env python3
"""C-CDA Vocabulary Conformance Validator.

Evaluates ONC-style XPath vocabulary validation rules against a C-CDA R2.1
clinical document and produces a structured violation report.
"""

import json
import sys
from lxml import etree


def parse_rules(rules_path):
    """Parse vocabularyValidationConfigurations XML to extract rules
    and the namespace map needed for XPath evaluation."""
    tree = etree.parse(rules_path)
    root = tree.getroot()

    # Standard HL7 v3 namespace for XPath evaluation
    nsmap = {"v3": "urn:hl7-org:v3"}

    rules = []
    for expr in root.findall(".//expressions/expression"):
        validator = expr.find("validator")
        sev_elem = validator.find(
            "validationResultSeverityLevels/codeSeverityLevel"
        )
        rule = {
            "id": expr.get("id"),
            "xpath": expr.get("xpathExpression"),
            "validator_type": validator.findtext("name"),
            "severity": sev_elem.text if sev_elem is not None else "MAY",
            "valueset_oid": validator.findtext("allowedValuesetOids"),
        }
        rules.append(rule)

    return rules, nsmap


def load_valuesets(path):
    """Load value set definitions from JSON file."""
    with open(path) as f:
        return json.load(f)


def get_valid_codes(valuesets, oid):
    """Get the set of valid codes for a given value set OID."""
    vs = valuesets.get(oid)
    if vs is None:
        return set()
    return {c["code"] for c in vs.get("codes", [])}


def evaluate_rules(doc_path, rules, nsmap, valuesets):
    """Evaluate all validation rules against the clinical document
    and return a list of violation dicts."""
    tree = etree.parse(doc_path)
    violations = []

    for rule in rules:
        try:
            elements = tree.xpath(rule["xpath"], namespaces=nsmap)
        except Exception:
            # Skip rules whose XPath cannot be evaluated
            continue

        if not elements:
            continue

        valid_codes = get_valid_codes(valuesets, rule["valueset_oid"])
        if not valid_codes:
            continue

        for elem in elements:
            if rule["validator_type"] == "UnitValidator":
                actual = elem.get("unit")
            else:
                actual = elem.get("code")

            if actual is None:
                continue

            if actual not in valid_codes:
                violations.append({
                    "rule_id": rule["id"],
                    "severity": rule["severity"],
                    "actual_code": actual,
                    "valueset_oid": rule["valueset_oid"],
                })

    return violations


def main():
    rules, nsmap = parse_rules("/app/validation_rules.xml")
    valuesets = load_valuesets("/app/valuesets.json")
    violations = evaluate_rules(
        "/app/patient_record.xml", rules, nsmap, valuesets
    )

    shall = sum(1 for v in violations if v["severity"] == "SHALL")
    should = sum(1 for v in violations if v["severity"] == "SHOULD")

    report = {
        "total_rules": len(rules),
        "total_violations": len(violations),
        "shall_violations": shall,
        "should_violations": should,
        "violations": violations,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Validation complete: {len(rules)} rules, {len(violations)} violations")


if __name__ == "__main__":
    main()
