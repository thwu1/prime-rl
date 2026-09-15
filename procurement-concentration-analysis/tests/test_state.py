
import json
import os
import subprocess
import sys

import pytest

NAICS_CODES = ["541511", "541512"]
FISCAL_YEAR = 2023
OUTPUT_PATH = "/app/test_report_output.json"


@pytest.fixture(scope="session")
def report():
    """Run the analyzer tool and return the parsed JSON report."""
    # Remove any stale output
    if os.path.exists(OUTPUT_PATH):
        os.remove(OUTPUT_PATH)

    cmd = [
        sys.executable, "/app/analyze.py",
        "--naics",
    ] + NAICS_CODES + [
        "--fy", str(FISCAL_YEAR),
        "--output", OUTPUT_PATH,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)
    assert result.returncode == 0, (
        f"analyze.py exited with code {result.returncode}.\n"
        f"STDOUT: {result.stdout[-2000:]}\n"
        f"STDERR: {result.stderr[-2000:]}"
    )
    assert os.path.exists(OUTPUT_PATH), "Output JSON file was not created"

    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    return data


# ── Metadata ──────────────────────────────────────────────────────────────

class TestMetadata:
    def test_metadata_exists(self, report):
        assert "metadata" in report

    def test_naics_codes_match(self, report):
        assert report["metadata"]["naics_codes"] == NAICS_CODES

    def test_fiscal_year_match(self, report):
        assert report["metadata"]["fiscal_year"] == FISCAL_YEAR

    def test_generated_at_present(self, report):
        ts = report["metadata"]["generated_at"]
        assert isinstance(ts, str) and len(ts) >= 10


# ── Per-NAICS structure ──────────────────────────────────────────────────

class TestPerNaicsStructure:
    def test_all_naics_present(self, report):
        for code in NAICS_CODES:
            assert code in report["per_naics"], f"Missing NAICS {code}"

    def test_total_spending_positive(self, report):
        for code in NAICS_CODES:
            assert report["per_naics"][code]["total_spending"] > 0

    def test_recipient_count_positive(self, report):
        for code in NAICS_CODES:
            assert report["per_naics"][code]["recipient_count"] > 0

    def test_concentration_keys(self, report):
        for code in NAICS_CODES:
            conc = report["per_naics"][code]["concentration"]
            for key in ("hhi", "cr4", "cr8"):
                assert key in conc, f"Missing concentration.{key} for {code}"

    def test_top_recipients_nonempty(self, report):
        for code in NAICS_CODES:
            recips = report["per_naics"][code]["top_recipients"]
            assert len(recips) >= 10, (
                f"Expected >=10 recipients for {code}, got {len(recips)}"
            )

    def test_geographic_keys(self, report):
        for code in NAICS_CODES:
            geo = report["per_naics"][code]["geographic"]
            assert "hhi" in geo
            assert "top_states" in geo

    def test_top_agency_keys(self, report):
        for code in NAICS_CODES:
            agency = report["per_naics"][code]["top_agency"]
            assert "name" in agency and "amount" in agency


# ── Concentration metric ranges ──────────────────────────────────────────

class TestConcentrationRanges:
    def test_hhi_range(self, report):
        for code in NAICS_CODES:
            hhi = report["per_naics"][code]["concentration"]["hhi"]
            assert 0 <= hhi <= 10000, f"HHI={hhi} out of [0,10000]"

    def test_cr4_range(self, report):
        for code in NAICS_CODES:
            cr4 = report["per_naics"][code]["concentration"]["cr4"]
            assert 0 <= cr4 <= 100, f"CR4={cr4} out of [0,100]"

    def test_cr8_range(self, report):
        for code in NAICS_CODES:
            cr8 = report["per_naics"][code]["concentration"]["cr8"]
            assert 0 <= cr8 <= 100, f"CR8={cr8} out of [0,100]"

    def test_cr4_le_cr8(self, report):
        for code in NAICS_CODES:
            conc = report["per_naics"][code]["concentration"]
            assert conc["cr4"] <= conc["cr8"] + 0.01, (
                f"CR4={conc['cr4']} > CR8={conc['cr8']}"
            )

    def test_geo_hhi_range(self, report):
        for code in NAICS_CODES:
            geo_hhi = report["per_naics"][code]["geographic"]["hhi"]
            assert 0 <= geo_hhi <= 10000, f"Geo HHI={geo_hhi} out of [0,10000]"


