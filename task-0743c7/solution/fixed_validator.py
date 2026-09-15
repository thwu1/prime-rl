#!/usr/bin/env python3
"""Fixed C-CDA Vocabulary Conformance Validator.

Corrects all defects in the original validator:
1. Reads namespace map from config XML (not hardcoded v3-only)
2. Loads rules from all expression sections including supplementaryExpressions
3. Expands value set 'includes' references transitively with cycle detection
4. Handles CodeSystemCodeValidator by checking @codeSystem attribute
5. Parses and applies CWE/CNE binding type semantics — CWE allows codes
   from approved code systems as valid extensions
"""

import json
from lxml import etree


def parse_rules(rules_path):
    """Parse vocabularyValidationConfigurations XML to extract rules
    and the namespace map needed for XPath evaluation."""
    tree = etree.parse(rules_path)
    root = tree.getroot()

    # FIX #1: Read namespace map from config file instead of hardcoding
    nsmap = {}
    for ns_elem in root.findall(".//namespaces/namespace"):
        nsmap[ns_elem.get("prefix")] = ns_elem.get("uri")

    rules = []
    # FIX #2: Load rules from ALL expression sections
    for section_tag in ["expressions", "supplementaryExpressions"]:
        for expr in root.findall(f".//{section_tag}/expression"):
            validator = expr.find("validator")
            sev_elem = validator.find(
                "validationResultSeverityLevels/codeSeverityLevel"
            )
            severity_text = sev_elem.text if sev_elem is not None else "MAY"
            if not severity_text or not severity_text.strip():
                severity_text = "MAY"
            # FIX #5: Parse binding type (CNE or CWE)
            binding_type = validator.findtext("bindingType") or "CNE"
            rule = {
                "id": expr.get("id"),
                "xpath": expr.get("xpathExpression"),
                "validator_type": validator.findtext("name"),
                "severity": severity_text.strip(),
                "valueset_oid": validator.findtext("allowedValuesetOids"),
                "binding_type": binding_type.strip(),
            }
            rules.append(rule)

    return rules, nsmap


def load_valuesets(path):
    """Load value set definitions from JSON file."""
    with open(path) as f:
        return json.load(f)


def get_valid_codes(valuesets, oid, visited=None):
    """Get the set of valid codes for a given value set OID,
    expanding 'includes' references transitively.
    FIX #3: Handle hierarchical value set composition with cycle detection."""
    if visited is None:
        visited = set()
    if oid in visited:
        return set()
    visited.add(oid)

    vs = valuesets.get(oid)
    if vs is None:
        return set()
    codes = {c["code"] for c in vs.get("codes", [])}
    for included_oid in vs.get("includes", []):
        codes |= get_valid_codes(valuesets, included_oid, visited)
    return codes


def evaluate_rules(doc_path, rules, nsmap, valuesets):
    """Evaluate all validation rules against the clinical document
    and return a list of violation dicts."""
    tree = etree.parse(doc_path)
    violations = []

    for rule in rules:
        try:
            elements = tree.xpath(rule["xpath"], namespaces=nsmap)
        except etree.XPathError:
            continue

        if not elements:
            continue

        valid_codes = get_valid_codes(valuesets, rule["valueset_oid"])
        if not valid_codes:
            continue

        for elem in elements:
            if rule["validator_type"] == "UnitValidator":
                actual = elem.get("unit")
            elif rule["validator_type"] == "CodeSystemCodeValidator":
                # FIX #4: CodeSystemCodeValidator checks @codeSystem, not @code
                actual = elem.get("codeSystem")
            else:
                actual = elem.get("code")

            if actual is None:
                continue

            if actual not in valid_codes:
                # FIX #5: CWE binding — check if code is from approved code system
                if rule.get("binding_type") == "CWE":
                    vs_def = valuesets.get(rule["valueset_oid"])
                    if vs_def:
                        approved = vs_def.get("approvedCodeSystems", [])
                        elem_cs = elem.get("codeSystem")
                        if elem_cs and elem_cs in approved:
                            continue  # Valid CWE extension, not a violation

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


if __name__ == "__main__":
    main()
