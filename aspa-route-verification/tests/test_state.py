
import json
import os
import pytest

AUDIT_PATH = "/app/audit.json"

# ============================================================
# EXPECTED ANSWERS
# ============================================================

EXPECTED_ERRORS = [
    {"customer_asn": 64512, "unauthorized_providers": [64500], "missing_providers": []},
    {"customer_asn": 64522, "unauthorized_providers": [64510], "missing_providers": [64511]},
    {"customer_asn": 64531, "unauthorized_providers": [64511], "missing_providers": []},
]

EXPECTED_CORRECTED_ASPA = {
    "64500": [], "64501": [],
    "64510": [64500], "64511": [64500, 64501], "64512": [64501],
    "64520": [64510], "64521": [64510, 64511],
    "64522": [64511, 64512], "64523": [64512],
    "64530": [64520], "64531": [64520, 64521],
    "64532": [64521, 64522], "64533": [64522, 64523],
    "64534": [64523],
}

EXPECTED_ROUTES = {
    "OBS-001": ("upstream", "Unknown", None),
    "OBS-002": ("upstream", "Valid", None),
    "OBS-003": ("upstream", "Valid", None),
    "OBS-004": ("upstream", "Invalid", 64520),
    "OBS-005": ("upstream", "Valid", None),
    "OBS-006": ("upstream", "Unknown", None),
    "OBS-007": ("upstream", "Valid", None),
    "OBS-008": ("upstream", "Valid", None),
    "OBS-009": ("upstream", "Unknown", None),
    "OBS-010": ("upstream", "Valid", None),
    "OBS-011": ("upstream", "Invalid", 64510),
    "OBS-012": ("upstream", "Valid", None),
    "OBS-013": ("upstream", "Valid", None),
    "OBS-014": ("upstream", "Unknown", None),
    "OBS-015": ("upstream", "Invalid", 64523),
    "OBS-016": ("downstream", "Valid", None),
    "OBS-017": ("downstream", "Valid", None),
    "OBS-018": ("downstream", "Invalid", 64520),
    "OBS-019": ("downstream", "Unknown", None),
    "OBS-020": ("downstream", "Invalid", 64510),
    "OBS-021": ("downstream", "Invalid", 64530),
    "OBS-022": ("downstream", "Valid", None),
    "OBS-023": ("downstream", "Valid", None),
    "OBS-024": ("downstream", "Invalid", 64523),
    "OBS-025": ("downstream", "Valid", None),
    "OBS-026": ("upstream", "Valid", None),
    "OBS-027": ("upstream", "Valid", None),
    "OBS-028": ("upstream", "Valid", None),
    "OBS-029": ("upstream", "Unverifiable", None),
    "OBS-030": ("downstream", "Unverifiable", None),
}

EXPECTED_DEPLOY_ASNS = {64544, 64540, 64542, 64543}
EXPECTED_DEPLOY_FIRST = 64544


@pytest.fixture(scope="module")
def audit():
    assert os.path.exists(AUDIT_PATH), f"Audit file not found at {AUDIT_PATH}"
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    for key in ["erroneous_objects", "corrected_aspa", "route_analysis",
                "deployment_recommendation"]:
        assert key in data, f"Top-level key '{key}' missing from audit.json"
    return data


# ============================================================
# ERROR DETECTION TESTS
# ============================================================

class TestErrorDetection:
    def test_error_count(self, audit):
        assert len(audit["erroneous_objects"]) == 3, \
            f"Expected 3 erroneous objects, got {len(audit['erroneous_objects'])}"

    @pytest.mark.parametrize("expected", EXPECTED_ERRORS,
                             ids=[f"AS{e['customer_asn']}" for e in EXPECTED_ERRORS])
    def test_error_details(self, audit, expected):
        found = [o for o in audit["erroneous_objects"]
                 if o["customer_asn"] == expected["customer_asn"]]
        assert len(found) == 1, \
            f"AS{expected['customer_asn']} not found or duplicated in erroneous_objects"
        obj = found[0]
        assert sorted(obj["unauthorized_providers"]) == sorted(expected["unauthorized_providers"]), \
            f"AS{expected['customer_asn']}: unauthorized mismatch: got {obj['unauthorized_providers']}"
        assert sorted(obj["missing_providers"]) == sorted(expected["missing_providers"]), \
            f"AS{expected['customer_asn']}: missing mismatch: got {obj['missing_providers']}"


# ============================================================
# CORRECTED ASPA TESTS
# ============================================================

class TestCorrectedASPA:
    def test_aspa_entry_count(self, audit):
        assert len(audit["corrected_aspa"]) == 14, \
            f"Expected 14 corrected ASPA entries, got {len(audit['corrected_aspa'])}"

    @pytest.mark.parametrize("asn_str,expected_provs",
                             list(EXPECTED_CORRECTED_ASPA.items()),
                             ids=[f"AS{k}" for k in EXPECTED_CORRECTED_ASPA])
    def test_corrected_provider_set(self, audit, asn_str, expected_provs):
        assert asn_str in audit["corrected_aspa"], \
            f"AS{asn_str} missing from corrected_aspa"
        actual = sorted(audit["corrected_aspa"][asn_str])
        expected = sorted(expected_provs)
        assert actual == expected, \
            f"AS{asn_str}: expected providers {expected}, got {actual}"


