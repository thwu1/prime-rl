#!/usr/bin/env python3
"""
Reference solution for the C-CDA Multi-Layer Conformance Engine task.

Parses validation_rules.xml using stdlib ElementTree, implements six
validator types, evaluates XPath rules against document.xml using lxml,
generates report.json with violations and conformance scorecard, and
produces fixed_document.xml.
"""


import json
import os
import sys
from xml.etree import ElementTree as StdlibET

from lxml import etree

# Namespace constants
V3_NS = "urn:hl7-org:v3"
SDTC_NS = "urn:hl7-org:sdtc"
CFG_NS = "http://www.SITE.org/CCDAValidator"

DOC_XPATH_NS = {"v3": V3_NS, "sdtc": SDTC_NS}

VALUESET_DIR = "/app/valuesets"


def load_valueset(oid):
    """Load a valueset JSON file and return the set of valid codes."""
    path = os.path.join(VALUESET_DIR, f"{oid}.json")
    if not os.path.exists(path):
        print(f"  WARNING: valueset file not found: {path}", file=sys.stderr)
        return None
    with open(path) as f:
        data = json.load(f)
    return {entry["code"] for entry in data["codes"]}


def parse_rules(config_path):
    """Parse validation_rules.xml using stdlib ElementTree for robustness."""
    tree = StdlibET.parse(config_path)
    root = tree.getroot()
    rules = []

    for expr_elem in root.findall(f"{{{CFG_NS}}}expression"):
        xpath_str = expr_elem.get("xpathExpression")
        if not xpath_str:
            continue

        for val_elem in expr_elem.findall(f"{{{CFG_NS}}}validator"):
            name_elem = val_elem.find(f"{{{CFG_NS}}}name")
            sev_elem = val_elem.find(
                f"{{{CFG_NS}}}validationResultSeverityLevels/"
                f"{{{CFG_NS}}}codeSeverityLevel"
            )
            oid_elem = val_elem.find(f"{{{CFG_NS}}}allowedValuesetOids")

            if name_elem is None or not (name_elem.text or "").strip():
                continue

            name = name_elem.text.strip()
            severity = (
                sev_elem.text.strip()
                if sev_elem is not None and sev_elem.text
                else "INFO"
            )
            oids = (
                oid_elem.text.strip().split("|")
                if oid_elem is not None and oid_elem.text
                else []
            )

            rules.append({
                "xpath": xpath_str,
                "validator_type": name,
                "severity": severity,
                "oids": oids,
            })

    return rules


def check_node(node, rule):
    """
    Check a single matched XML node against a validation rule.
    Returns a violation dict if invalid, or None if the node passes.
    """
    vtype = rule["validator_type"]

    if vtype == "ValueSetCodeValidator":
        code = node.get("code")
        if code is None:
            return None
        code = code.strip()
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and code in valid_codes:
                return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": code,
        }

    elif vtype == "NodeCodeSystemMatchesConfiguredCodeSystemValidator":
        cs = node.get("codeSystem")
        if cs is None:
            return None
        cs = cs.strip()
        expected = rule["oids"][0].strip()
        if cs == expected:
            return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": cs,
        }

    elif vtype == "LanguageCodeNodeLanguageCodeValuesetValidator":
        code = node.get("code")
        if code is None:
            return None
        code = code.strip()
        lang = code.split("-")[0] if "-" in code else code
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and lang in valid_codes:
                return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": lang,
        }

    elif vtype == "LanguageCodeNodeCountryCodeValuesetValidator":
        code = node.get("code")
        if code is None:
            return None
        code = code.strip()
        if "-" not in code:
            return None
        country = code.split("-", 1)[1]
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and country in valid_codes:
                return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": country,
        }

    elif vtype == "TextNodeValidator":
        text = (node.text or "").strip()
        if not text:
            return None
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and text in valid_codes:
                return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": text,
        }

    elif vtype == "ClassCodeValidator":
        cc = node.get("classCode")
        if cc is None:
            return None
        cc = cc.strip()
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and cc in valid_codes:
                return None
        return {
            "validator_type": vtype,
            "severity": rule["severity"],
            "found_value": cc,
        }

    print(f"  WARNING: unknown validator type: {vtype}", file=sys.stderr)
    return None


