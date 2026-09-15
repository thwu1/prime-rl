#!/usr/bin/env python3
"""Tests for SSURGO Soil Report Generator."""


import json
import subprocess
import sys
import time
import pytest
import requests

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
MAX_RETRIES = 3
RETRY_BACKOFF = 3

MUKEYS = ["49456", "49457", "49458"]


def query_sda(sql):
    """Query the SDA REST API directly with retry.

    Uses JSON+COLUMNNAME format: first row = column headers, rest = data.
    Converts to list of dicts.
    """
    session = requests.Session()
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(
                SDA_URL,
                json={"query": sql, "format": "JSON+COLUMNNAME"},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                table = data.get("Table") or data.get("table") or []
                if len(table) < 2:
                    return []
                headers = table[0]
                return [dict(zip(headers, row)) for row in table[1:]]
            return []
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
    pytest.skip(f"SDA API unavailable after {MAX_RETRIES} retries: {last_exc}")


def run_tool(mukeys, output_path, depth_top=None, depth_bottom=None, timeout=480):
    """Run the soil report tool."""
    cmd = ["python3", "/app/soil_report.py", "--mukeys", mukeys, "--output", output_path]
    if depth_top is not None:
        cmd += ["--depth-top", str(depth_top)]
    if depth_bottom is not None:
        cmd += ["--depth-bottom", str(depth_bottom)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def reference_classify_texture(sand, silt, clay):
    """Reference USDA Soil Texture Triangle classification."""
    if sand is None or silt is None or clay is None:
        return None
    if silt + 1.5 * clay < 15:
        return "Sand"
    if silt + 2 * clay < 30:
        return "Loamy sand"
    if (clay >= 7 and clay < 20 and sand > 52 and silt + 2 * clay >= 30) or \
       (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "Sandy loam"
    if clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52:
        return "Loam"
    if (silt >= 50 and clay >= 12 and clay < 27) or \
       (silt >= 50 and silt < 80 and clay < 12):
        return "Silt loam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if clay >= 20 and clay < 35 and silt < 28 and sand >= 45:
        return "Sandy clay loam"
    if clay >= 27 and clay < 40 and sand > 20 and sand <= 45:
        return "Clay loam"
    if clay >= 27 and clay < 40 and sand <= 20:
        return "Silty clay loam"
    if clay >= 35 and sand >= 45:
        return "Sandy clay"
    if clay >= 40 and silt >= 40:
        return "Silty clay"
    if clay >= 40:
        return "Clay"
    return None


def safe_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    return float(s)


def safe_int(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    return int(float(s))


# ============================================================
# Session-scoped fixtures
# ============================================================

@pytest.fixture(scope="session")
def check_api():
    """Verify the SDA API is reachable before running tests."""
    try:
        resp = requests.post(
            SDA_URL,
            json={"query": "SELECT TOP 1 mukey FROM mapunit", "format": "JSON+COLUMNNAME"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        assert "Table" in data or "table" in data
    except Exception as exc:
        pytest.skip(f"SDA API unreachable: {exc}")


@pytest.fixture(scope="session")
def report_main(check_api, tmp_path_factory):
    """Run the tool for all 3 mukeys -- shared by most tests."""
    tmp = tmp_path_factory.mktemp("rmain")
    output = str(tmp / "report.json")
    mukeys_str = ",".join(MUKEYS)
    result = run_tool(mukeys_str, output, timeout=480)
    assert result.returncode == 0, \
        f"Tool failed for mukeys {mukeys_str}:\nstdout: {result.stdout[-3000:]}\nstderr: {result.stderr[-3000:]}"
    with open(output) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def report_custom_depth(check_api, tmp_path_factory):
    """Run the tool with custom depth range."""
    tmp = tmp_path_factory.mktemp("rdepth")
    output = str(tmp / "report.json")
    result = run_tool("49458", output, depth_top=25, depth_bottom=75, timeout=480)
    assert result.returncode == 0, \
        f"Tool failed for custom depth:\nstdout: {result.stdout[-3000:]}\nstderr: {result.stderr[-3000:]}"
    with open(output) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def raw_hz_49456(check_api):
    return query_sda("""
        SELECT ch.cokey, ch.hzdept_r, ch.hzdepb_r, ch.awc_r, ch.ksat_r, ch.dbthirdbar_r
        FROM chorizon ch INNER JOIN component c ON ch.cokey = c.cokey
        WHERE c.mukey = '49456'
        ORDER BY ch.cokey, ch.hzdept_r
    """)


@pytest.fixture(scope="session")
def raw_rest_49456(check_api):
    return query_sda("""
        SELECT cr.cokey, cr.resdept_r
        FROM corestrictions cr INNER JOIN component c ON cr.cokey = c.cokey
        WHERE c.mukey = '49456'
    """)


@pytest.fixture(scope="session")
def raw_hz_49458(check_api):
    return query_sda("""
        SELECT ch.cokey, ch.hzdept_r, ch.hzdepb_r, ch.awc_r
        FROM chorizon ch INNER JOIN component c ON ch.cokey = c.cokey
        WHERE c.mukey = '49458'
        ORDER BY ch.cokey, ch.hzdept_r
    """)


@pytest.fixture(scope="session")
def raw_interp_49456(check_api):
    return query_sda("""
        SELECT ci.cokey, ci.interphr, ci.interphrc
        FROM cointerp ci INNER JOIN component c ON ci.cokey = c.cokey
        WHERE c.mukey = '49456'
        AND ci.mrulename = 'ENG - Septic Tank Absorption Fields'
        AND ci.rulename = ci.mrulename
    """)


# ============================================================
# 1. Texture Triangle Reference Sanity
# ============================================================

class TestTextureReference:
    """Verify the reference texture classification against known cases."""

    @pytest.mark.parametrize("sand,silt,clay,expected", [
        (92, 5, 3, "Sand"),
        (82, 10, 8, "Loamy sand"),
        (65, 20, 15, "Sandy loam"),
        (40, 40, 20, "Loam"),
        (20, 65, 15, "Silt loam"),
        (5, 88, 7, "Silt"),
        (55, 15, 30, "Sandy clay loam"),
        (30, 35, 35, "Clay loam"),
        (10, 55, 35, "Silty clay loam"),
        (50, 5, 45, "Sandy clay"),
        (5, 50, 45, "Silty clay"),
        (20, 30, 50, "Clay"),
    ])
    def test_known_case(self, sand, silt, clay, expected):
        assert reference_classify_texture(sand, silt, clay) == expected


# ============================================================
# 2. Tool Texture Classification vs Reference
# ============================================================

class TestToolTexture:
    """Verify the tool's texture classifications match the reference."""

    def test_texture_matches_reference(self, report_main):
        checked = 0
        for mukey in MUKEYS:
            if mukey not in report_main["mapunits"]:
                continue
            mu_data = report_main["mapunits"][mukey]
            for cokey, comp in mu_data["components"].items():
                for hz in comp["horizons"]:
                    sand = hz.get("sandtotal_r")
                    silt = hz.get("silttotal_r")
                    clay = hz.get("claytotal_r")
                    tex = hz.get("texture_class")

                    if sand is None or silt is None or clay is None:
                        assert tex is None, \
                            f"texture_class should be null when inputs null (cokey {cokey})"
                        continue

                    expected = reference_classify_texture(sand, silt, clay)
                    assert tex == expected, \
                        f"cokey {cokey}: ({sand},{silt},{clay}) -> '{tex}', expected '{expected}'"
                    checked += 1

        assert checked > 0, "No horizons with sand/silt/clay data found"

    def test_valid_texture_classes(self, report_main):
        """All texture classes must be one of the 12 valid USDA classes or null."""
        valid = {
            "Sand", "Loamy sand", "Sandy loam", "Loam",
            "Silt loam", "Silt", "Sandy clay loam", "Clay loam",
            "Silty clay loam", "Sandy clay", "Silty clay", "Clay"
        }
        for mukey in MUKEYS:
            if mukey not in report_main["mapunits"]:
                continue
            for cokey, comp in report_main["mapunits"][mukey]["components"].items():
                for hz in comp["horizons"]:
                    tex = hz.get("texture_class")
                    if tex is not None:
                        assert tex in valid, f"Invalid texture class: '{tex}'"


# ============================================================
# 3. Depth-Weighted Average Verification
# ============================================================

class TestDepthWeighting:
    """Verify depth-weighted averages match independent computation."""

    def test_awc_depth_weighted(self, report_main, raw_hz_49456, raw_rest_49456):
        mukey = "49456"
        # Build restriction map
        rest_map = {}
        for r in raw_rest_49456:
            ck = str(r["cokey"]).strip()
            d = safe_float(r.get("resdept_r"))
            if d is not None:
                rest_map[ck] = min(rest_map.get(ck, float("inf")), d)

        # Group horizons by cokey
        hz_by_ck = {}
        for h in raw_hz_49456:
            ck = str(h["cokey"]).strip()
            hz_by_ck.setdefault(ck, []).append(h)

        checked = 0
        for ck, hz_list in hz_by_ck.items():
            if ck not in report_main["mapunits"][mukey]["components"]:
                continue

            eff_bottom = 100.0
            if ck in rest_map:
                eff_bottom = min(100.0, rest_map[ck])

            total_t = 0.0
            w_sum = 0.0
            for h in hz_list:
                ht = safe_int(h.get("hzdept_r"))
                hb = safe_int(h.get("hzdepb_r"))
                awc = safe_float(h.get("awc_r"))
                if ht is None or hb is None or awc is None:
                    continue
                ot = max(ht, 0)
                ob = min(hb, eff_bottom)
                t = ob - ot
                if t <= 0:
                    continue
                total_t += t
                w_sum += awc * t

            expected = w_sum / total_t if total_t > 0 else None
            actual = report_main["mapunits"][mukey]["components"][ck]["depth_weighted"]["awc"]

            if expected is None:
                assert actual is None, f"Expected null AWC for cokey {ck}, got {actual}"
            else:
                assert actual is not None, f"Expected non-null AWC for cokey {ck}"
                assert abs(actual - expected) < 1e-4, \
                    f"AWC mismatch for cokey {ck}: got {actual}, expected {expected}"
                checked += 1

        assert checked > 0, "No components with computable AWC found"


# ============================================================
# 4. Output Structure Validation
# ============================================================

class TestStructure:
    """Validate the output JSON structure."""

    def test_top_level_keys(self, report_main):
        assert "query_params" in report_main
        assert "mapunits" in report_main

    def test_query_params(self, report_main):
        qp = report_main["query_params"]
        assert set(qp["mukeys"]) == set(MUKEYS)
        assert qp["depth_top_cm"] == 0
        assert qp["depth_bottom_cm"] == 100

    def test_mapunit_presence(self, report_main):
        for mk in MUKEYS:
            assert mk in report_main["mapunits"], f"Missing mukey {mk}"

    def test_mapunit_fields(self, report_main):
        for mk in MUKEYS:
            mu = report_main["mapunits"][mk]
            assert isinstance(mu["muname"], str)
            assert "mukind" in mu
            assert "components" in mu
            assert "aggregated" in mu
            assert "interpretations" in mu

    def test_aggregated_keys(self, report_main):
        for mk in MUKEYS:
            agg = report_main["mapunits"][mk]["aggregated"]
            for key in ["wtd_avg_awc", "wtd_avg_ksat", "wtd_avg_bd",
                        "dominant_hydgrp", "dominant_drainagecl"]:
                assert key in agg, f"Missing aggregated key {key} for mukey {mk}"

    def test_component_structure(self, report_main):
        for mk in MUKEYS:
            mu = report_main["mapunits"][mk]
            assert len(mu["components"]) > 0, f"No components for mukey {mk}"

            for cokey, comp in mu["components"].items():
                assert "compname" in comp
                assert isinstance(comp["comppct_r"], int), \
                    f"comppct_r should be int, got {type(comp['comppct_r'])}"
                assert "horizons" in comp
                assert "depth_weighted" in comp

                dw = comp["depth_weighted"]
                for key in ["awc", "ksat", "dbthirdbar"]:
                    assert key in dw, f"Missing depth_weighted key {key}"

    def test_horizons_sorted(self, report_main):
        for mk in MUKEYS:
            for cokey, comp in report_main["mapunits"][mk]["components"].items():
                depths = [h["hzdept_r"] for h in comp["horizons"]
                          if h["hzdept_r"] is not None]
                assert depths == sorted(depths), \
                    f"Horizons not sorted for cokey {cokey}"

    def test_horizon_fields(self, report_main):
        required = {"hzdept_r", "hzdepb_r", "sandtotal_r", "silttotal_r",
                     "claytotal_r", "texture_class", "awc_r", "ksat_r", "dbthirdbar_r"}
        for mk in MUKEYS:
            for cokey, comp in report_main["mapunits"][mk]["components"].items():
                for hz in comp["horizons"]:
                    for key in required:
                        assert key in hz, f"Missing horizon key {key} for cokey {cokey}"

    def test_interpretation_structure(self, report_main):
        mu = report_main["mapunits"]["49456"]
        ikey = "ENG - Septic Tank Absorption Fields"
        assert ikey in mu["interpretations"], "Missing septic interpretation"
        interp = mu["interpretations"][ikey]
        assert "dominant_rating_class" in interp
        assert "weighted_rating_value" in interp
        assert "components" in interp


# ============================================================
# 5. Aggregation Consistency
# ============================================================

class TestAggregation:
    """Verify mapunit aggregations are consistent with component data."""

    def test_weighted_avg_consistency(self, report_main):
        mu = report_main["mapunits"]["49456"]
        prop_map = {"awc": "wtd_avg_awc", "ksat": "wtd_avg_ksat", "dbthirdbar": "wtd_avg_bd"}

        for prop, agg_key in prop_map.items():
            sum_pct = 0
            sum_val = 0.0
            for cokey, comp in mu["components"].items():
                val = comp["depth_weighted"][prop]
                pct = comp["comppct_r"]
                if val is not None and pct is not None:
                    sum_pct += pct
                    sum_val += pct * val

            if sum_pct > 0:
                expected = sum_val / sum_pct
                actual = mu["aggregated"][agg_key]
                assert actual is not None, f"Aggregated {agg_key} should not be null"
                assert abs(actual - expected) < 1e-6, \
                    f"{agg_key}: got {actual}, expected {expected}"

    def test_dominant_hydgrp_consistency(self, report_main):
        mu = report_main["mapunits"]["49456"]
        grp_pct = {}
        for cokey, comp in mu["components"].items():
            hg = comp.get("hydgrp")
            pct = comp.get("comppct_r")
            if hg and pct:
                grp_pct[hg] = grp_pct.get(hg, 0) + pct

        if grp_pct:
            max_pct = max(grp_pct.values())
            candidates = sorted([g for g, p in grp_pct.items() if p == max_pct])
            expected = candidates[0]
            assert mu["aggregated"]["dominant_hydgrp"] == expected, \
                f"Dominant hydgrp: got {mu['aggregated']['dominant_hydgrp']}, expected {expected}"

    def test_dominant_drainagecl_consistency(self, report_main):
        mu = report_main["mapunits"]["49456"]
        cls_pct = {}
        for cokey, comp in mu["components"].items():
            dc = comp.get("drainagecl")
            pct = comp.get("comppct_r")
            if dc and pct:
                cls_pct[dc] = cls_pct.get(dc, 0) + pct

        if cls_pct:
            max_pct = max(cls_pct.values())
            candidates = sorted([c for c, p in cls_pct.items() if p == max_pct])
            expected = candidates[0]
            assert mu["aggregated"]["dominant_drainagecl"] == expected


# ============================================================
# 6. Custom Depth Range
# ============================================================

class TestDepthRange:
    """Test custom depth range parameter."""

    def test_query_params_reflect_custom_depth(self, report_custom_depth):
        assert report_custom_depth["query_params"]["depth_top_cm"] == 25
        assert report_custom_depth["query_params"]["depth_bottom_cm"] == 75

    def test_custom_depth_awc(self, report_custom_depth, raw_hz_49458):
        mukey = "49458"
        hz_by_ck = {}
        for h in raw_hz_49458:
            ck = str(h["cokey"]).strip()
            hz_by_ck.setdefault(ck, []).append(h)

        checked = 0
        for ck, hz_list in hz_by_ck.items():
            if ck not in report_custom_depth["mapunits"][mukey]["components"]:
                continue

            # No restriction depth correction needed for this mukey in the 25-75 range
            # (restrictions for 49458 components are at 44cm for cokey 26725909)
            comp_data = report_custom_depth["mapunits"][mukey]["components"][ck]
            rest_depth = comp_data.get("restriction_depth_cm")

            eff_bottom = 75.0
            if rest_depth is not None:
                eff_bottom = min(75.0, rest_depth)

            total_t = 0.0
            w_sum = 0.0
            for h in hz_list:
                ht = safe_int(h.get("hzdept_r"))
                hb = safe_int(h.get("hzdepb_r"))
                awc = safe_float(h.get("awc_r"))
                if ht is None or hb is None or awc is None:
                    continue
                ot = max(ht, 25)
                ob = min(hb, eff_bottom)
                t = ob - ot
                if t <= 0:
                    continue
                total_t += t
                w_sum += awc * t

            expected = w_sum / total_t if total_t > 0 else None
            actual = comp_data["depth_weighted"]["awc"]

            if expected is None:
                assert actual is None
            else:
                assert actual is not None
                assert abs(actual - expected) < 1e-4, \
                    f"Custom depth AWC mismatch for cokey {ck}: {actual} vs {expected}"
                checked += 1

        assert checked > 0, "No components with computable AWC in 25-75cm range"


# ============================================================
# 7. Multiple Mukeys
# ============================================================

class TestMultipleMukeys:
    """Test handling of multiple map unit keys."""

    def test_three_mukeys_present(self, report_main):
        assert len(report_main["mapunits"]) == 3
        for mk in MUKEYS:
            assert mk in report_main["mapunits"], f"Missing mukey {mk}"

    def test_three_mukeys_have_data(self, report_main):
        for mk in MUKEYS:
            mu = report_main["mapunits"][mk]
            assert mu["muname"] is not None
            assert len(mu["components"]) > 0, f"No components for mukey {mk}"

    def test_three_mukeys_aggregated(self, report_main):
        for mk in MUKEYS:
            agg = report_main["mapunits"][mk]["aggregated"]
            assert "wtd_avg_awc" in agg
            assert "dominant_hydgrp" in agg


# ============================================================
# 8. Interpretation Data
# ============================================================

class TestInterpretation:
    """Test soil interpretation processing."""

    def test_interp_values_match_api(self, report_main, raw_interp_49456):
        mukey = "49456"
        api_interps = {}
        for r in raw_interp_49456:
            ck = str(r["cokey"]).strip()
            api_interps[ck] = {
                "rating_class": r.get("interphrc"),
                "rating_value": safe_float(r.get("interphr"))
            }

        ikey = "ENG - Septic Tank Absorption Fields"
        tool_interps = report_main["mapunits"][mukey]["interpretations"][ikey]["components"]

        for ck, api_data in api_interps.items():
            if ck in tool_interps:
                assert tool_interps[ck]["rating_class"] == api_data["rating_class"], \
                    f"Rating class mismatch for cokey {ck}"
                if api_data["rating_value"] is not None and \
                   tool_interps[ck]["rating_value"] is not None:
                    assert abs(tool_interps[ck]["rating_value"] - api_data["rating_value"]) < 1e-4

    def test_dominant_excludes_not_rated(self, report_main):
        mukey = "49456"
        ikey = "ENG - Septic Tank Absorption Fields"
        interp = report_main["mapunits"][mukey]["interpretations"][ikey]
        dom = interp["dominant_rating_class"]
        if dom is not None:
            assert dom.lower() != "not rated", \
                "Dominant rating class should exclude 'Not rated'"

    def test_weighted_value_excludes_not_rated(self, report_main):
        mukey = "49456"
        ikey = "ENG - Septic Tank Absorption Fields"
        interp = report_main["mapunits"][mukey]["interpretations"][ikey]

        components = report_main["mapunits"][mukey]["components"]
        sum_pct = 0
        sum_val = 0.0
        for ck, idata in interp["components"].items():
            rc = idata.get("rating_class")
            rv = idata.get("rating_value")
            if rc and rc.lower() != "not rated" and rv is not None and ck in components:
                pct = components[ck]["comppct_r"]
                if pct:
                    sum_pct += pct
                    sum_val += pct * rv

        if sum_pct > 0:
            expected = sum_val / sum_pct
            actual = interp["weighted_rating_value"]
            assert actual is not None
            assert abs(actual - expected) < 1e-4, \
                f"Weighted rating value: got {actual}, expected {expected}"


# ============================================================
# 9. Edge Cases
# ============================================================

class TestEdgeCases:
    """Test edge cases in the data."""

    def test_component_without_horizons(self, report_main):
        """Some components (e.g. Rock outcrop) may have no horizons."""
        mukey = "49456"
        found_empty = False
        for cokey, comp in report_main["mapunits"][mukey]["components"].items():
            if len(comp["horizons"]) == 0:
                found_empty = True
                assert comp["depth_weighted"]["awc"] is None
                assert comp["depth_weighted"]["ksat"] is None
                assert comp["depth_weighted"]["dbthirdbar"] is None
        if not found_empty:
            pytest.skip("No components without horizons found in test data")

    def test_restriction_depth_present(self, report_main):
        """Verify restriction_depth_cm field exists for all components."""
        mukey = "49456"
        for cokey, comp in report_main["mapunits"][mukey]["components"].items():
            assert "restriction_depth_cm" in comp
