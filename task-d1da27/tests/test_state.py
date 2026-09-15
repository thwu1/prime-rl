
import json
import math
import os
import pytest

OUTPUT_DIR = "/app/output"


def load_json(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    assert os.path.exists(path), f"Output file {filename} does not exist at {path}"
    with open(path) as f:
        return json.load(f)


# ========================
# Catalog Summary Tests
# ========================

class TestCatalogSummary:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "catalog_summary.json"))

    def test_required_keys(self):
        data = load_json("catalog_summary.json")
        for key in ["total_events", "time_span_days", "min_magnitude", "max_magnitude", "region"]:
            assert key in data, f"Missing required key: {key}"

    def test_has_time_span_years(self):
        data = load_json("catalog_summary.json")
        assert "time_span_years" in data
        assert isinstance(data["time_span_years"], (int, float))
        assert data["time_span_years"] > 0

    def test_event_count_reasonable(self):
        """Western US, Jan-Mar 2024, M2.5+ should have hundreds of events."""
        data = load_json("catalog_summary.json")
        assert isinstance(data["total_events"], int)
        assert data["total_events"] >= 200, \
            f"Expected at least 200 events, got {data['total_events']}"
        assert data["total_events"] < 20000, \
            f"Event count {data['total_events']} exceeds FDSN API limit"

    def test_time_span_reasonable(self):
        """Catalog should span roughly 90 days (Q1 2024)."""
        data = load_json("catalog_summary.json")
        assert 60 <= data["time_span_days"] <= 100, \
            f"Time span {data['time_span_days']} days outside expected range [60, 100]"

    def test_magnitude_range(self):
        data = load_json("catalog_summary.json")
        assert data["min_magnitude"] >= 2.0, "Min magnitude should be >= 2.0 for M2.5+ query"
        assert data["min_magnitude"] <= 3.0, "Min magnitude should be <= 3.0"
        assert data["max_magnitude"] >= 4.0, "Western US Q1 2024 should have at least one M4+ event"

    def test_region_bounds(self):
        data = load_json("catalog_summary.json")
        region = data["region"]
        assert "min_lat" in region
        assert "max_lat" in region
        assert "min_lon" in region
        assert "max_lon" in region
        assert region["min_lat"] >= 30
        assert region["max_lat"] <= 50
        assert region["min_lon"] >= -130
        assert region["max_lon"] <= -100


# ========================
# Grid B-value Tests
# ========================

class TestGridBvalues:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "grid_bvalues.json"))

    def test_has_cells(self):
        data = load_json("grid_bvalues.json")
        assert "cells" in data
        assert len(data["cells"]) > 0, "Should have at least one qualifying grid cell"

    def test_multiple_cells(self):
        """Western US should have multiple seismically active grid cells."""
        data = load_json("grid_bvalues.json")
        assert len(data["cells"]) >= 3, \
            f"Expected at least 3 qualifying grid cells, got {len(data['cells'])}"

    def test_cell_structure(self):
        data = load_json("grid_bvalues.json")
        required_keys = ["lat_center", "lon_center", "event_count", "mc",
                         "b_value", "b_value_stderr"]
        for cell in data["cells"]:
            for key in required_keys:
                assert key in cell, \
                    f"Cell ({cell.get('lat_center')}, {cell.get('lon_center')}) missing key: {key}"

    def test_bvalue_physical_range(self):
        """b-values must be physically meaningful (typically 0.5-2.0, allow wider)."""
        data = load_json("grid_bvalues.json")
        for cell in data["cells"]:
            b = cell["b_value"]
            assert 0.3 <= b <= 3.0, \
                f"b-value {b} at ({cell['lat_center']}, {cell['lon_center']}) " \
                f"outside physical range [0.3, 3.0]"

    def test_mc_range(self):
        """Completeness magnitude should be between 2.0 and 6.0 for M2.5+ catalog."""
        data = load_json("grid_bvalues.json")
        for cell in data["cells"]:
            mc = cell["mc"]
            assert 2.0 <= mc <= 6.0, \
                f"Mc={mc} at ({cell['lat_center']}, {cell['lon_center']}) " \
                f"outside expected range [2.0, 6.0]"

    def test_bvalue_stderr_positive(self):
        data = load_json("grid_bvalues.json")
        for cell in data["cells"]:
            assert cell["b_value_stderr"] > 0, \
                f"b-value stderr must be positive at ({cell['lat_center']}, {cell['lon_center']})"
            assert cell["b_value_stderr"] < 2.0, \
                f"b-value stderr {cell['b_value_stderr']} unreasonably large"

    def test_event_count_threshold(self):
        data = load_json("grid_bvalues.json")
        for cell in data["cells"]:
            assert cell["event_count"] >= 10, \
                f"Cell ({cell['lat_center']}, {cell['lon_center']}) has only " \
                f"{cell['event_count']} events, minimum is 10"

    def test_bin_size_specified(self):
        data = load_json("grid_bvalues.json")
        assert "bin_size_degrees" in data
        assert data["bin_size_degrees"] == 1.0

    def test_cells_within_region(self):
        """All grid cell centers should be within the query region."""
        data = load_json("grid_bvalues.json")
        for cell in data["cells"]:
            assert 31.5 <= cell["lat_center"] <= 49.5, \
                f"Cell lat {cell['lat_center']} outside region"
            assert -125.5 <= cell["lon_center"] <= -104.5, \
                f"Cell lon {cell['lon_center']} outside region"

    def test_has_a_value(self):
        """Cells should have an annualized a-value."""
        data = load_json("grid_bvalues.json")
        has_a = sum(1 for c in data["cells"] if "a_value" in c and c["a_value"] is not None)
        assert has_a > 0, "At least some cells should have an a-value"


