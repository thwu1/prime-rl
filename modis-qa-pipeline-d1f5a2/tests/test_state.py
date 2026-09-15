#!/usr/bin/env python3
"""Tests for the multi-product satellite QA pipeline."""


import json
import os
import subprocess
import pytest
import requests

OUTPUT_PATH = "/app/output.jsonl"
REPORT_PATH = "/app/report.json"
_cached_outputs = None
_cached_report = None


def setup_module(module):
    """Run the pipeline tool before tests."""
    result = subprocess.run(
        ["python3", "/app/satqa.py", "/app/input.jsonl", "/app/filter.json", OUTPUT_PATH],
        capture_output=True, text=True, timeout=180, cwd="/app"
    )
    if result.returncode != 0:
        pytest.fail(
            f"Pipeline exited with code {result.returncode}.\n"
            f"STDERR: {result.stderr[:2000]}\nSTDOUT: {result.stdout[:2000]}"
        )


def load_outputs():
    global _cached_outputs
    if _cached_outputs is not None:
        return _cached_outputs
    outputs = {}
    with open(OUTPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                outputs[obj["id"]] = obj
    _cached_outputs = outputs
    return outputs


def load_report():
    global _cached_report
    if _cached_report is not None:
        return _cached_report
    with open(REPORT_PATH) as f:
        _cached_report = json.load(f)
    return _cached_report


def get_output(obs_id):
    outputs = load_outputs()
    assert obs_id in outputs, f"Missing output for {obs_id}"
    return outputs[obs_id]


def find_measurement(output, layer_name):
    for m in output["scaled_measurements"]:
        if m["layer"] == layer_name:
            return m
    pytest.fail(f"Missing measurement for layer {layer_name} in {output['id']}")


# ─── Basic structure ───

def test_output_file_exists():
    assert os.path.isfile(OUTPUT_PATH), "output.jsonl not found"


def test_output_has_10_observations():
    outputs = load_outputs()
    assert len(outputs) == 10, f"Expected 10 observations, got {len(outputs)}"


# ─── obs_001: MOD13A1.061 good quality land ───

def test_obs_001_quality_passed():
    out = get_output("obs_001")
    assert out["product"] == "MOD13A1.061"
    assert out["quality_passed"] is True


def test_obs_001_qa_decode():
    out = get_output("obs_001")
    assert out["qa_decode"]["MODLAND"]["value"] == 0
    assert out["qa_decode"]["MODLAND"]["description"] == "VI produced with good quality"
    assert out["qa_decode"]["VI Usefulness"]["value"] == 0
    assert out["qa_decode"]["VI Usefulness"]["description"] == "Highest quality"
    assert out["qa_decode"]["Aerosol Quantity"]["value"] == 1
    assert out["qa_decode"]["Aerosol Quantity"]["description"] == "Low"
    assert out["qa_decode"]["Adjacent cloud detected"]["value"] == 0
    assert out["qa_decode"]["Atmosphere BRDF Correction"]["value"] == 0
    assert out["qa_decode"]["Mixed Clouds"]["value"] == 0
    assert out["qa_decode"]["Land/Water Mask"]["value"] == 1
    assert out["qa_decode"]["Land/Water Mask"]["description"] == "Land (Nothing else but land)"
    assert out["qa_decode"]["Possible snow/ice"]["value"] == 0
    assert out["qa_decode"]["Possible shadow"]["value"] == 0


def test_obs_001_scaled_ndvi():
    out = get_output("obs_001")
    ndvi = find_measurement(out, "_500m_16_days_NDVI")
    assert abs(ndvi["scaled"] - 0.75) < 1e-6
    assert ndvi["is_fill"] is False


def test_obs_001_scaled_evi():
    out = get_output("obs_001")
    evi = find_measurement(out, "_500m_16_days_EVI")
    assert abs(evi["scaled"] - 0.42) < 1e-6
    assert evi["is_fill"] is False


# ─── obs_002: MOD13A1.061 bad quality water ───

def test_obs_002_quality_failed():
    out = get_output("obs_002")
    assert out["quality_passed"] is False


def test_obs_002_qa_decode():
    out = get_output("obs_002")
    assert out["qa_decode"]["MODLAND"]["value"] == 1
    assert out["qa_decode"]["MODLAND"]["description"] == "VI produced, but check other QA"
    assert out["qa_decode"]["VI Usefulness"]["value"] == 8
    assert out["qa_decode"]["Aerosol Quantity"]["value"] == 0
    assert out["qa_decode"]["Land/Water Mask"]["value"] == 4
    assert out["qa_decode"]["Land/Water Mask"]["description"] == "Ephemeral water"
    assert out["qa_decode"]["Possible snow/ice"]["value"] == 0
    assert out["qa_decode"]["Possible shadow"]["value"] == 0


# ─── obs_003: MOD11A1.061 good quality LST ───

def test_obs_003_quality_passed():
    out = get_output("obs_003")
    assert out["quality_passed"] is True


def test_obs_003_qa_decode():
    out = get_output("obs_003")
    assert out["qa_decode"]["MODLAND"]["value"] == 0
    assert out["qa_decode"]["Data Quality flag"]["value"] == 0
    assert out["qa_decode"]["Emis Error flag"]["value"] == 0
    assert out["qa_decode"]["LST Error Flag"]["value"] == 0


def test_obs_003_lst_scaled():
    out = get_output("obs_003")
    lst = find_measurement(out, "LST_Day_1km")
    assert abs(lst["scaled"] - 296.0) < 1e-6
    assert lst["is_fill"] is False
    assert lst["units"] == "Kelvin"


def test_obs_003_emissivity_scaled():
    """Emis_31 with scale+offset: 240*0.002+0.49=0.97"""
    out = get_output("obs_003")
    emis = find_measurement(out, "Emis_31")
    assert abs(emis["scaled"] - 0.97) < 1e-6
    assert emis["is_fill"] is False


# ─── obs_004: MOD11A1.061 cloud-affected fill ───

def test_obs_004_quality_failed():
    out = get_output("obs_004")
    assert out["quality_passed"] is False
    assert out["qa_decode"]["MODLAND"]["value"] == 2


def test_obs_004_lst_fill():
    out = get_output("obs_004")
    lst = find_measurement(out, "LST_Day_1km")
    assert lst["is_fill"] is True
    assert lst["scaled"] is None


# ─── obs_005: MOD09GA.061 clear land EVI ───

def test_obs_005_quality_passed():
    out = get_output("obs_005")
    assert out["quality_passed"] is True


def test_obs_005_qa_decode():
    out = get_output("obs_005")
    assert out["qa_decode"]["cloud state"]["value"] == 0
    assert out["qa_decode"]["cloud state"]["description"] == "clear"
    assert out["qa_decode"]["cloud shadow"]["value"] == 0
    assert out["qa_decode"]["land/water flag"]["value"] == 1
    assert out["qa_decode"]["land/water flag"]["description"] == "land"


def test_obs_005_reflectance_scaling():
    out = get_output("obs_005")
    b01 = find_measurement(out, "sur_refl_b01_1")
    assert abs(b01["scaled"] - 0.05) < 1e-8
    b02 = find_measurement(out, "sur_refl_b02_1")
    assert abs(b02["scaled"] - 0.30) < 1e-8
    b03 = find_measurement(out, "sur_refl_b03_1")
    assert abs(b03["scaled"] - 0.02) < 1e-8


def test_obs_005_evi_computation():
    out = get_output("obs_005")
    assert "EVI" in out["computed_indices"]
    expected = 2.5 * (0.30 - 0.05) / (0.30 + 6.0 * 0.05 - 7.5 * 0.02 + 1.0)
    assert abs(out["computed_indices"]["EVI"] - expected) < 1e-10


# ─── obs_006: MOD09GA.061 cloudy ───

def test_obs_006_quality_failed():
    out = get_output("obs_006")
    assert out["quality_passed"] is False


def test_obs_006_qa_decode():
    out = get_output("obs_006")
    assert out["qa_decode"]["cloud state"]["value"] == 1
    assert out["qa_decode"]["cloud state"]["description"] == "cloudy"
    assert out["qa_decode"]["land/water flag"]["value"] == 2
    assert out["qa_decode"]["cirrus detected"]["value"] == 2
    assert out["qa_decode"]["cirrus detected"]["description"] == "average"
    assert out["qa_decode"]["Pixel is adjacent to cloud"]["value"] == 1
    assert out["qa_decode"]["Pixel is adjacent to cloud"]["description"] == "yes"


def test_obs_006_evi_zero():
    """All bands have the same raw value (100), so NIR - Red = 0 and EVI = 0."""
    out = get_output("obs_006")
    assert "EVI" in out["computed_indices"]
    assert abs(out["computed_indices"]["EVI"] - 0.0) < 1e-10


# ─── obs_007: L08.002 clear land ───

def test_obs_007_quality_passed():
    out = get_output("obs_007")
    assert out["quality_passed"] is True


def test_obs_007_qa_decode():
    out = get_output("obs_007")
    assert out["qa_decode"]["Fill"]["value"] == 0
    assert out["qa_decode"]["Dilated Cloud"]["value"] == 0
    assert out["qa_decode"]["Cloud"]["value"] == 0
    assert out["qa_decode"]["Cloud Shadow"]["value"] == 0
    assert out["qa_decode"]["Clear"]["value"] == 1
    assert out["qa_decode"]["Water"]["value"] == 0
    assert out["qa_decode"]["Cloud Confidence"]["value"] == 0


# ─── obs_008: L08.002 cloudy ───

def test_obs_008_quality_failed():
    out = get_output("obs_008")
    assert out["quality_passed"] is False


def test_obs_008_qa_decode():
    out = get_output("obs_008")
    assert out["qa_decode"]["Cloud"]["value"] == 1
    assert out["qa_decode"]["Cloud"]["description"] == "high confidence cloud"
    assert out["qa_decode"]["Cloud Confidence"]["value"] == 3
    assert out["qa_decode"]["Cloud Confidence"]["description"] == "High confidence"
    assert out["qa_decode"]["Clear"]["value"] == 0
    assert out["qa_decode"]["Fill"]["value"] == 0


# ─── obs_009: MOD09GA.061 band fill → null EVI ───

def test_obs_009_quality_passed():
    out = get_output("obs_009")
    assert out["quality_passed"] is True


def test_obs_009_band_fill():
    out = get_output("obs_009")
    b01 = find_measurement(out, "sur_refl_b01_1")
    assert b01["is_fill"] is True
    assert b01["scaled"] is None


def test_obs_009_evi_null():
    out = get_output("obs_009")
    assert out["computed_indices"].get("EVI") is None


# ─── obs_010: MOD13A1.061 land with snow flag ───

def test_obs_010_quality_passed():
    """Snow flag is set but not in the filter → passes"""
    out = get_output("obs_010")
    assert out["quality_passed"] is True


def test_obs_010_qa_decode():
    out = get_output("obs_010")
    assert out["qa_decode"]["MODLAND"]["value"] == 0
    assert out["qa_decode"]["Land/Water Mask"]["value"] == 1
    assert out["qa_decode"]["Possible snow/ice"]["value"] == 1
    assert out["qa_decode"]["Possible snow/ice"]["description"] == "Yes"


def test_obs_010_ndvi_scaled():
    out = get_output("obs_010")
    ndvi = find_measurement(out, "_500m_16_days_NDVI")
    assert abs(ndvi["scaled"] - 0.85) < 1e-6
    assert ndvi["is_fill"] is False


# ─── Report ───

def test_report_exists():
    assert os.path.isfile(REPORT_PATH), "report.json not found"


def test_report_total():
    report = load_report()
    assert report["total"] == 10


def test_report_by_product_mod13a1():
    report = load_report()
    bp = report["by_product"]["MOD13A1.061"]
    assert bp["total"] == 3
    assert bp["passed"] == 2
    assert bp["failed"] == 1


def test_report_by_product_mod11a1():
    report = load_report()
    bp = report["by_product"]["MOD11A1.061"]
    assert bp["total"] == 2
    assert bp["passed"] == 1
    assert bp["failed"] == 1


def test_report_by_product_mod09ga():
    report = load_report()
    bp = report["by_product"]["MOD09GA.061"]
    assert bp["total"] == 3
    assert bp["passed"] == 2
    assert bp["failed"] == 1


def test_report_by_product_l08():
    report = load_report()
    bp = report["by_product"]["L08.002"]
    assert bp["total"] == 2
    assert bp["passed"] == 1
    assert bp["failed"] == 1


def test_report_fill_count():
    report = load_report()
    assert report["fill_count"] == 2


def test_report_indices_computed():
    report = load_report()
    assert report["indices_computed"]["EVI"] == 2


# ─── Cross-validation against AppEEARS decode endpoint ───

def test_cross_validate_mod09ga_decode():
    """Compare tool decode of qa=8721 against AppEEARS /quality/.../8721 endpoint."""
    out = get_output("obs_006")
    url = "https://appeears.earthdatacloud.nasa.gov/api/quality/MOD09GA.061/state_1km_1/8721"
    resp = requests.get(url, timeout=30)
    assert resp.status_code == 200, f"AppEEARS API returned {resp.status_code}"
    api_decode = resp.json()
    for field_name, api_info in api_decode.items():
        if field_name == "Binary Representation":
            continue
        assert field_name in out["qa_decode"], f"Missing field '{field_name}' in tool output"
        assert out["qa_decode"][field_name]["description"] == api_info["description"], (
            f"Description mismatch for '{field_name}': "
            f"tool='{out['qa_decode'][field_name]['description']}', "
            f"api='{api_info['description']}'"
        )


def test_cross_validate_mod11a1_decode():
    """Compare tool decode of qa=0 against AppEEARS decode endpoint."""
    out = get_output("obs_003")
    url = "https://appeears.earthdatacloud.nasa.gov/api/quality/MOD11A1.061/QC_Day/0"
    resp = requests.get(url, timeout=30)
    assert resp.status_code == 200, f"AppEEARS API returned {resp.status_code}"
    api_decode = resp.json()
    for field_name, api_info in api_decode.items():
        if field_name == "Binary Representation":
            continue
        assert field_name in out["qa_decode"], f"Missing field '{field_name}'"
        assert out["qa_decode"][field_name]["description"] == api_info["description"], (
            f"Description mismatch for '{field_name}': "
            f"tool='{out['qa_decode'][field_name]['description']}', "
            f"api='{api_info['description']}'"
        )
