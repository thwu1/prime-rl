"""
Tests for FRED Macroeconomic Analysis output.
Verifies the structure, correctness, and economic plausibility of computed indicators.
"""

import json
import math
import os

import pytest


@pytest.fixture(scope="module")
def indicators():
    path = "/app/output/indicators.json"
    assert os.path.exists(path), f"Output file not found: {path}"
    with open(path, "r") as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_top_level_keys(self, indicators):
        required = {"metadata", "monthly_data", "inversion_episodes",
                     "sahm_rule_triggers", "summary"}
        assert required.issubset(set(indicators.keys()))

    def test_metadata_dates(self, indicators):
        meta = indicators["metadata"]
        assert meta["start_date"] == "1977-01"
        assert meta["end_date"] == "2025-12"

    def test_metadata_num_months(self, indicators):
        assert indicators["metadata"]["num_months"] == 588

    def test_monthly_data_count(self, indicators):
        assert len(indicators["monthly_data"]) == 588

    def test_date_keys_format(self, indicators):
        for key in indicators["monthly_data"]:
            parts = key.split("-")
            assert len(parts) == 2, f"Bad date key format: {key}"
            year, month = int(parts[0]), int(parts[1])
            assert 1977 <= year <= 2025
            assert 1 <= month <= 12

    def test_monthly_entry_fields(self, indicators):
        required_fields = {
            "cpi", "cpi_yoy_inflation", "fedfunds", "real_fed_funds_rate",
            "unrate", "sahm_rule_indicator", "m2_velocity",
            "taylor_rule_rate", "taylor_gap",
            "t10y2y_monthly_avg", "dgs10_monthly_avg", "payroll_momentum",
        }
        # Check several dates well within all series ranges
        for date in ["1990-06", "2000-06", "2010-06", "2020-06"]:
            entry = indicators["monthly_data"][date]
            missing = required_fields - set(entry.keys())
            assert not missing, f"Missing fields at {date}: {missing}"

    def test_no_nan_strings_or_floats(self, indicators):
        for date, data in indicators["monthly_data"].items():
            for key, val in data.items():
                if isinstance(val, str):
                    assert val.lower() != "nan", f"NaN string at {date}.{key}"
                if isinstance(val, float):
                    assert not math.isnan(val), f"NaN float at {date}.{key}"


# ---------------------------------------------------------------------------
# CPI inflation tests
# ---------------------------------------------------------------------------

class TestCPIInflation:
    def test_inflation_jan_2020(self, indicators):
        """CPI Jan 2020 ~259.1, Jan 2019 ~252.6 -> ~2.6%."""
        val = indicators["monthly_data"]["2020-01"]["cpi_yoy_inflation"]
        assert val is not None
        assert abs(val - 2.60) < 0.5, f"Jan 2020 inflation unexpected: {val}"

    def test_inflation_jan_2022(self, indicators):
        """CPI Jan 2022 ~282.5, Jan 2021 ~262.7 -> ~7.56%."""
        val = indicators["monthly_data"]["2022-01"]["cpi_yoy_inflation"]
        assert val is not None
        assert abs(val - 7.56) < 0.5, f"Jan 2022 inflation unexpected: {val}"

    def test_inflation_jan_2024(self, indicators):
        """CPI Jan 2024 ~309.7, Jan 2023 ~300.4 -> ~3.09%."""
        val = indicators["monthly_data"]["2024-01"]["cpi_yoy_inflation"]
        assert val is not None
        assert abs(val - 3.09) < 0.5, f"Jan 2024 inflation unexpected: {val}"

    def test_inflation_peaked_above_8(self, indicators):
        peak = max(
            (d["cpi_yoy_inflation"] for d in indicators["monthly_data"].values()
             if d["cpi_yoy_inflation"] is not None)
        )
        assert peak > 8.0, f"Peak inflation too low: {peak}"

    def test_inflation_all_present_2000s(self, indicators):
        """Every month in 2000-2009 should have non-null inflation."""
        for y in range(2000, 2010):
            for m in range(1, 13):
                date = f"{y}-{m:02d}"
                val = indicators["monthly_data"][date]["cpi_yoy_inflation"]
                assert val is not None, f"Missing inflation at {date}"


# ---------------------------------------------------------------------------
# Real rate tests
# ---------------------------------------------------------------------------

