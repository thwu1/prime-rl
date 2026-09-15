
import json
import os
import pytest

OUTPUT_PATH = "/app/output/fusion_plan.json"


@pytest.fixture(scope="module")
def plan():
    assert os.path.exists(OUTPUT_PATH), f"Output file not found at {OUTPUT_PATH}"
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    return data


def find_subquery(plan_entry, dataset_id):
    """Find a subquery for a given dataset within a query entry."""
    for sq in plan_entry["subqueries"]:
        if sq["dataset_id"] == dataset_id:
            return sq
    pytest.fail(f"Dataset '{dataset_id}' not found in subqueries")


# =========================================================
# Q1: SST unit harmonization — Kelvin + Celsius + buoy
# =========================================================


class TestQ1SSTHarmonize:
    def test_has_three_subqueries(self, plan):
        assert "sst_harmonize" in plan
        assert len(plan["sst_harmonize"]["subqueries"]) == 3

    def test_mur_griddap(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert sq["query_type"] == "griddap"

    def test_mur_no_split(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert sq["antimeridian_split"] is False
        assert len(sq["urls"]) == 1

    def test_mur_stride_25(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert sq["constraints"]["latitude"]["stride"] == 25
        assert sq["constraints"]["longitude"][0]["stride"] == 25

    def test_mur_lon_converted_to_0_360(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        lon = sq["constraints"]["longitude"][0]
        assert abs(lon["start"] - 220.0) < 1.0
        assert abs(lon["stop"] - 240.0) < 1.0

    def test_mur_ancillary_detected(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert "analysis_error" in sq["ancillary_variables"]
        assert "mask" in sq["ancillary_variables"]

    def test_mur_unit_conversion_kelvin_to_celsius(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert "analysed_sst" in sq["unit_conversions"]
        conv = sq["unit_conversions"]["analysed_sst"]
        assert conv["source_unit"] == "kelvin"
        assert conv["target_unit"] == "degree_C"
        assert abs(conv["offset"] - (-273.15)) < 0.01
        assert abs(conv["scale"] - 1.0) < 0.01

    def test_mur_url_has_ancillary_vars(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        url = sq["urls"][0]
        assert "analysis_error[" in url
        assert "mask[" in url

    def test_oisst_griddap(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "oisst_avhrr")
        assert sq["query_type"] == "griddap"
        assert sq["antimeridian_split"] is False

    def test_oisst_stride_1(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "oisst_avhrr")
        assert sq["constraints"]["latitude"]["stride"] == 1
        assert sq["constraints"]["longitude"][0]["stride"] == 1

    def test_oisst_zlev_constraint(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "oisst_avhrr")
        assert "zlev" in sq["constraints"]
        assert abs(sq["constraints"]["zlev"]["value"] - 0.0) < 0.01

    def test_oisst_no_unit_conversion(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "oisst_avhrr")
        assert len(sq["unit_conversions"]) == 0

    def test_oisst_no_ancillary(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "oisst_avhrr")
        assert len(sq["ancillary_variables"]) == 0

    def test_ndbc_tabledap(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "ndbc_stdmet")
        assert sq["query_type"] == "tabledap"
        assert sq["antimeridian_split"] is False
        assert len(sq["urls"]) == 1

    def test_ndbc_no_unit_conversion(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "ndbc_stdmet")
        assert len(sq["unit_conversions"]) == 0

    def test_ndbc_url_tabledap_syntax(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "ndbc_stdmet")
        url = sq["urls"][0]
        assert "tabledap" in url
        assert "ndbc_stdmet" in url
        assert ">=" in url

    def test_unit_harmonization_target(self, plan):
        targets = plan["sst_harmonize"]["unit_harmonization_target"]
        assert "sea_surface_temperature" in targets
        assert targets["sea_surface_temperature"] == "degree_C"

    def test_mur_server(self, plan):
        sq = find_subquery(plan["sst_harmonize"], "mur_sst")
        assert "coastwatch" in sq["server"]

    def test_full_spatial_coverage(self, plan):
        for sq in plan["sst_harmonize"]["subqueries"]:
            assert sq["spatial_coverage"]["latitude_fraction"] == pytest.approx(
                1.0, abs=0.01
            )
            assert sq["spatial_coverage"]["longitude_fraction"] == pytest.approx(
                1.0, abs=0.01
            )


# =========================================================
# Q2: Quality-aware chlorophyll + temporal alignment
# =========================================================


class TestQ2QualityChlor:
    def test_has_two_subqueries(self, plan):
        assert "quality_chlor" in plan
        assert len(plan["quality_chlor"]["subqueries"]) == 2

    def test_chlor_ancillary_detected(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        assert "quality_flags" in sq["ancillary_variables"]

    def test_chlor_altitude_constraint(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        assert "altitude" in sq["constraints"]
        assert abs(sq["constraints"]["altitude"]["value"] - 0.0) < 0.01

    def test_chlor_stride_1(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        assert sq["constraints"]["latitude"]["stride"] == 1
        assert sq["constraints"]["longitude"][0]["stride"] == 1

    def test_chlor_url_has_quality_flags(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        url = sq["urls"][0]
        assert "quality_flags[" in url

    def test_chlor_server_upwell(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        assert "upwell" in sq["server"]

    def test_mur_stride_10(self, plan):
        sq = find_subquery(plan["quality_chlor"], "mur_sst")
        assert sq["constraints"]["latitude"]["stride"] == 10
        assert sq["constraints"]["longitude"][0]["stride"] == 10

    def test_mur_ancillary(self, plan):
        sq = find_subquery(plan["quality_chlor"], "mur_sst")
        assert "analysis_error" in sq["ancillary_variables"]
        assert "mask" in sq["ancillary_variables"]

    def test_no_splits(self, plan):
        for sq in plan["quality_chlor"]["subqueries"]:
            assert sq["antimeridian_split"] is False
            assert len(sq["urls"]) == 1

    def test_temporal_alignment_mismatch(self, plan):
        ta = plan["quality_chlor"]["temporal_alignment"]
        assert ta["chlor_viirs"]["resolution_seconds"] == pytest.approx(691200.0)
        assert ta["chlor_viirs"]["resolution_label"] == "8-day"
        assert ta["mur_sst"]["resolution_seconds"] == pytest.approx(86400.0)
        assert ta["mur_sst"]["resolution_label"] == "daily"

    def test_no_unit_harmonization(self, plan):
        targets = plan["quality_chlor"]["unit_harmonization_target"]
        assert len(targets) == 0

    def test_chlor_full_coverage(self, plan):
        sq = find_subquery(plan["quality_chlor"], "chlor_viirs")
        assert sq["spatial_coverage"]["latitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )
        assert sq["spatial_coverage"]["longitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )


# =========================================================
# Q3: Antimeridian wrap with grid + table
# =========================================================


class TestQ3AntimeridianWrap:
    def test_has_three_subqueries(self, plan):
        assert "antimeridian_wrap" in plan
        assert len(plan["antimeridian_wrap"]["subqueries"]) == 3

    def test_mur_split_detected(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "mur_sst")
        assert sq["antimeridian_split"] is True
        assert len(sq["urls"]) == 2

    def test_mur_stride_100(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "mur_sst")
        assert sq["constraints"]["latitude"]["stride"] == 100
        for lr in sq["constraints"]["longitude"]:
            assert lr["stride"] == 100

    def test_mur_lon_ranges_split(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "mur_sst")
        lon_ranges = sq["constraints"]["longitude"]
        assert len(lon_ranges) == 2
        sorted_ranges = sorted(lon_ranges, key=lambda r: r["start"])
        # Range 1: [~0, 170]
        assert sorted_ranges[0]["start"] < 5
        assert abs(sorted_ranges[0]["stop"] - 170.0) < 1.0
        # Range 2: [~190, ~360]
        assert abs(sorted_ranges[1]["start"] - 190.0) < 1.0
        assert sorted_ranges[1]["stop"] > 355

    def test_mur_unit_conversion(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "mur_sst")
        assert "analysed_sst" in sq["unit_conversions"]
        conv = sq["unit_conversions"]["analysed_sst"]
        assert conv["source_unit"] == "kelvin"
        assert conv["target_unit"] == "degree_C"
        assert abs(conv["offset"] - (-273.15)) < 0.01

    def test_oisst_split_detected(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "oisst_avhrr")
        assert sq["antimeridian_split"] is True
        assert len(sq["urls"]) == 2

    def test_oisst_zlev(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "oisst_avhrr")
        assert "zlev" in sq["constraints"]

    def test_oisst_lon_ranges_split(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "oisst_avhrr")
        lon_ranges = sq["constraints"]["longitude"]
        assert len(lon_ranges) == 2
        sorted_ranges = sorted(lon_ranges, key=lambda r: r["start"])
        assert sorted_ranges[0]["start"] < 5
        assert abs(sorted_ranges[0]["stop"] - 170.0) < 1.0
        assert abs(sorted_ranges[1]["start"] - 190.0) < 1.0
        assert sorted_ranges[1]["stop"] > 355

    def test_oisst_no_unit_conversion(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "oisst_avhrr")
        assert len(sq["unit_conversions"]) == 0

    def test_argo_no_split(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "argo_profile")
        assert sq["antimeridian_split"] is False
        assert len(sq["urls"]) == 1

    def test_argo_tabledap(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "argo_profile")
        assert sq["query_type"] == "tabledap"

    def test_argo_server_upwell(self, plan):
        sq = find_subquery(plan["antimeridian_wrap"], "argo_profile")
        assert "upwell" in sq["server"]

    def test_unit_harmonization_target(self, plan):
        targets = plan["antimeridian_wrap"]["unit_harmonization_target"]
        assert "sea_surface_temperature" in targets
        assert targets["sea_surface_temperature"] == "degree_C"

    def test_griddap_urls_have_bracket_syntax(self, plan):
        for sq in plan["antimeridian_wrap"]["subqueries"]:
            if sq["query_type"] == "griddap":
                for url in sq["urls"]:
                    assert "[(" in url

    def test_temporal_alignment(self, plan):
        ta = plan["antimeridian_wrap"]["temporal_alignment"]
        assert ta["mur_sst"]["resolution_label"] == "daily"
        assert ta["oisst_avhrr"]["resolution_label"] == "daily"
        assert ta["argo_profile"]["resolution_label"] == "irregular"
        assert ta["argo_profile"]["resolution_seconds"] is None


# =========================================================
# Q4: Coverage gap detection
# =========================================================


class TestQ4CoverageAssess:
    def test_has_three_subqueries(self, plan):
        assert "coverage_assess" in plan
        assert len(plan["coverage_assess"]["subqueries"]) == 3

    def test_mur_full_lat_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "mur_sst")
        assert sq["spatial_coverage"]["latitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )

    def test_mur_full_lon_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "mur_sst")
        assert sq["spatial_coverage"]["longitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )

    def test_chlor_partial_lat_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "chlor_viirs")
        # chlor_viirs lat [-60, 60], query [-70, 70]: overlap=120, range=140, frac=6/7
        expected = 6.0 / 7.0
        assert sq["spatial_coverage"]["latitude_fraction"] == pytest.approx(
            expected, abs=0.01
        )

    def test_chlor_full_lon_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "chlor_viirs")
        assert sq["spatial_coverage"]["longitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )

    def test_argo_partial_lat_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "argo_profile")
        # argo lat [-65, 65], query [-70, 70]: overlap=130, range=140, frac=13/14
        expected = 13.0 / 14.0
        assert sq["spatial_coverage"]["latitude_fraction"] == pytest.approx(
            expected, abs=0.01
        )

    def test_argo_full_lon_coverage(self, plan):
        sq = find_subquery(plan["coverage_assess"], "argo_profile")
        assert sq["spatial_coverage"]["longitude_fraction"] == pytest.approx(
            1.0, abs=0.01
        )

    def test_chlor_altitude_present(self, plan):
        sq = find_subquery(plan["coverage_assess"], "chlor_viirs")
        assert "altitude" in sq["constraints"]

    def test_chlor_ancillary(self, plan):
        sq = find_subquery(plan["coverage_assess"], "chlor_viirs")
        assert "quality_flags" in sq["ancillary_variables"]

    def test_mur_stride_50(self, plan):
        sq = find_subquery(plan["coverage_assess"], "mur_sst")
        assert sq["constraints"]["latitude"]["stride"] == 50
        assert sq["constraints"]["longitude"][0]["stride"] == 50

    def test_no_splits(self, plan):
        for sq in plan["coverage_assess"]["subqueries"]:
            assert sq["antimeridian_split"] is False

    def test_temporal_alignment_heterogeneous(self, plan):
        ta = plan["coverage_assess"]["temporal_alignment"]
        assert ta["mur_sst"]["resolution_label"] == "daily"
        assert ta["chlor_viirs"]["resolution_label"] == "8-day"
        assert ta["argo_profile"]["resolution_label"] == "irregular"

    def test_no_unit_harmonization(self, plan):
        targets = plan["coverage_assess"]["unit_harmonization_target"]
        assert len(targets) == 0


# =========================================================
# Cross-cutting structural tests
# =========================================================


class TestStructural:
    def test_all_queries_present(self, plan):
        expected = {"sst_harmonize", "quality_chlor", "antimeridian_wrap", "coverage_assess"}
        assert expected == set(plan.keys())

    def test_all_subqueries_have_required_fields(self, plan):
        required = {
            "dataset_id",
            "server",
            "query_type",
            "variables",
            "ancillary_variables",
            "urls",
            "antimeridian_split",
            "constraints",
            "unit_conversions",
            "spatial_coverage",
        }
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                missing = required - set(sq.keys())
                assert not missing, f"{qid}/{sq['dataset_id']} missing: {missing}"

    def test_all_entries_have_temporal_alignment(self, plan):
        for qid, entry in plan.items():
            assert "temporal_alignment" in entry
            assert "unit_harmonization_target" in entry

    def test_griddap_urls_bracket_syntax(self, plan):
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                if sq["query_type"] == "griddap":
                    for url in sq["urls"]:
                        assert "[(" in url, f"Griddap URL missing [( bracket syntax: {url}"

    def test_tabledap_urls_filter_syntax(self, plan):
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                if sq["query_type"] == "tabledap":
                    for url in sq["urls"]:
                        assert ">=" in url or "<=" in url, (
                            f"Tabledap URL missing filter syntax: {url}"
                        )

    def test_server_urls_valid(self, plan):
        valid_servers = {
            "https://coastwatch.pfeg.noaa.gov/erddap",
            "https://upwell.pfeg.noaa.gov/erddap",
        }
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                assert sq["server"] in valid_servers, (
                    f"Invalid server for {sq['dataset_id']}: {sq['server']}"
                )

    def test_urls_contain_correct_server(self, plan):
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                for url in sq["urls"]:
                    assert sq["server"] in url, (
                        f"URL does not match server for {sq['dataset_id']}"
                    )

    def test_urls_contain_dataset_id(self, plan):
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                for url in sq["urls"]:
                    assert sq["dataset_id"] in url, (
                        f"URL missing dataset_id for {sq['dataset_id']}"
                    )

    def test_coverage_fractions_in_valid_range(self, plan):
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                lat_f = sq["spatial_coverage"]["latitude_fraction"]
                lon_f = sq["spatial_coverage"]["longitude_fraction"]
                assert 0.0 <= lat_f <= 1.0, f"Lat coverage out of range: {lat_f}"
                assert 0.0 <= lon_f <= 1.0, f"Lon coverage out of range: {lon_f}"

    def test_ancillary_vars_in_griddap_urls(self, plan):
        """Verify that declared ancillary variables appear in griddap URLs."""
        for qid, entry in plan.items():
            for sq in entry["subqueries"]:
                if sq["query_type"] == "griddap" and sq["ancillary_variables"]:
                    for anc_var in sq["ancillary_variables"]:
                        for url in sq["urls"]:
                            assert anc_var in url, (
                                f"Ancillary var '{anc_var}' not in URL"
                            )