# ── Recipient data quality ───────────────────────────────────────────────

class TestRecipientData:
    def test_recipient_fields(self, report):
        for code in NAICS_CODES:
            for r in report["per_naics"][code]["top_recipients"]:
                assert "name" in r and isinstance(r["name"], str)
                assert "amount" in r and isinstance(r["amount"], (int, float))
                assert "share_pct" in r and isinstance(r["share_pct"], (int, float))
                assert "recipient_id" in r and isinstance(r["recipient_id"], str)

    def test_recipients_sorted_descending(self, report):
        for code in NAICS_CODES:
            amounts = [r["amount"] for r in report["per_naics"][code]["top_recipients"]]
            assert amounts == sorted(amounts, reverse=True), (
                f"Recipients for {code} not sorted descending by amount"
            )

    def test_amounts_nonnegative(self, report):
        for code in NAICS_CODES:
            for r in report["per_naics"][code]["top_recipients"]:
                assert r["amount"] >= 0

    def test_share_pct_bounded(self, report):
        for code in NAICS_CODES:
            total_share = sum(
                r["share_pct"] for r in report["per_naics"][code]["top_recipients"]
            )
            assert total_share <= 100.5, (
                f"Sum of share_pct={total_share} exceeds 100% for {code}"
            )


# ── Concentration math consistency ───────────────────────────────────────

class TestConcentrationMath:
    def test_hhi_recomputation(self, report):
        """Recompute HHI from the reported recipients and compare."""
        for code in NAICS_CODES:
            recips = report["per_naics"][code]["top_recipients"]
            amounts = [r["amount"] for r in recips]
            total = sum(amounts)
            if total <= 0:
                continue
            shares = [(a / total) * 100 for a in amounts]
            expected_hhi = sum(s * s for s in shares)
            actual_hhi = report["per_naics"][code]["concentration"]["hhi"]
            # Allow tolerance because the tool may use a slightly different
            # denominator (e.g., API-reported total vs sum of top-N)
            assert abs(actual_hhi - expected_hhi) < max(1.0, actual_hhi * 0.05), (
                f"HHI mismatch for {code}: reported={actual_hhi}, "
                f"recomputed={expected_hhi}"
            )

    def test_cr4_recomputation(self, report):
        for code in NAICS_CODES:
            recips = report["per_naics"][code]["top_recipients"]
            amounts = sorted([r["amount"] for r in recips], reverse=True)
            total = sum(amounts)
            if total <= 0 or len(amounts) < 4:
                continue
            expected_cr4 = sum(amounts[:4]) / total * 100
            actual_cr4 = report["per_naics"][code]["concentration"]["cr4"]
            assert abs(actual_cr4 - expected_cr4) < max(0.5, actual_cr4 * 0.05), (
                f"CR4 mismatch for {code}: reported={actual_cr4}, "
                f"recomputed={expected_cr4}"
            )

    def test_cr8_recomputation(self, report):
        for code in NAICS_CODES:
            recips = report["per_naics"][code]["top_recipients"]
            amounts = sorted([r["amount"] for r in recips], reverse=True)
            total = sum(amounts)
            if total <= 0 or len(amounts) < 8:
                continue
            expected_cr8 = sum(amounts[:8]) / total * 100
            actual_cr8 = report["per_naics"][code]["concentration"]["cr8"]
            assert abs(actual_cr8 - expected_cr8) < max(0.5, actual_cr8 * 0.05), (
                f"CR8 mismatch for {code}: reported={actual_cr8}, "
                f"recomputed={expected_cr8}"
            )


# ── Geographic data ──────────────────────────────────────────────────────