# ========================
# Site Design Tests
# ========================

class TestSiteDesign:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "site_design.json"))

    def test_five_sites_present(self):
        data = load_json("site_design.json")
        assert "sites" in data
        assert len(data["sites"]) == 5, f"Expected 5 sites, got {len(data['sites'])}"

    def test_site_names(self):
        data = load_json("site_design.json")
        names = {s["name"] for s in data["sites"]}
        expected = {"San Francisco", "Salt Lake City", "Portland", "Phoenix", "Reno"}
        assert names == expected, f"Site names mismatch: got {names}, expected {expected}"

    def test_reference_document(self):
        data = load_json("site_design.json")
        assert "reference_document" in data
        assert "ASCE7-22" in data["reference_document"] or "ASCE 7-22" in data["reference_document"]

    def test_all_sites_have_sds(self):
        """All sites should have SDS values from the API."""
        data = load_json("site_design.json")
        for site in data["sites"]:
            assert "sds" in site, f"{site['name']} missing SDS"
            assert site["sds"] is not None, f"{site['name']} has null SDS"
            assert isinstance(site["sds"], (int, float)), \
                f"{site['name']} SDS is not numeric: {site['sds']}"
            assert site["sds"] > 0, f"{site['name']} SDS must be positive"

    def test_sf_high_hazard(self):
        """San Francisco is in a high seismic zone; SDS should be > 0.8."""
        data = load_json("site_design.json")
        sf = next(s for s in data["sites"] if s["name"] == "San Francisco")
        assert sf["sds"] > 0.8, \
            f"San Francisco SDS={sf['sds']} too low; expected > 0.8 for high seismic zone"

    def test_all_sites_have_sdc(self):
        """All sites should have a Seismic Design Category."""
        data = load_json("site_design.json")
        valid_sdc = {"A", "B", "C", "D", "E", "F"}
        for site in data["sites"]:
            assert "sdc" in site, f"{site['name']} missing SDC"
            assert site["sdc"] in valid_sdc, \
                f"{site['name']} has invalid SDC: {site['sdc']}"

    def test_all_sites_have_spectral_params(self):
        """Sites should have Ss, S1, SMS, SM1 parameters."""
        data = load_json("site_design.json")
        params = ["ss", "s1", "sms", "sm1", "sd1"]
        for site in data["sites"]:
            for p in params:
                assert p in site, f"{site['name']} missing {p}"
                assert site[p] is not None, f"{site['name']} has null {p}"
                assert site[p] > 0, f"{site['name']} {p}={site[p]} must be positive"

    def test_phoenix_lower_than_sf(self):
        """Phoenix should have lower SDS than San Francisco."""
        data = load_json("site_design.json")
        sf = next(s for s in data["sites"] if s["name"] == "San Francisco")
        phx = next(s for s in data["sites"] if s["name"] == "Phoenix")
        assert phx["sds"] < sf["sds"], \
            f"Phoenix SDS={phx['sds']} should be lower than SF SDS={sf['sds']}"


# ========================
# Site Activity Tests
# ========================

