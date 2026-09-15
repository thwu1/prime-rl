
import json
import pytest


@pytest.fixture
def results():
    with open("/app/analysis_results.json") as f:
        return json.load(f)


EXPECTED_KEYS = [
    "total_routes", "rpki_valid", "rpki_invalid", "rpki_invalid_as",
    "rpki_invalid_length", "rpki_not_found", "rpki_unsafe_maxlength",
    "rpki_conflicting_prefixes", "rpki_redundant_roas", "aspa_valid",
    "aspa_invalid", "aspa_unknown", "irr_registered", "irr_origin_match",
    "irr_origin_mismatch", "multi_signal_hijack_candidates"
]


def test_results_exist(results):
    assert isinstance(results, dict)


def test_all_keys_present(results):
    for key in EXPECTED_KEYS:
        assert key in results, f"Missing key: {key}"


def test_all_values_are_integers(results):
    for key in EXPECTED_KEYS:
        assert isinstance(results.get(key), int), f"{key} should be int"


def test_total_routes(results):
    assert results["total_routes"] == 60


def test_rpki_valid(results):
    assert results["rpki_valid"] == 41


def test_rpki_invalid(results):
    assert results["rpki_invalid"] == 16


def test_rpki_invalid_as(results):
    assert results["rpki_invalid_as"] == 11


def test_rpki_invalid_length(results):
    assert results["rpki_invalid_length"] == 5


def test_rpki_not_found(results):
    assert results["rpki_not_found"] == 3


def test_rpki_unsafe_maxlength(results):
    assert results["rpki_unsafe_maxlength"] == 10


def test_rpki_conflicting_prefixes(results):
    assert results["rpki_conflicting_prefixes"] == 2


def test_rpki_redundant_roas(results):
    assert results["rpki_redundant_roas"] == 3


def test_aspa_valid(results):
    assert results["aspa_valid"] == 49


def test_aspa_invalid(results):
    assert results["aspa_invalid"] == 10


def test_aspa_unknown(results):
    assert results["aspa_unknown"] == 1


def test_irr_registered(results):
    assert results["irr_registered"] == 56


def test_irr_origin_match(results):
    assert results["irr_origin_match"] == 42


def test_irr_origin_mismatch(results):
    assert results["irr_origin_mismatch"] == 14


def test_multi_signal_hijack_candidates(results):
    assert results["multi_signal_hijack_candidates"] == 12


def test_rpki_consistency(results):
    total = results["rpki_valid"] + results["rpki_invalid"] + results["rpki_not_found"]
    assert total == results["total_routes"], (
        f"ROV categories ({total}) must sum to total_routes ({results['total_routes']})"
    )


def test_rpki_invalid_subtypes(results):
    sub = results["rpki_invalid_as"] + results["rpki_invalid_length"]
    assert sub == results["rpki_invalid"], (
        f"Invalid subtypes ({sub}) must sum to rpki_invalid ({results['rpki_invalid']})"
    )


def test_aspa_consistency(results):
    total = results["aspa_valid"] + results["aspa_invalid"] + results["aspa_unknown"]
    assert total == results["total_routes"], (
        f"ASPA categories ({total}) must sum to total_routes ({results['total_routes']})"
    )


def test_irr_consistency(results):
    total = results["irr_origin_match"] + results["irr_origin_mismatch"]
    assert total == results["irr_registered"], (
        f"IRR match+mismatch ({total}) must sum to irr_registered ({results['irr_registered']})"
    )