class TestGeographic:
    def test_top_states_nonempty(self, report):
        for code in NAICS_CODES:
            states = report["per_naics"][code]["geographic"]["top_states"]
            assert len(states) >= 1, f"No top_states for {code}"

    def test_state_fields(self, report):
        for code in NAICS_CODES:
            for s in report["per_naics"][code]["geographic"]["top_states"]:
                assert "state_code" in s
                assert "state_name" in s
                assert "amount" in s
                assert "share_pct" in s

    def test_state_code_format(self, report):
        for code in NAICS_CODES:
            for s in report["per_naics"][code]["geographic"]["top_states"]:
                sc = s["state_code"]
                assert isinstance(sc, str) and len(sc) == 2, (
                    f"Invalid state_code '{sc}' for {code}"
                )

    def test_state_amounts_nonneg(self, report):
        for code in NAICS_CODES:
            for s in report["per_naics"][code]["geographic"]["top_states"]:
                assert s["amount"] >= 0

    def test_top_states_max_five(self, report):
        for code in NAICS_CODES:
            states = report["per_naics"][code]["geographic"]["top_states"]
            assert len(states) <= 5


# ── Top agency ───────────────────────────────────────────────────────────

class TestTopAgency:
    def test_agency_name_nonempty(self, report):
        for code in NAICS_CODES:
            name = report["per_naics"][code]["top_agency"]["name"]
            assert isinstance(name, str) and len(name) > 0

    def test_agency_amount_positive(self, report):
        for code in NAICS_CODES:
            amt = report["per_naics"][code]["top_agency"]["amount"]
            assert amt > 0


# ── Cross-NAICS overlap ─────────────────────────────────────────────────

class TestCrossNaicsOverlap:
    def test_overlap_is_list(self, report):
        assert isinstance(report["cross_naics_overlap"], list)

    def test_overlap_entry_fields(self, report):
        for entry in report["cross_naics_overlap"]:
            assert "name" in entry
            assert "recipient_id" in entry
            assert "naics_codes" in entry
            assert "total_amount" in entry

    def test_overlap_has_multiple_naics(self, report):
        for entry in report["cross_naics_overlap"]:
            assert len(entry["naics_codes"]) >= 2, (
                f"Overlap entry {entry['name']} has fewer than 2 NAICS codes"
            )

    def test_overlap_naics_are_queried(self, report):
        """Every NAICS in an overlap entry must be one of the queried codes."""
        for entry in report["cross_naics_overlap"]:
            for code in entry["naics_codes"]:
                assert code in NAICS_CODES, (
                    f"Overlap entry references unqueried NAICS {code}"
                )

    def test_overlap_amounts_positive(self, report):
        for entry in report["cross_naics_overlap"]:
            assert entry["total_amount"] > 0


# ── Top recipient profile ───────────────────────────────────────────────

class TestTopRecipientProfile:
    def test_profile_exists(self, report):
        profile = report["top_recipient_profile"]
        assert isinstance(profile, dict)
        assert len(profile) > 0, "top_recipient_profile must be non-empty"

    def test_profile_name(self, report):
        profile = report["top_recipient_profile"]
        assert "name" in profile
        assert isinstance(profile["name"], str) and len(profile["name"]) > 0

    def test_profile_recipient_id(self, report):
        profile = report["top_recipient_profile"]
        assert "recipient_id" in profile
        assert isinstance(profile["recipient_id"], str)

    def test_profile_location(self, report):
        profile = report["top_recipient_profile"]
        assert "location" in profile
        assert isinstance(profile["location"], dict)

    def test_profile_business_categories(self, report):
        profile = report["top_recipient_profile"]
        assert "business_categories" in profile
        assert isinstance(profile["business_categories"], list)

    def test_profile_total_transaction_amount(self, report):
        profile = report["top_recipient_profile"]
        assert "total_transaction_amount" in profile
        assert isinstance(profile["total_transaction_amount"], (int, float))


# ── Top-level structure ──────────────────────────────────────────────────

class TestTopLevelStructure:
    def test_required_top_keys(self, report):
        for key in ("metadata", "per_naics", "cross_naics_overlap",
                     "top_recipient_profile"):
            assert key in report, f"Missing top-level key '{key}'"

    def test_per_naics_is_dict(self, report):
        assert isinstance(report["per_naics"], dict)

    def test_cross_naics_is_list(self, report):
        assert isinstance(report["cross_naics_overlap"], list)

    def test_profile_is_dict(self, report):
        assert isinstance(report["top_recipient_profile"], dict)