def validate_document(doc_tree, rules):
    """Evaluate all rules against the document and collect violations."""
    violations = []
    for i, rule in enumerate(rules):
        try:
            nodes = doc_tree.xpath(rule["xpath"], namespaces=DOC_XPATH_NS)
        except etree.XPathError as e:
            print(f"  XPath error on rule {i+1}: {e}", file=sys.stderr)
            continue
        for node in nodes:
            violation = check_node(node, rule)
            if violation is not None:
                violations.append(violation)
    return violations


def fix_node(node, rule):
    """Fix a single node if it violates the rule."""
    vtype = rule["validator_type"]

    if vtype == "ValueSetCodeValidator":
        code = node.get("code")
        if code is None:
            return
        code = code.strip()
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and code in valid_codes:
                return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes:
                node.set("code", sorted(valid_codes)[0])
                return

    elif vtype == "NodeCodeSystemMatchesConfiguredCodeSystemValidator":
        cs = node.get("codeSystem")
        if cs is None:
            return
        expected = rule["oids"][0].strip()
        if cs.strip() != expected:
            node.set("codeSystem", expected)

    elif vtype == "LanguageCodeNodeLanguageCodeValuesetValidator":
        code = node.get("code")
        if code is None:
            return
        code = code.strip()
        lang = code.split("-")[0] if "-" in code else code
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and lang in valid_codes:
                return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes:
                new_lang = sorted(valid_codes)[0]
                if "-" in code:
                    country = code.split("-", 1)[1]
                    node.set("code", f"{new_lang}-{country}")
                else:
                    node.set("code", new_lang)
                return

    elif vtype == "LanguageCodeNodeCountryCodeValuesetValidator":
        code = node.get("code")
        if code is None or "-" not in code.strip():
            return
        code = code.strip()
        country = code.split("-", 1)[1]
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and country in valid_codes:
                return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes:
                new_country = sorted(valid_codes)[0]
                lang = code.split("-")[0]
                node.set("code", f"{lang}-{new_country}")
                return

    elif vtype == "TextNodeValidator":
        text = (node.text or "").strip()
        if not text:
            return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and text in valid_codes:
                return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes:
                node.text = sorted(valid_codes)[0]
                return

    elif vtype == "ClassCodeValidator":
        cc = node.get("classCode")
        if cc is None:
            return
        cc = cc.strip()
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes is not None and cc in valid_codes:
                return
        for oid in rule["oids"]:
            valid_codes = load_valueset(oid)
            if valid_codes:
                node.set("classCode", sorted(valid_codes)[0])
                return


def fix_document(doc_tree, rules):
    """Apply all rules to fix violations in the document tree (in-place)."""
    for rule in rules:
        try:
            nodes = doc_tree.xpath(rule["xpath"], namespaces=DOC_XPATH_NS)
        except etree.XPathError:
            continue
        for node in nodes:
            fix_node(node, rule)
    return doc_tree


def main():
    config_path = "/app/validation_rules.xml"
    doc_path = "/app/document.xml"
    report_path = "/app/report.json"
    fixed_path = "/app/fixed_document.xml"

    # Parse rules using stdlib ElementTree (robust namespace handling)
    rules = parse_rules(config_path)
    print(f"Loaded {len(rules)} validation rules")
    for i, r in enumerate(rules):
        print(f"  R{i+1}: {r['validator_type']} ({r['severity']})")

    # Validate original document using lxml (supports ancestor:: axis)
    doc_tree = etree.parse(doc_path)
    violations = validate_document(doc_tree, rules)

    shall_count = sum(1 for v in violations if v["severity"] == "SHALL")
    should_count = sum(1 for v in violations if v["severity"] == "SHOULD")
    conformance_score = max(0.0, 1.0 - (0.05 * shall_count + 0.02 * should_count))

    report = {
        "violations": violations,
        "summary": {
            "shall_count": shall_count,
            "should_count": should_count,
            "conformance_score": round(conformance_score, 4),
        },
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {len(violations)} violations "
          f"({shall_count} SHALL, {should_count} SHOULD), "
          f"conformance score: {conformance_score:.4f}")

    # Print each violation for debugging
    for v in violations:
        print(f"  {v['severity']}: {v['found_value']} ({v['validator_type']})")

    # Fix document
    fix_tree = etree.parse(doc_path)
    fix_document(fix_tree, rules)
    fix_tree.write(fixed_path, xml_declaration=True, encoding="UTF-8",
                   pretty_print=True)
    print(f"Fixed document written to {fixed_path}")


if __name__ == "__main__":
    main()