class TestRealRate:
    def test_real_rate_deeply_negative_early_2022(self, indicators):
        """FEDFUNDS ~0.08, inflation ~7.56 -> real rate ~-7.5."""
        val = indicators["monthly_data"]["2022-01"]["real_fed_funds_rate"]
        assert val is not None
        assert val < -6.0, f"Real rate not negative enough in Jan 2022: {val}"

    def test_real_rate_positive_early_2024(self, indicators):
        """FEDFUNDS ~5.33, inflation ~3.09 -> real rate ~2.2."""
        val = indicators["monthly_data"]["2024-01"]["real_fed_funds_rate"]
        assert val is not None
        assert val > 1.0, f"Real rate not positive enough in Jan 2024: {val}"
        assert val < 4.0, f"Real rate too high in Jan 2024: {val}"

    def test_real_rate_internal_consistency(self, indicators):
        """real_rate must equal fedfunds - inflation (within rounding)."""
        checked = 0
        for date, data in indicators["monthly_data"].items():
            r = data.get("real_fed_funds_rate")
            ff = data.get("fedfunds")
            inf = data.get("cpi_yoy_inflation")
            if r is not None and ff is not None and inf is not None:
                expected = ff - inf
                assert abs(r - expected) < 0.05, (
                    f"Inconsistent real rate at {date}: {r} != {ff} - {inf} = {expected}"
                )
                checked += 1
        assert checked > 400, f"Too few consistency checks: {checked}"


# ---------------------------------------------------------------------------
# Sahm Rule tests
# ---------------------------------------------------------------------------

class TestSahmRule:
    def test_no_trigger_2019(self, indicators):
        """Sahm Rule should NOT trigger in 2019."""
        for m in range(1, 13):
            date = f"2019-{m:02d}"
            val = indicators["monthly_data"][date]["sahm_rule_indicator"]
            if val is not None:
                assert val < 0.50, f"False trigger at {date}: {val}"

    def test_trigger_during_covid(self, indicators):
        triggers = indicators["sahm_rule_triggers"]
        t2020 = [t for t in triggers if t.startswith("2020-")]
        assert len(t2020) > 0, "Sahm Rule did not trigger during 2020 recession"

    def test_trigger_during_great_recession(self, indicators):
        triggers = indicators["sahm_rule_triggers"]
        t2008 = [t for t in triggers if t.startswith("2008-")]
        assert len(t2008) > 0, "Sahm Rule did not trigger during 2008 recession"

    def test_covid_sahm_very_high(self, indicators):
        """By mid-2020 the Sahm indicator should be well above 0.5."""
        found = False
        for month in ["2020-04", "2020-05", "2020-06"]:
            val = indicators["monthly_data"][month]["sahm_rule_indicator"]
            if val is not None and val > 2.0:
                found = True
        assert found, "Sahm indicator not elevated enough during COVID"

    def test_sahm_triggers_sorted(self, indicators):
        triggers = indicators["sahm_rule_triggers"]
        assert triggers == sorted(triggers), "Sahm trigger dates not sorted"


# ---------------------------------------------------------------------------
# Taylor Rule tests
# ---------------------------------------------------------------------------

class TestTaylorRule:
    def test_taylor_gap_large_positive_early_2022(self, indicators):
        """Fed was far behind the Taylor Rule in early 2022."""
        val = indicators["monthly_data"]["2022-01"]["taylor_gap"]
        assert val is not None
        assert val > 5.0, f"Taylor gap too small in Jan 2022: {val}"

    def test_taylor_gap_smaller_2024(self, indicators):
        """After aggressive hikes, Taylor gap should narrow by 2024."""
        val = indicators["monthly_data"]["2024-01"]["taylor_gap"]
        assert val is not None
        assert abs(val) < 5.0, f"Taylor gap still too wide in Jan 2024: {val}"

    def test_taylor_rule_positive_when_inflation_positive(self, indicators):
        for date in ["2022-01", "2023-01", "2024-01"]:
            val = indicators["monthly_data"][date]["taylor_rule_rate"]
            assert val is not None
            assert val > 0, f"Taylor Rule negative at {date}: {val}"

    def test_taylor_rule_present_2000s(self, indicators):
        """Taylor Rule should be computable for every month in the 2000s."""
        for y in range(2000, 2010):
            for m in range(1, 13):
                date = f"{y}-{m:02d}"
                val = indicators["monthly_data"][date]["taylor_rule_rate"]
                assert val is not None, f"Missing Taylor Rule at {date}"


# ---------------------------------------------------------------------------
# Yield curve inversion tests
# ---------------------------------------------------------------------------

