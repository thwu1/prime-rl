
import json
import os
import pytest

RESULTS_PATH = "/app/results/audit_report.json"

# Expected results for all 20 routes
EXPECTED = {
    1:  {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    2:  {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    3:  {"rov": "Invalid",  "aspa": "Valid",   "policy": "REJECT"},
    4:  {"rov": "Invalid",  "aspa": "Valid",   "policy": "REJECT"},
    5:  {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    6:  {"rov": "Valid",    "aspa": "Unknown", "policy": "ACCEPT"},
    7:  {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    8:  {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    9:  {"rov": "Valid",    "aspa": "Invalid", "policy": "REJECT"},
    10: {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    11: {"rov": "Valid",    "aspa": "Invalid", "policy": "REJECT"},
    12: {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    13: {"rov": "Valid",    "aspa": "Unknown", "policy": "ACCEPT"},
    14: {"rov": "Invalid",  "aspa": "Valid",   "policy": "REJECT"},
    15: {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    16: {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    17: {"rov": "Valid",    "aspa": "Valid",   "policy": "ACCEPT"},
    18: {"rov": "Invalid",  "aspa": "Valid",   "policy": "REJECT"},
    19: {"rov": "NotFound", "aspa": "Unknown", "policy": "ACCEPT"},
    20: {"rov": "Invalid",  "aspa": "Unknown", "policy": "REJECT"},
}


@pytest.fixture(scope="module")
def report():
    """Load the audit report."""
    assert os.path.exists(RESULTS_PATH), (
        f"Audit report not found at {RESULTS_PATH}"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def validations(report):
    """Extract route validations as lookup by route_id."""
    assert "route_validations" in report, "Report must contain 'route_validations'"
    results = {}
    for entry in report["route_validations"]:
        assert "route_id" in entry, f"Each validation must have 'route_id': {entry}"
        results[entry["route_id"]] = entry
    return results


# --- ROA Verification Tests ---

def test_roa_verification_present(report):
    """Report must include ROA verification summary."""
    assert "roa_verification" in report, "Report must contain 'roa_verification'"
    rv = report["roa_verification"]
    for key in ("total", "valid", "invalid", "invalid_files"):
        assert key in rv, f"roa_verification missing '{key}'"


def test_roa_total_count(report):
    """All 11 CMS files must be examined."""
    assert report["roa_verification"]["total"] == 11


def test_roa_valid_count(report):
    """Exactly 10 ROAs should pass chain-of-trust verification."""
    assert report["roa_verification"]["valid"] == 10


def test_roa_invalid_count(report):
    """Exactly 1 ROA should fail verification (rogue signer)."""
    assert report["roa_verification"]["invalid"] == 1


def test_roa_invalid_file_identified(report):
    """The rogue ROA file must be identified."""
    inv = report["roa_verification"]["invalid_files"]
    assert len(inv) == 1
    assert "roa_11" in inv[0], f"Expected roa_11 in invalid list, got {inv}"


# --- Route Presence and Schema ---

def test_all_routes_present(validations):
    """All 20 routes must have results."""
    for rid in range(1, 21):
        assert rid in validations, f"Missing result for route_id {rid}"


def test_result_schema(validations):
    """Each result must have proper fields and values."""
    for rid in range(1, 21):
        r = validations[rid]
        assert r["rov_status"] in ("Valid", "Invalid", "NotFound"), (
            f"Route {rid}: rov_status={r['rov_status']}"
        )
        assert r["aspa_status"] in ("Valid", "Invalid", "Unknown"), (
            f"Route {rid}: aspa_status={r['aspa_status']}"
        )
        assert r["policy"] in ("ACCEPT", "REJECT"), (
            f"Route {rid}: policy={r['policy']}"
        )


# --- ROV Tests ---

@pytest.mark.parametrize("route_id", [1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17])
def test_rov_valid(validations, route_id):
    """Routes covered by a valid ROA with matching origin and prefix length."""
    assert validations[route_id]["rov_status"] == "Valid", (
        f"Route {route_id}: expected ROV=Valid, got {validations[route_id]['rov_status']}"
    )


@pytest.mark.parametrize("route_id", [3, 4, 14, 18, 20])
def test_rov_invalid(validations, route_id):
    """Routes covered by ROA but wrong origin or prefix exceeds maxLength."""
    assert validations[route_id]["rov_status"] == "Invalid", (
        f"Route {route_id}: expected ROV=Invalid, got {validations[route_id]['rov_status']}"
    )


def test_rov_notfound_rogue_rejected(validations):
    """Route 19: only covered by rogue ROA which must be rejected -> NotFound."""
    assert validations[19]["rov_status"] == "NotFound", (
        f"Route 19: expected ROV=NotFound (rogue ROA rejected), "
        f"got {validations[19]['rov_status']}. "
        "CMS chain-of-trust verification may not be working correctly."
    )


# --- ASPA Tests ---

@pytest.mark.parametrize("route_id", [1, 2, 3, 4, 5, 7, 8, 10, 12, 14, 15, 16, 17, 18])
def test_aspa_valid(validations, route_id):
    """Routes with valid upstream paths or single-AS paths."""
    assert validations[route_id]["aspa_status"] == "Valid", (
        f"Route {route_id}: expected ASPA=Valid, got {validations[route_id]['aspa_status']}"
    )


@pytest.mark.parametrize("route_id", [9, 11])
def test_aspa_invalid(validations, route_id):
    """Routes with ASPA-detected route leaks (unauthorized transit)."""
    assert validations[route_id]["aspa_status"] == "Invalid", (
        f"Route {route_id}: expected ASPA=Invalid, got {validations[route_id]['aspa_status']}"
    )


@pytest.mark.parametrize("route_id", [6, 13, 19, 20])
def test_aspa_unknown(validations, route_id):
    """Routes where some ASes lack ASPA records."""
    assert validations[route_id]["aspa_status"] == "Unknown", (
        f"Route {route_id}: expected ASPA=Unknown, got {validations[route_id]['aspa_status']}"
    )


# --- Policy Tests ---

@pytest.mark.parametrize("route_id", [1, 2, 5, 6, 7, 8, 10, 12, 13, 15, 16, 17, 19])
def test_policy_accept(validations, route_id):
    """Routes that should be accepted."""
    assert validations[route_id]["policy"] == "ACCEPT", (
        f"Route {route_id}: expected ACCEPT, got {validations[route_id]['policy']}"
    )


@pytest.mark.parametrize("route_id", [3, 4, 9, 11, 14, 18, 20])
def test_policy_reject(validations, route_id):
    """Routes that should be rejected (ROV=Invalid or ASPA=Invalid)."""
    assert validations[route_id]["policy"] == "REJECT", (
        f"Route {route_id}: expected REJECT, got {validations[route_id]['policy']}"
    )


# --- Edge Case Tests ---

def test_prepending_normalized(validations):
    """Route 5: AS path [64512, 64512, 64512, 64500] must be deduplicated for ASPA."""
    r = validations[5]
    assert r["rov_status"] == "Valid" and r["aspa_status"] == "Valid", (
        f"Route 5 (prepending): expected Valid/Valid, got {r['rov_status']}/{r['aspa_status']}"
    )


def test_long_prepending_valid(validations):
    """Route 17: [64711, 64711, 64711, 64700] after dedup is [64711, 64700] -> valid."""
    r = validations[17]
    assert r["aspa_status"] == "Valid", (
        f"Route 17 (prepending): expected ASPA=Valid, got {r['aspa_status']}"
    )


def test_maxlength_violation(validations):
    """Route 4: prefix /24 exceeds ROA maxLength of /16."""
    assert validations[4]["rov_status"] == "Invalid"


def test_broad_roa_maxlength_trap(validations):
    """Route 14: 10.5.0.0/16 covered by ROA 10.0.0.0/8 maxLen=8, but /16 > 8 -> Invalid."""
    assert validations[14]["rov_status"] == "Invalid"


def test_ipv6_validation(validations):
    """IPv6 routes (12, 15) validate correctly."""
    for rid in [12, 15]:
        r = validations[rid]
        assert r["rov_status"] == "Valid" and r["aspa_status"] == "Valid", (
            f"Route {rid} (IPv6): expected Valid/Valid, got {r['rov_status']}/{r['aspa_status']}"
        )


def test_rov_aspa_independence(validations):
    """Route 18: ROV=Invalid but ASPA=Valid — validations must be independent."""
    r = validations[18]
    assert r["rov_status"] == "Invalid" and r["aspa_status"] == "Valid", (
        f"Route 18: expected Invalid/Valid, got {r['rov_status']}/{r['aspa_status']}"
    )


def test_route_leak_detection(validations):
    """Route 9: unauthorized transit AS 64513 between 64710 and 64700."""
    r = validations[9]
    assert r["aspa_status"] == "Invalid", (
        f"Route 9 (route leak): expected ASPA=Invalid, got {r['aspa_status']}"
    )


def test_multi_hop_valid_path(validations):
    """Route 10: [64720, 64710, 64700] — each hop is customer-to-provider."""
    r = validations[10]
    assert r["rov_status"] == "Valid" and r["aspa_status"] == "Valid", (
        f"Route 10 (multi-hop): expected Valid/Valid, got {r['rov_status']}/{r['aspa_status']}"
    )


def test_complete_validation_set(validations):
    """Verify all 20 routes match expected results exactly."""
    mismatches = []
    for rid in range(1, 21):
        r = validations[rid]
        exp = EXPECTED[rid]
        for field, key in [("rov", "rov_status"), ("aspa", "aspa_status"), ("policy", "policy")]:
            if r[key] != exp[field]:
                mismatches.append(
                    f"Route {rid}.{field}: expected {exp[field]}, got {r[key]}"
                )
    assert not mismatches, "Mismatches found:\n" + "\n".join(mismatches)
