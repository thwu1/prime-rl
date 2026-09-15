#!/usr/bin/env python3
"""C-CDA Vocabulary Conformance Analyzer.

Parses ONC-style XPath validation rules, evaluates them against a C-CDA R2.1
clinical document, reports vocabulary violations, and produces a corrected copy.
"""

import json
from lxml import etree


def parse_rules(rules_path):
    """Parse the vocabularyValidationConfigurations XML to extract rules and
    the namespace map needed for XPath evaluation."""
    tree = etree.parse(rules_path)
    root = tree.getroot()

    # Build namespace map from <namespaces> section
    nsmap = {}
    for ns_elem in root.findall(".//namespaces/namespace"):
        nsmap[ns_elem.get("prefix")] = ns_elem.get("uri")

    # Extract each rule
    rules = []
    for expr in root.findall(".//expressions/expression"):
        validator = expr.find("validator")
        rule = {
            "id": expr.get("id"),
            "xpath": expr.get("xpathExpression"),
            "validator_type": validator.findtext("name"),
            "severity": validator.find(
                "validationResultSeverityLevels/codeSeverityLevel"
            ).text,
            "valueset_oid": validator.findtext("allowedValuesetOids"),
        }
        rules.append(rule)

    return rules, nsmap


def load_valuesets(path):
    with open(path) as f:
        return json.load(f)


def evaluate_rules(doc_path, rules, nsmap, valuesets):
    """Return a list of violation dicts."""
    tree = etree.parse(doc_path)
    violations = []

    for rule in rules:
        elements = tree.xpath(rule["xpath"], namespaces=nsmap)
        if not elements:
            continue

        vs = valuesets.get(rule["valueset_oid"])
        if vs is None:
            continue

        valid_codes = {c["code"] for c in vs["codes"]}

        for elem in elements:
            if rule["validator_type"] == "UnitValidator":
                actual = elem.get("unit")
            else:
                actual = elem.get("code")

            if actual is None:
                continue

            if actual not in valid_codes:
                violations.append(
                    {
                        "rule_id": rule["id"],
                        "severity": rule["severity"],
                        "actual_code": actual,
                        "valueset_oid": rule["valueset_oid"],
                    }
                )

    return violations


def fix_document(doc_path, output_path, rules, nsmap, valuesets, violation_ids):
    """Write a corrected copy of the document, replacing each violating
    code/unit with the alphabetically first valid value from the value set."""
    tree = etree.parse(doc_path)

    for rule in rules:
        if rule["id"] not in violation_ids:
            continue

        vs = valuesets.get(rule["valueset_oid"])
        if vs is None:
            continue
        sorted_codes = sorted(c["code"] for c in vs["codes"])
        if not sorted_codes:
            continue
        replacement = sorted_codes[0]

        attr = "unit" if rule["validator_type"] == "UnitValidator" else "code"

        for elem in tree.xpath(rule["xpath"], namespaces=nsmap):
            current = elem.get(attr)
            if current is not None and current not in {c["code"] for c in vs["codes"]}:
                elem.set(attr, replacement)

    tree.write(output_path, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def main():
    rules, nsmap = parse_rules("/app/validation_rules.xml")
    valuesets = load_valuesets("/app/valuesets.json")
    violations = evaluate_rules("/app/patient_record.xml", rules, nsmap, valuesets)

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

    violation_ids = {v["rule_id"] for v in violations}
    fix_document(
        "/app/patient_record.xml",
        "/app/fixed_record.xml",
        rules,
        nsmap,
        valuesets,
        violation_ids,
    )


if __name__ == "__main__":
    main()
