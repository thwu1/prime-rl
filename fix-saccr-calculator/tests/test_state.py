import json
import subprocess
import os
import pytest


GOLDEN_EAD = {
    "example1": 569,
    "example2": 381,
    "example3": 5406,
    "example4": 936,
    "example5": 1879,
}

GOLDEN_ADDON = {
    "example1": {"addon_ir": 347},
    "example2": {"addon_credit": 282},
    "example3": {"addon_commodity": 3841},
    "example4": {"addon_ir": 347, "addon_credit": 282},
    "example5": {"addon_ir": 123, "addon_commodity": 1278},
}

GOLDEN_RC = {
    "example1": 60,
    "example2": 0,
    "example3": 20,
    "example4": 40,
    "example5": 0,
}

GOLDEN_ADDON_AGG = {
    "example1": 347,
    "example2": 282,
    "example3": 3841,
    "example4": 629,
    "example5": 1401,
}

GOLDEN_IR_DETAIL = {
    "example1": {"USD": 296, "EUR": 50},
    "example4": {"USD": 296, "EUR": 50},
    "example5": {"USD": 105, "EUR": 18},
}

GOLDEN_CREDIT_DETAIL = {
    "example2": {"FirmA": 106, "FirmB": -280, "CDX.IG": 168},
    "example4": {"FirmA": 106, "FirmB": -280, "CDX.IG": 168},
}

GOLDEN_COMMODITY_DETAIL = {
    "example3": {"Energy": 2041, "Metals": 1800},
    "example5": {"Energy": 639, "Metals": 639},
}

EAD_TOLERANCE = 5
ADDON_TOLERANCE = 10
RC_TOLERANCE = 5
DETAIL_TOLERANCE = 15