# ============================================================
# ROUTE ANALYSIS TESTS
# ============================================================

class TestRouteAnalysis:
    def test_route_count(self, audit):
        assert len(audit["route_analysis"]) == 30, \
            f"Expected 30 route analyses, got {len(audit['route_analysis'])}"

    def _get_route(self, audit, route_id):
        matches = [r for r in audit["route_analysis"] if r["id"] == route_id]
        assert len(matches) == 1, f"Route {route_id} not found or duplicated"
        return matches[0]

    @pytest.mark.parametrize("route_id", list(EXPECTED_ROUTES.keys()))
    def test_direction(self, audit, route_id):
        r = self._get_route(audit, route_id)
        expected_dir = EXPECTED_ROUTES[route_id][0]
        assert r["direction"] == expected_dir, \
            f"{route_id}: expected direction '{expected_dir}', got '{r['direction']}'"

    @pytest.mark.parametrize("route_id", list(EXPECTED_ROUTES.keys()))
    def test_result(self, audit, route_id):
        r = self._get_route(audit, route_id)
        expected_result = EXPECTED_ROUTES[route_id][1]
        assert r["result"] == expected_result, \
            f"{route_id}: expected result '{expected_result}', got '{r['result']}'"

    @pytest.mark.parametrize("route_id",
                             [k for k, v in EXPECTED_ROUTES.items() if v[2] is not None])
    def test_leak_attribution(self, audit, route_id):
        r = self._get_route(audit, route_id)
        expected_leak = EXPECTED_ROUTES[route_id][2]
        assert r.get("leak_source_asn") == expected_leak, \
            f"{route_id}: expected leak_source_asn={expected_leak}, " \
            f"got {r.get('leak_source_asn')}"


# ============================================================
# DEPLOYMENT RECOMMENDATION TESTS
# ============================================================

class TestDeployment:
    def test_recommendation_set(self, audit):
        rec_asns = {r["asn"] for r in audit["deployment_recommendation"]}
        assert rec_asns == EXPECTED_DEPLOY_ASNS, \
            f"Expected deployment ASes {EXPECTED_DEPLOY_ASNS}, got {rec_asns}"

    def test_greedy_priority(self, audit):
        """First recommended AS should resolve the most routes."""
        assert len(audit["deployment_recommendation"]) > 0
        first = audit["deployment_recommendation"][0]
        assert first["asn"] == EXPECTED_DEPLOY_FIRST, \
            f"Expected AS{EXPECTED_DEPLOY_FIRST} first (highest impact), " \
            f"got AS{first['asn']}"

    def test_provider_sets(self, audit):
        expected_providers = {
            64544: [64534], 64540: [64530],
            64542: [64532], 64543: [64533],
        }
        for rec in audit["deployment_recommendation"]:
            asn = rec["asn"]
            if asn in expected_providers:
                assert sorted(rec["provider_set"]) == sorted(expected_providers[asn]), \
                    f"AS{asn}: expected providers {expected_providers[asn]}, " \
                    f"got {rec['provider_set']}"

    def test_resolves_routes_for_top_pick(self, audit):
        """Top-priority AS should resolve exactly two specific Unknown routes."""
        top = [r for r in audit["deployment_recommendation"]
               if r["asn"] == 64544]
        assert len(top) == 1
        assert set(top[0]["resolves_routes"]) == {"OBS-009", "OBS-019"}, \
            f"AS64544 resolves_routes mismatch: {top[0]['resolves_routes']}"


# ============================================================
# STRUCTURAL TESTS
# ============================================================

class TestStructure:
    def test_valid_result_values(self, audit):
        allowed = {"Valid", "Invalid", "Unknown", "Unverifiable"}
        for r in audit["route_analysis"]:
            assert r["result"] in allowed, \
                f"{r['id']}: invalid result '{r['result']}'"

    def test_valid_direction_values(self, audit):
        allowed = {"upstream", "downstream"}
        for r in audit["route_analysis"]:
            assert r["direction"] in allowed, \
                f"{r['id']}: invalid direction '{r['direction']}'"

    def test_no_leak_for_non_invalid(self, audit):
        for r in audit["route_analysis"]:
            if r["result"] != "Invalid":
                leak = r.get("leak_source_asn")
                assert leak is None, \
                    f"{r['id']}: non-Invalid route should have null " \
                    f"leak_source_asn, got {leak}"

    def test_all_route_ids_present(self, audit):
        actual_ids = {r["id"] for r in audit["route_analysis"]}
        expected_ids = set(EXPECTED_ROUTES.keys())
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        assert not missing, f"Missing route IDs: {sorted(missing)}"
        assert not extra, f"Extra route IDs: {sorted(extra)}"
