
"""
Test harness for FHIRPath evaluator conformance tests.
Parses the HL7 FHIRPath test suite XML (tests-fhir-r4.xml),
extracts tests from specified groups, runs each through the
solver's evaluate.js, and compares results.
"""

import json
import subprocess
import pytest
from lxml import etree


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEST_SUITE_PATH = "/data/tests-fhir-r4.xml"
EVALUATOR_CMD = ["node", "/app/evaluate.js"]
RESOURCE_DIR = "/data/resources"

TARGET_GROUPS = [
    "testEquality",
    "testNEquality",
    "testEquivalent",
    "testNotEquivalent",
    "testBooleanLogicAnd",
    "testBooleanLogicOr",
    "testBooleanLogicXOr",
    "testBooleanImplies",
    "testQuantity",
]

# Quantity tests 9-11 require full UCUM unit algebra (multiplication/division
# of derived units) which is out of scope.  Exclude them.
EXCLUDED_TESTS = {"testQuantity9", "testQuantity10", "testQuantity11"}


# ---------------------------------------------------------------------------
# Parse the test suite
# ---------------------------------------------------------------------------

def _parse_test_suite():
    """Return list of (group_name, test_name, test_element) tuples."""
    tree = etree.parse(TEST_SUITE_PATH)
    root = tree.getroot()
    cases = []
    for group in root.iter("group"):
        gname = group.get("name")
        if gname not in TARGET_GROUPS:
            continue
        idx = 0
        for test in group.iter("test"):
            tname = test.get("name", f"{gname}_{idx}")
            if tname in EXCLUDED_TESTS:
                continue
            cases.append((gname, tname, idx, test))
            idx += 1
    return cases


RAW_CASES = _parse_test_suite()


def _extract_expected(test_elem):
    """Return (is_invalid, expected_outputs).

    is_invalid: None or string like 'syntax'/'semantic'/'execution'
    expected_outputs: list of (type, value) tuples, or [] for empty result
    """
    expr_elem = test_elem.find("expression")
    invalid = expr_elem.get("invalid") if expr_elem is not None else None

    outputs = []
    for out in test_elem.findall("output"):
        otype = out.get("type")
        ovalue = out.text if out.text else ""
        outputs.append((otype, ovalue.strip()))

    return invalid, outputs


# ---------------------------------------------------------------------------
# Build pytest parameters
# ---------------------------------------------------------------------------

def _make_id(gname, tname, idx):
    return f"{gname}::{tname}[{idx}]"


PARAMS = []
for gname, tname, idx, elem in RAW_CASES:
    expr_elem = elem.find("expression")
    expression = ""
    if expr_elem is not None:
        expression = expr_elem.text or ""

    inputfile = elem.get("inputfile", "patient-example.xml")
    invalid, expected = _extract_expected(elem)

    PARAMS.append(pytest.param(
        inputfile, expression, invalid, expected,
        id=_make_id(gname, tname, idx),
    ))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inputfile,expression,invalid,expected", PARAMS)
def test_fhirpath_conformance(inputfile, expression, invalid, expected):
    resource_path = f"{RESOURCE_DIR}/{inputfile}"

    result = subprocess.run(
        EVALUATOR_CMD + [resource_path, expression],
        capture_output=True, text=True, timeout=30,
        cwd="/app",
    )

    stdout = result.stdout.strip()
    assert stdout, f"evaluate.js produced no output for expression: {expression!r}"

    data = json.loads(stdout)

    if invalid:
        # The expression is expected to be invalid / cause a runtime error.
        assert "error" in data, (
            f"Expected error for invalid ({invalid}) expression, "
            f"got: {data}"
        )
        return

    # Valid expression -- check results.
    assert "results" in data, f"Missing 'results' key in output: {data}"
    results = data["results"]

    if not expected:
        # Expected empty collection.
        assert len(results) == 0, (
            f"Expected empty collection, got {len(results)} results: {results}"
        )
        return

    assert len(results) == len(expected), (
        f"Expected {len(expected)} results but got {len(results)}.\n"
        f"  Expected: {expected}\n"
        f"  Got:      {results}"
    )

    for i, ((etype, evalue), actual) in enumerate(zip(expected, results)):
        atype = actual.get("type", "")
        avalue = actual.get("value", "")

        # Type matching -- be flexible with case
        assert atype.lower() == etype.lower(), (
            f"Result[{i}] type mismatch: expected {etype!r}, got {atype!r}"
        )

        # Value matching
        assert str(avalue).strip() == str(evalue).strip(), (
            f"Result[{i}] value mismatch: expected {evalue!r}, got {avalue!r}"
        )