class TestInversions:
    def test_at_least_one_episode(self, indicators):
        assert len(indicators["inversion_episodes"]) > 0

    def test_2022_inversion_exists(self, indicators):
        found = any(
            ep["start_month"].startswith("2022")
            for ep in indicators["inversion_episodes"]
        )
        assert found, "No inversion episode starting in 2022"

    def test_2022_inversion_long(self, indicators):
        durations = [
            ep["duration_months"]
            for ep in indicators["inversion_episodes"]
            if ep["start_month"].startswith("2022")
        ]
        assert max(durations) >= 20, (
            f"2022 inversion too short: {max(durations)} months"
        )

    def test_pre_1990_inversions_exist(self, indicators):
        found = any(
            ep["start_month"][:3] in ("197", "198")
            for ep in indicators["inversion_episodes"]
        )
        assert found, "No inversion episodes in late 1970s / 1980s era"

    def test_inversion_spreads_negative(self, indicators):
        for ep in indicators["inversion_episodes"]:
            assert ep["min_monthly_avg_spread"] < 0, (
                f"Positive min spread in inversion: {ep}"
            )
            assert ep["mean_monthly_avg_spread"] < 0, (
                f"Positive mean spread in inversion: {ep}"
            )

    def test_episode_fields(self, indicators):
        required = {"start_month", "end_month", "duration_months",
                     "min_monthly_avg_spread", "mean_monthly_avg_spread"}
        for ep in indicators["inversion_episodes"]:
            missing = required - set(ep.keys())
            assert not missing, f"Inversion episode missing fields: {missing}"


# ---------------------------------------------------------------------------
# M2 velocity tests
# ---------------------------------------------------------------------------

class TestM2Velocity:
    def test_velocity_reasonable_range(self, indicators):
        for date in ["2019-06", "2023-06"]:
            val = indicators["monthly_data"][date]["m2_velocity"]
            assert val is not None, f"Missing M2 velocity at {date}"
            assert 0.8 < val < 2.5, f"M2 velocity out of range at {date}: {val}"

    def test_velocity_declined_2019_to_2021(self, indicators):
        """Massive M2 expansion during COVID should lower velocity."""
        v19 = indicators["monthly_data"]["2019-06"]["m2_velocity"]
        v21 = indicators["monthly_data"]["2021-06"]["m2_velocity"]
        assert v19 is not None and v21 is not None
        assert v21 < v19, (
            f"Velocity did not decline from 2019 ({v19}) to 2021 ({v21})"
        )


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_keys(self, indicators):
        required = {
            "total_months", "max_inflation", "min_real_rate",
            "max_taylor_gap", "num_inversion_episodes",
            "num_sahm_triggers", "longest_inversion_months",
        }
        missing = required - set(indicators["summary"].keys())
        assert not missing, f"Summary missing keys: {missing}"

    def test_total_months(self, indicators):
        assert indicators["summary"]["total_months"] == 588

    def test_max_inflation_plausible(self, indicators):
        val = indicators["summary"]["max_inflation"]["value"]
        assert val > 8.0, f"Max inflation too low: {val}"

    def test_min_real_rate_plausible(self, indicators):
        val = indicators["summary"]["min_real_rate"]["value"]
        assert val < -5.0, f"Min real rate not negative enough: {val}"

    def test_max_taylor_gap_plausible(self, indicators):
        val = indicators["summary"]["max_taylor_gap"]["value"]
        assert val > 5.0, f"Max Taylor gap too small: {val}"

    def test_longest_inversion_plausible(self, indicators):
        val = indicators["summary"]["longest_inversion_months"]
        assert val >= 20, f"Longest inversion too short: {val}"

    def test_num_inversion_episodes_positive(self, indicators):
        assert indicators["summary"]["num_inversion_episodes"] > 0

    def test_num_sahm_triggers_positive(self, indicators):
        assert indicators["summary"]["num_sahm_triggers"] > 0


# ---------------------------------------------------------------------------
# Completeness tests
# ---------------------------------------------------------------------------

class TestCompleteness:
    def test_core_fields_2000(self, indicators):
        """Core fields must be non-null throughout year 2000."""
        core = ["cpi", "cpi_yoy_inflation", "fedfunds",
                "real_fed_funds_rate", "unrate"]
        for m in range(1, 13):
            date = f"2000-{m:02d}"
            for field in core:
                assert indicators["monthly_data"][date][field] is not None, (
                    f"Null {field} at {date}"
                )

    def test_derived_fields_2010(self, indicators):
        """All derived indicators should be present mid-range."""
        derived = ["sahm_rule_indicator", "m2_velocity",
                    "taylor_rule_rate", "taylor_gap"]
        for m in range(1, 13):
            date = f"2010-{m:02d}"
            for field in derived:
                assert indicators["monthly_data"][date][field] is not None, (
                    f"Null {field} at {date}"
                )

    def test_inversion_episodes_is_list(self, indicators):
        assert isinstance(indicators["inversion_episodes"], list)

    def test_sahm_triggers_is_list(self, indicators):
        assert isinstance(indicators["sahm_rule_triggers"], list)