class TestSiteActivity:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "site_activity.json"))

    def test_five_sites_present(self):
        data = load_json("site_activity.json")
        assert "sites" in data
        assert len(data["sites"]) == 5

    def test_search_radius(self):
        data = load_json("site_activity.json")
        assert "search_radius_km" in data
        assert data["search_radius_km"] == 200

    def test_non_negative_values(self):
        data = load_json("site_activity.json")
        for site in data["sites"]:
            assert site["events_within_radius"] >= 0, \
                f"{site['name']} has negative event count"
            assert site["annualized_rate_all"] >= 0, \
                f"{site['name']} has negative annualized rate"

    def test_sf_has_events(self):
        """San Francisco area should have earthquake activity."""
        data = load_json("site_activity.json")
        sf = next(s for s in data["sites"] if s["name"] == "San Francisco")
        assert sf["events_within_radius"] > 0, \
            "San Francisco should have events within 200km"
        assert sf["max_magnitude"] is not None, \
            "San Francisco should have a max magnitude"
        assert sf["max_magnitude"] >= 2.5, \
            f"SF max magnitude {sf['max_magnitude']} seems too low"

    def test_has_distance_info(self):
        data = load_json("site_activity.json")
        for site in data["sites"]:
            assert "nearest_event_distance_km" in site
            if site["events_within_radius"] > 0:
                assert site["nearest_event_distance_km"] is not None
                assert 0 <= site["nearest_event_distance_km"] <= 200

    def test_annualized_rate_consistency(self):
        """Annualized rate should be consistent with event count and time span."""
        data = load_json("site_activity.json")
        time_span_years = data.get("catalog_time_span_years")
        if time_span_years and time_span_years > 0:
            for site in data["sites"]:
                expected_rate = site["events_within_radius"] / time_span_years
                actual_rate = site["annualized_rate_all"]
                if expected_rate > 0:
                    ratio = actual_rate / expected_rate
                    assert 0.9 <= ratio <= 1.1, \
                        f"{site['name']} rate inconsistency: expected ~{expected_rate:.2f}, " \
                        f"got {actual_rate:.2f}"

    def test_m4plus_subset(self):
        """M4+ events should be a subset of all events."""
        data = load_json("site_activity.json")
        for site in data["sites"]:
            if "events_m4plus" in site:
                assert site["events_m4plus"] <= site["events_within_radius"], \
                    f"{site['name']} M4+ count exceeds total count"


# ========================
# Discrepancy Tests
# ========================

class TestDiscrepancy:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "discrepancy.json"))

    def test_five_sites_present(self):
        data = load_json("discrepancy.json")
        assert "sites" in data
        assert len(data["sites"]) == 5

    def test_valid_classifications(self):
        data = load_json("discrepancy.json")
        valid_classes = {
            "observed_exceeds_design",
            "design_exceeds_observed",
            "consistent",
            "insufficient_data",
        }
        for site in data["sites"]:
            assert "classification" in site, f"{site.get('name', '?')} missing classification"
            assert site["classification"] in valid_classes, \
                f"{site['name']} has invalid classification: {site['classification']}"

    def test_has_ratios(self):
        """At least some sites should have computed discrepancy ratios."""
        data = load_json("discrepancy.json")
        has_ratio = sum(
            1 for s in data["sites"]
            if s.get("discrepancy_ratio") is not None
        )
        assert has_ratio >= 3, \
            f"Expected at least 3 sites with discrepancy ratios, got {has_ratio}"

    def test_sf_has_data(self):
        data = load_json("discrepancy.json")
        sf = next(s for s in data["sites"] if s["name"] == "San Francisco")
        assert sf["sds"] is not None, "SF should have SDS"
        assert sf["discrepancy_ratio"] is not None, "SF should have a discrepancy ratio"
        assert sf["discrepancy_ratio"] > 0, "SF discrepancy ratio should be positive"

    def test_ratio_formula_consistency(self):
        """Verify discrepancy ratio = (rate * max_mag / 10) / sds."""
        data = load_json("discrepancy.json")
        for site in data["sites"]:
            ratio = site.get("discrepancy_ratio")
            sds = site.get("sds")
            rate = site.get("annualized_rate")
            max_mag = site.get("max_observed_magnitude")
            if ratio is not None and sds and rate and max_mag:
                expected = (rate * max_mag / 10.0) / sds
                assert abs(ratio - expected) < 0.01, \
                    f"{site['name']} ratio {ratio} inconsistent with formula " \
                    f"(expected {expected:.4f})"

    def test_site_names_match(self):
        """Discrepancy site names should match other output files."""
        disc = load_json("discrepancy.json")
        design = load_json("site_design.json")
        disc_names = {s["name"] for s in disc["sites"]}
        design_names = {s["name"] for s in design["sites"]}
        assert disc_names == design_names


# ========================
# Cross-File Consistency
# ========================

class TestCrossFileConsistency:
    def test_time_span_matches(self):
        """Time span should be consistent across output files."""
        summary = load_json("catalog_summary.json")
        activity = load_json("site_activity.json")
        if "catalog_time_span_years" in activity:
            expected_years = summary["time_span_days"] / 365.25
            actual_years = activity["catalog_time_span_years"]
            assert abs(expected_years - actual_years) < 0.01, \
                f"Time span mismatch: summary implies {expected_years:.4f} years, " \
                f"activity says {actual_years:.4f} years"

    def test_bvalue_implies_valid_mean_magnitude(self):
        """Verify b-value is consistent with MLE: implied M_mean > Mc."""
        data = load_json("grid_bvalues.json")
        log10e = math.log10(math.e)
        for cell in data["cells"]:
            b = cell["b_value"]
            mc = cell["mc"]
            # For MLE b-value: M_mean = log10(e)/b + Mc - delta
            # The implied mean magnitude must exceed Mc
            implied_m_mean = log10e / b + mc - 0.05
            assert implied_m_mean >= mc, \
                f"Cell ({cell['lat_center']}, {cell['lon_center']}): " \
                f"implied M_mean={implied_m_mean:.3f} < Mc={mc}, " \
                f"indicates b-value computation error"