@pytest.fixture(scope="session")
def results():
    """Run the SA-CCR calculator and load results."""
    proc = subprocess.run(
        ["Rscript", "/app/saccr.R"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"Rscript /app/saccr.R failed with exit code {proc.returncode}.\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    )
    with open("/app/results.json") as f:
        return json.load(f)


# === EAD golden value tests ===

@pytest.mark.parametrize("example,expected_ead", list(GOLDEN_EAD.items()))
def test_ead_golden_value(results, example, expected_ead):
    """Each example EAD must match the BCBS 279 Annex 4a golden output."""
    assert example in results, f"Missing key '{example}' in results.json"
    actual = results[example]["EAD"]
    assert abs(actual - expected_ead) <= EAD_TOLERANCE, (
        f"{example}: computed EAD={actual}, expected={expected_ead} "
        f"(tolerance +/-{EAD_TOLERANCE})"
    )


# === Per-asset-class addon tests ===

@pytest.mark.parametrize("example,expected_addons", list(GOLDEN_ADDON.items()))
def test_per_asset_class_addon(results, example, expected_addons):
    """Per-asset-class addon values must be correct."""
    assert example in results, f"Missing '{example}'"
    for field, expected in expected_addons.items():
        assert field in results[example], (
            f"{example}: missing '{field}' in output"
        )
        actual = results[example][field]
        assert abs(actual - expected) <= ADDON_TOLERANCE, (
            f"{example}.{field}: got {actual}, expected {expected} "
            f"(tolerance +/-{ADDON_TOLERANCE})"
        )


# === Replacement cost tests ===

@pytest.mark.parametrize("example,expected_rc", list(GOLDEN_RC.items()))
def test_replacement_cost(results, example, expected_rc):
    """Replacement cost must match expected values."""
    assert example in results, f"Missing '{example}'"
    actual = results[example]["RC"]
    assert abs(actual - expected_rc) <= RC_TOLERANCE, (
        f"{example}: RC={actual}, expected={expected_rc} "
        f"(tolerance +/-{RC_TOLERANCE})"
    )


# === Aggregate addon tests ===

@pytest.mark.parametrize("example,expected_agg", list(GOLDEN_ADDON_AGG.items()))
def test_addon_aggregate(results, example, expected_agg):
    """Aggregate addon must match expected values."""
    assert example in results, f"Missing '{example}'"
    actual = results[example]["addon_aggregate"]
    assert abs(actual - expected_agg) <= ADDON_TOLERANCE, (
        f"{example}: addon_agg={actual}, expected={expected_agg} "
        f"(tolerance +/-{ADDON_TOLERANCE})"
    )


# === IR hedging-set detail tests ===

@pytest.mark.parametrize("example,expected_detail", list(GOLDEN_IR_DETAIL.items()))
def test_ir_hedging_set_detail(results, example, expected_detail):
    """IR per-hedging-set (per-currency) detail must match golden values."""
    assert example in results, f"Missing '{example}'"
    assert "ir_detail" in results[example], (
        f"{example}: missing 'ir_detail' in output"
    )
    detail = results[example]["ir_detail"]
    for ccy, expected in expected_detail.items():
        assert ccy in detail, (
            f"{example}: missing currency '{ccy}' in ir_detail"
        )
        actual = detail[ccy]
        assert abs(actual - expected) <= DETAIL_TOLERANCE, (
            f"{example}.ir_detail.{ccy}: got {actual}, expected {expected} "
            f"(tolerance +/-{DETAIL_TOLERANCE})"
        )


# === Credit entity detail tests ===

@pytest.mark.parametrize("example,expected_detail", list(GOLDEN_CREDIT_DETAIL.items()))
def test_credit_entity_detail(results, example, expected_detail):
    """Credit per-entity detail must match golden values (signed)."""
    assert example in results, f"Missing '{example}'"
    assert "credit_detail" in results[example], (
        f"{example}: missing 'credit_detail' in output"
    )
    detail = results[example]["credit_detail"]
    for entity, expected in expected_detail.items():
        assert entity in detail, (
            f"{example}: missing entity '{entity}' in credit_detail"
        )
        actual = detail[entity]
        assert abs(actual - expected) <= DETAIL_TOLERANCE, (
            f"{example}.credit_detail.{entity}: got {actual}, expected {expected} "
            f"(tolerance +/-{DETAIL_TOLERANCE})"
        )


# === Commodity hedging-set detail tests ===

@pytest.mark.parametrize("example,expected_detail", list(GOLDEN_COMMODITY_DETAIL.items()))
def test_commodity_hedging_set_detail(results, example, expected_detail):
    """Commodity per-hedging-set detail must match golden values."""
    assert example in results, f"Missing '{example}'"
    assert "commodity_detail" in results[example], (
        f"{example}: missing 'commodity_detail' in output"
    )
    detail = results[example]["commodity_detail"]
    for hs, expected in expected_detail.items():
        assert hs in detail, (
            f"{example}: missing hedging set '{hs}' in commodity_detail"
        )
        actual = detail[hs]
        assert abs(actual - expected) <= DETAIL_TOLERANCE, (
            f"{example}.commodity_detail.{hs}: got {actual}, expected {expected} "
            f"(tolerance +/-{DETAIL_TOLERANCE})"
        )


# === Structural and consistency tests ===

def test_results_json_exists():
    """Verify that the results file was written."""
    assert os.path.isfile("/app/results.json"), "/app/results.json not found"


def test_all_examples_present(results):
    """All five examples must be present in the output."""
    for ex in GOLDEN_EAD:
        assert ex in results, f"Missing example '{ex}' in results.json"


def test_ead_fields_are_numeric(results):
    """EAD values must be numeric."""
    for ex in GOLDEN_EAD:
        ead = results[ex]["EAD"]
        assert isinstance(ead, (int, float)), (
            f"{ex}: EAD value is {type(ead).__name__}, expected numeric"
        )


def test_replacement_cost_nonnegative(results):
    """Replacement cost must be non-negative for all examples."""
    for ex in GOLDEN_EAD:
        rc = results[ex]["RC"]
        assert rc >= 0, f"{ex}: RC={rc} is negative"


def test_multiplier_in_range(results):
    """Multiplier must be between 0.05 (floor) and 1.0."""
    for ex in GOLDEN_EAD:
        mult = results[ex]["multiplier"]
        assert 0.05 <= mult <= 1.0, (
            f"{ex}: multiplier={mult} outside valid range [0.05, 1.0]"
        )


def test_internal_consistency_pfe(results):
    """PFE must equal multiplier * addon_aggregate (within rounding)."""
    for ex in GOLDEN_EAD:
        r = results[ex]
        expected_pfe = r["multiplier"] * r["addon_aggregate"]
        assert abs(r["PFE"] - expected_pfe) < 5, (
            f"{ex}: PFE={r['PFE']} != mult*addon={expected_pfe:.2f}"
        )


def test_internal_consistency_ead(results):
    """EAD must equal 1.4 * (RC + PFE) within rounding."""
    for ex in GOLDEN_EAD:
        r = results[ex]
        expected_ead = 1.4 * (r["RC"] + r["PFE"])
        assert abs(r["EAD"] - expected_ead) < 5, (
            f"{ex}: EAD={r['EAD']} != 1.4*(RC+PFE)={expected_ead:.2f}"
        )


# === Multiplier-specific tests ===

def test_margined_example_multiplier(results):
    """Example 5 should have multiplier < 1 (V-C is negative)."""
    mult = results["example5"]["multiplier"]
    assert mult < 1.0, (
        f"Example 5 multiplier should be < 1 (V-C negative), got {mult}"
    )
    assert mult > 0.90, (
        f"Example 5 multiplier should be ~0.958, got {mult}"
    )


def test_credit_example_multiplier(results):
    """Example 2 should have multiplier < 1 (V-C is negative, unmargined)."""
    mult = results["example2"]["multiplier"]
    assert mult < 1.0, (
        f"Example 2 multiplier should be < 1 (V-C negative), got {mult}"
    )
    assert mult > 0.90, (
        f"Example 2 multiplier should be ~0.9586, got {mult}"
    )


def test_margined_example_rc_zero(results):
    """Example 5 RC should be 0 (over-collateralised margined set)."""
    rc = results["example5"]["RC"]
    assert rc == 0, f"Example 5 RC should be 0, got {rc}"


def test_unmargined_multiplier_one(results):
    """Examples 1, 3, 4 have V-C >= 0 so multiplier must be 1."""
    for ex in ["example1", "example3", "example4"]:
        mult = results[ex]["multiplier"]
        assert mult == 1.0, (
            f"{ex}: multiplier should be 1.0 (V-C >= 0), got {mult}"
        )


# === Cross-validation tests ===

def test_credit_detail_sign_convention(results):
    """Entity-level credit addons must have correct sign (protection buyer positive)."""
    for ex in GOLDEN_CREDIT_DETAIL:
        detail = results[ex].get("credit_detail", {})
        for entity, expected in GOLDEN_CREDIT_DETAIL[ex].items():
            if entity in detail:
                actual = detail[entity]
                if expected > 0:
                    assert actual > 0, (
                        f"{ex}.credit_detail.{entity} should be positive, got {actual}"
                    )
                else:
                    assert actual < 0, (
                        f"{ex}.credit_detail.{entity} should be negative, got {actual}"
                    )


def test_ir_detail_sums_to_addon(results):
    """IR detail per-currency values should approximately sum to total IR addon."""
    for ex in GOLDEN_IR_DETAIL:
        if "ir_detail" in results.get(ex, {}) and "addon_ir" in results.get(ex, {}):
            detail_sum = sum(results[ex]["ir_detail"].values())
            total = results[ex]["addon_ir"]
            assert abs(detail_sum - total) < DETAIL_TOLERANCE, (
                f"{ex}: ir_detail sum={detail_sum:.1f} != addon_ir={total}"
            )


def test_commodity_detail_sums_to_addon(results):
    """Commodity detail per-hedging-set values should approximately sum to total addon."""
    for ex in GOLDEN_COMMODITY_DETAIL:
        if "commodity_detail" in results.get(ex, {}) and "addon_commodity" in results.get(ex, {}):
            detail_sum = sum(results[ex]["commodity_detail"].values())
            total = results[ex]["addon_commodity"]
            assert abs(detail_sum - total) < DETAIL_TOLERANCE, (
                f"{ex}: commodity_detail sum={detail_sum:.1f} != addon_commodity={total}"
            )


def test_example4_addon_is_sum_of_classes(results):
    """Example 4 aggregate addon must equal IR addon + Credit addon."""
    r = results.get("example4", {})
    if "addon_ir" in r and "addon_credit" in r:
        expected = r["addon_ir"] + r["addon_credit"]
        actual = r["addon_aggregate"]
        assert abs(actual - expected) < ADDON_TOLERANCE, (
            f"example4: addon_aggregate={actual} != addon_ir + addon_credit = {expected}"
        )


def test_example5_addon_is_sum_of_classes(results):
    """Example 5 aggregate addon must equal IR addon + Commodity addon."""
    r = results.get("example5", {})
    if "addon_ir" in r and "addon_commodity" in r:
        expected = r["addon_ir"] + r["addon_commodity"]
        actual = r["addon_aggregate"]
        assert abs(actual - expected) < ADDON_TOLERANCE, (
            f"example5: addon_aggregate={actual} != addon_ir + addon_commodity = {expected}"
        )
