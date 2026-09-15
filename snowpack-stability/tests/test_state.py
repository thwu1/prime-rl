
"""Tests for SNOWPACK profile stability analyzer.

Validates against reference output from the SNOWPACK model (MST96 Weissfluhjoch
winter 1995-96 simulation).
"""

import json
import subprocess
import sys
import math
import pytest

TOOL = "/app/snowpack_stability.py"
PRO = "/app/data/profile.pro"
SLOPE = "0.0"


def run_analyzer(timestamp, slope=SLOPE):
    """Run the stability analyzer and return parsed JSON."""
    result = subprocess.run(
        [sys.executable, TOOL, PRO, timestamp, "--slope-angle", slope],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Tool failed: {result.stderr}"
    data = json.loads(result.stdout)
    return data


def approx(a, b, rel=0.20, abs_tol=0.02):
    """Check that a ~ b within 20% relative or 0.02 absolute tolerance."""
    if b == 0:
        return abs(a) < abs_tol
    return abs(a - b) / max(abs(b), 1e-9) < rel or abs(a - b) < abs_tol


# ============================================================
# Test 1: Parsing - November 2, 1995 (6 elements, thin snowpack)
# ============================================================
class TestNov2Parsing:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analyzer("02.11.1995 00:00:00")

    def test_n_elements(self):
        assert self.data["n_elements"] == 6

    def test_snow_height(self):
        assert approx(self.data["snow_height_cm"], 5.10)

    def test_stability_class_undefined(self):
        """Snowpack too thin for stability assessment."""
        assert self.data["profile"]["stability_class"] == -1

    def test_all_sk38_max(self):
        """All Sk38 should be 6.0 (max) for very thin snowpack."""
        for layer in self.data["layers"]:
            assert layer["Sk38"] == 6.0

    def test_layer_count(self):
        assert len(self.data["layers"]) == 6

    def test_grain_types_all_pp(self):
        """All layers should be PP (110)."""
        for layer in self.data["layers"]:
            assert layer["grain_type"] == 110

    def test_ccl_all_max_thin_snow(self):
        """CCL should be 3.0 for all layers in a snowpack too thin for analysis."""
        for layer in self.data["layers"]:
            assert layer["critical_cut_length_m"] == 3.0


# ============================================================
# Test 2: Shear strength - PP grain type (Nov 2, all PP)
# ============================================================
class TestShearStrengthPP:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analyzer("02.11.1995 00:00:00")

    def test_pp_strength_layer0(self):
        """PP shear strength at density 88.1 should be ~0.20 kPa."""
        s = self.data["layers"][0]["shear_strength_kPa"]
        assert approx(s, 0.20, rel=0.15), f"PP strength {s} not ~ 0.20"

    def test_pp_strength_layer5(self):
        """PP shear strength at density 77.7 should be ~0.175 kPa."""
        s = self.data["layers"][5]["shear_strength_kPa"]
        assert approx(s, 0.175, rel=0.15), f"PP strength {s} not ~ 0.175"

    def test_strength_decreases_with_density(self):
        """Lower density -> lower shear strength for same grain type."""
        strengths = [l["shear_strength_kPa"] for l in self.data["layers"]]
        assert strengths[0] > strengths[-1]


# ============================================================
# Test 3: December 15, 1995 - Full stability (41 layers, class 3)
# ============================================================
class TestDec15Stability:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analyzer("15.12.1995 00:00:00")

    def test_n_elements(self):
        assert self.data["n_elements"] == 41

    def test_snow_height(self):
        assert approx(self.data["snow_height_cm"], 52.25)

    def test_stability_class_fair(self):
        """Reference stability class = 3 (fair)."""
        assert self.data["profile"]["stability_class"] == 3

    def test_mfcr_shear_strength(self):
        """MFcr layers (mk>=20, grain type 772) must have strength ~ 4.0 kPa."""
        for i in [4, 5, 6, 7, 9]:
            s = self.data["layers"][i]["shear_strength_kPa"]
            assert approx(s, 4.0, rel=0.05), \
                f"MFcr layer {i} strength {s} not ~ 4.0"

    def test_fc_shear_strength(self):
        """FC/FCxr layer (layer 0, rho=352.8): strength ~ 2.47 kPa."""
        s = self.data["layers"][0]["shear_strength_kPa"]
        assert approx(s, 2.47, rel=0.15), \
            f"FC layer strength {s} not ~ 2.47"

    def test_min_sk38_is_low(self):
        """Profile has unstable layers: min Sk38 should be < 0.5."""
        min_sk = self.data["profile"]["min_Sk38"]
        assert min_sk < 0.5, f"min_Sk38 {min_sk} should be < 0.5"

    def test_min_ssi_reasonable(self):
        """Minimum SSI should be between 1.0 and 3.5."""
        min_ssi = self.data["profile"]["min_SSI"]
        assert 0.5 < min_ssi < 4.0, \
            f"min_SSI {min_ssi} not in expected range"

    def test_sk38_above_penetration(self):
        """Layers above penetration depth should have Sk38 = 6.0."""
        pk = self.data["penetration_depth_m"]
        for layer in self.data["layers"]:
            depth = (self.data["snow_height_cm"] - layer["height_cm"]) / 100.0
            if depth < pk - 0.01:
                assert layer["Sk38"] == 6.0, \
                    f"Layer at h={layer['height_cm']} above Pk should have Sk38=6.0"

    def test_penetration_depth_reasonable(self):
        """Pk should be between 0.05 and 0.5 m for this profile."""
        pk = self.data["penetration_depth_m"]
        assert 0.05 < pk < 0.5, f"Pk={pk} not in expected range"

    def test_ccl_top_undefined(self):
        """Top element CCL should be 3.0 (undefined)."""
        assert self.data["layers"][-1]["critical_cut_length_m"] == 3.0

    def test_ccl_range(self):
        """CCL minimum should be between 0.03 and 0.2 for this profile."""
        ccl_vals = [l["critical_cut_length_m"] for l in self.data["layers"]]
        ccl_min = min(ccl_vals)
        assert 0.03 < ccl_min < 0.2, f"CCL min {ccl_min} not in expected range"

    def test_ccl_active_layers(self):
        """Multiple layers should have CCL < 1.0 (not at max)."""
        ccl_active = [l for l in self.data["layers"]
                      if l["critical_cut_length_m"] < 1.0]
        assert len(ccl_active) >= 10, \
            f"Only {len(ccl_active)} layers with CCL<1.0, expected >=10"


# ============================================================
# Test 4: February 15, 1996 - Deep snowpack, poor stability
# ============================================================
class TestFeb15Stability:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_analyzer("15.02.1996 00:00:00")

    def test_n_elements(self):
        assert self.data["n_elements"] == 81

    def test_snow_height(self):
        assert approx(self.data["snow_height_cm"], 108.05)

    def test_stability_class_poor(self):
        """Reference stability class = 1 (poor)."""
        assert self.data["profile"]["stability_class"] == 1

    def test_min_sk38_very_low(self):
        """Feb 15 has very low Sk38 (near clamped minimum)."""
        min_sk = self.data["profile"]["min_Sk38"]
        assert min_sk < 0.15, f"min_Sk38 {min_sk} should be < 0.15"

    def test_min_ssi_low(self):
        """SSI should be low for poor stability."""
        min_ssi = self.data["profile"]["min_SSI"]
        assert min_ssi < 2.0, f"min_SSI {min_ssi} should be < 2.0"

    def test_mfcr_detected(self):
        """MFcr layers must have strength ~ 4.0."""
        for i in [4, 5, 6, 7, 9]:
            s = self.data["layers"][i]["shear_strength_kPa"]
            assert approx(s, 4.0, rel=0.05), \
                f"Feb15 MFcr layer {i} strength {s} not ~ 4.0"

    def test_weak_layers_in_upper_pack(self):
        """Weak layers (low Sk38) should be in upper portion of snowpack."""
        weak_layers = [l for l in self.data["layers"] if l["Sk38"] < 1.0]
        assert len(weak_layers) > 3, \
            "Should have multiple weak layers"
        for wl in weak_layers:
            assert wl["height_cm"] > 40.0, \
                f"Weak layer at h={wl['height_cm']} unexpectedly low"

    def test_deep_layers_are_stable_sn38(self):
        """Deep layers in Feb15 should have moderate-to-high Sn38."""
        for layer in self.data["layers"][:25]:
            if layer["height_cm"] > 20:
                assert layer["Sn38"] > 1.0, \
                    f"Deep layer at h={layer['height_cm']} has low Sn38={layer['Sn38']}"

    def test_penetration_depth_for_deep_pack(self):
        """Pk for 108cm snowpack with mixed densities should be 0.1-0.6 m."""
        pk = self.data["penetration_depth_m"]
        assert 0.1 < pk < 0.6, f"Pk={pk} not in expected range"

    def test_ccl_more_active_than_dec(self):
        """Deep snowpack should have more layers with short CCL."""
        ccl_active = [l for l in self.data["layers"]
                      if l["critical_cut_length_m"] < 0.5]
        assert len(ccl_active) >= 20, \
            f"Only {len(ccl_active)} layers with CCL<0.5, expected >=20 for deep pack"

    def test_ccl_min_low(self):
        """CCL minimum should be below 0.1 for the deep unstable profile."""
        ccl_vals = [l["critical_cut_length_m"] for l in self.data["layers"]]
        assert min(ccl_vals) < 0.1, \
            f"CCL min {min(ccl_vals)} should be < 0.1"


# ============================================================
# Test 5: Cross-timestep consistency and edge cases
# ============================================================
class TestConsistency:
    def test_json_schema(self):
        """Output must contain all required fields including CCL."""
        data = run_analyzer("15.12.1995 00:00:00")
        assert "timestamp" in data
        assert "n_elements" in data
        assert "snow_height_cm" in data
        assert "penetration_depth_m" in data
        assert "profile" in data
        p = data["profile"]
        for key in ["stability_class", "min_Sk38", "min_Sk38_height_cm",
                     "min_Sn38", "min_Sn38_height_cm",
                     "min_SSI", "min_SSI_height_cm"]:
            assert key in p, f"Missing profile key: {key}"
        assert "layers" in data
        assert len(data["layers"]) > 0
        layer = data["layers"][0]
        for key in ["height_cm", "density_kg_m3", "grain_type",
                     "shear_strength_kPa", "Sk38", "Sn38", "SSI",
                     "critical_cut_length_m"]:
            assert key in layer, f"Missing layer key: {key}"

    def test_stability_clamping(self):
        """All stability indices must be in [0.05, 6.0]."""
        for ts in ["02.11.1995 00:00:00", "15.12.1995 00:00:00",
                    "15.02.1996 00:00:00"]:
            data = run_analyzer(ts)
            for layer in data["layers"]:
                for idx in ["Sk38", "Sn38", "SSI"]:
                    v = layer[idx]
                    assert 0.05 <= v <= 6.0, \
                        f"ts={ts} h={layer['height_cm']} {idx}={v} out of [0.05,6.0]"

    def test_ccl_clamping(self):
        """All CCL values must be in [0, 3.0]."""
        for ts in ["02.11.1995 00:00:00", "15.12.1995 00:00:00",
                    "15.02.1996 00:00:00"]:
            data = run_analyzer(ts)
            for layer in data["layers"]:
                ccl = layer["critical_cut_length_m"]
                assert 0 <= ccl <= 3.0, \
                    f"ts={ts} h={layer['height_cm']} CCL={ccl} out of [0,3.0]"

    def test_deeper_snowpack_more_unstable(self):
        """Feb15 (108cm, class 1) should be less stable than Dec15 (52cm, class 3)."""
        dec = run_analyzer("15.12.1995 00:00:00")
        feb = run_analyzer("15.02.1996 00:00:00")
        assert feb["profile"]["stability_class"] <= dec["profile"]["stability_class"]
        assert feb["profile"]["min_Sk38"] <= dec["profile"]["min_Sk38"]

    def test_ssi_geq_sk38(self):
        """SSI >= Sk38 for all layers (SSI = Sk38 + offset from lemons)."""
        data = run_analyzer("15.12.1995 00:00:00")
        for layer in data["layers"]:
            assert layer["SSI"] >= layer["Sk38"] - 0.01, \
                f"SSI ({layer['SSI']}) < Sk38 ({layer['Sk38']}) at h={layer['height_cm']}"

    def test_grain_type_dependent_strength(self):
        """Different grain types at similar densities should give different strengths."""
        data = run_analyzer("15.12.1995 00:00:00")
        s_fcxr = data["layers"][8]["shear_strength_kPa"]
        s_mfcr = data["layers"][4]["shear_strength_kPa"]
        assert abs(s_mfcr - 4.0) < 0.2
        assert s_fcxr < 3.0
        assert s_mfcr > s_fcxr


# ============================================================
# Test 6: Slope angle sensitivity
# ============================================================
class TestSlopeAngle:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data_0 = run_analyzer("15.12.1995 00:00:00", slope="0.0")
        self.data_38 = run_analyzer("15.12.1995 00:00:00", slope="38.0")

    def test_same_n_elements(self):
        """Number of elements should not change with slope angle."""
        assert self.data_0["n_elements"] == self.data_38["n_elements"]

    def test_same_snow_height(self):
        """Snow height should not change with slope angle."""
        assert self.data_0["snow_height_cm"] == self.data_38["snow_height_cm"]

    def test_steeper_slope_lower_sn38(self):
        """At steeper slope, natural stability (Sn38) should decrease."""
        sn_0 = self.data_0["profile"]["min_Sn38"]
        sn_38 = self.data_38["profile"]["min_Sn38"]
        assert sn_38 < sn_0, \
            f"Sn38 at 38 deg ({sn_38}) should be < Sn38 at 0 deg ({sn_0})"

    def test_steeper_slope_lower_sk38(self):
        """At steeper slope, skier stability (Sk38) should decrease or be equal."""
        sk_0 = self.data_0["profile"]["min_Sk38"]
        sk_38 = self.data_38["profile"]["min_Sk38"]
        assert sk_38 <= sk_0 + 0.01, \
            f"Sk38 at 38 deg ({sk_38}) should be <= Sk38 at 0 deg ({sk_0})"

    def test_steeper_slope_shorter_ccl(self):
        """At steeper slope, minimum CCL should be shorter (easier to fracture)."""
        ccl_0 = min(l["critical_cut_length_m"] for l in self.data_0["layers"])
        ccl_38 = min(l["critical_cut_length_m"] for l in self.data_38["layers"])
        assert ccl_38 < ccl_0 + 0.01, \
            f"Min CCL at 38 deg ({ccl_38}) should be < CCL at 0 deg ({ccl_0})"

    def test_slope_changes_stability_magnitudes(self):
        """Sn38 should change substantially between 0 and 38 deg."""
        sn_0 = self.data_0["profile"]["min_Sn38"]
        sn_38 = self.data_38["profile"]["min_Sn38"]
        # Expect at least 20% change in Sn38
        assert abs(sn_0 - sn_38) / max(sn_0, 0.01) > 0.2, \
            f"Sn38 change too small: {sn_0} -> {sn_38}"

    def test_shear_strengths_unchanged_by_slope(self):
        """Shear strength is a layer property and should not change with slope for non-FC types."""
        # Check PP layers near the top
        for i in range(36, 41):
            s0 = self.data_0["layers"][i]["shear_strength_kPa"]
            s38 = self.data_38["layers"][i]["shear_strength_kPa"]
            gt = self.data_0["layers"][i]["grain_type"]
            f1 = gt // 100
            if f1 in (1, 2, 3, 7):  # PP, DF, RG, MF - no sig_n in strength
                assert abs(s0 - s38) < 0.01, \
                    f"Layer {i} (type {gt}): strength changed with slope: {s0} vs {s38}"


# ============================================================
# Test 7: Critical Cut Length detailed validation
# ============================================================
class TestCCLComputation:
    def test_dec15_ccl_varies_with_depth(self):
        """CCL should vary across layers - not all the same value."""
        data = run_analyzer("15.12.1995 00:00:00")
        ccl_vals = [l["critical_cut_length_m"] for l in data["layers"]]
        unique_ccl = set(round(c, 2) for c in ccl_vals)
        assert len(unique_ccl) >= 5, \
            f"Only {len(unique_ccl)} unique CCL values, expected variety"

    def test_feb15_ccl_shorter_with_deeper_slab(self):
        """For Feb15, CCL for middle layers should be shorter than for top layers."""
        data = run_analyzer("15.02.1996 00:00:00")
        # Top layers (indices 70+) are near surface -> thin slab -> large CCL or 3.0
        top_ccls = [data["layers"][i]["critical_cut_length_m"]
                    for i in range(70, 80)]
        # Middle layers (indices 40-60) have thicker slab
        mid_ccls = [data["layers"][i]["critical_cut_length_m"]
                    for i in range(40, 60)]
        avg_top = sum(top_ccls) / len(top_ccls)
        avg_mid = sum(mid_ccls) / len(mid_ccls)
        assert avg_mid < avg_top, \
            f"Mid-pack CCL avg ({avg_mid:.3f}) should be < top CCL avg ({avg_top:.3f})"

    def test_ccl_depends_on_young_modulus(self):
        """CCL computation requires correct Young's modulus from slab density.
        Dec15 low-density slab layers should have smaller E -> different CCL
        compared to high-density slab layers."""
        data = run_analyzer("15.12.1995 00:00:00")
        # Check that CCL varies with slab properties - layers at different depths
        ccl_10 = data["layers"][10]["critical_cut_length_m"]
        ccl_25 = data["layers"][25]["critical_cut_length_m"]
        # These should be different due to different slab densities/thicknesses
        assert abs(ccl_10 - ccl_25) > 0.05, \
            f"CCL at layer 10 ({ccl_10:.3f}) and 25 ({ccl_25:.3f}) too similar"

    def test_ccl_bottom_layers_defined(self):
        """Bottom layer should have CCL = 3.0 (not included in CCL computation)."""
        data = run_analyzer("15.12.1995 00:00:00")
        assert data["layers"][0]["critical_cut_length_m"] == 3.0, \
            "Bottom layer CCL should be 3.0"

    def test_feb15_many_short_ccl(self):
        """Feb15 deep pack: majority of middle layers should have CCL < 1.0."""
        data = run_analyzer("15.02.1996 00:00:00")
        n = data["n_elements"]
        middle_layers = data["layers"][10:n-10]
        short_ccl = [l for l in middle_layers
                     if l["critical_cut_length_m"] < 1.0]
        assert len(short_ccl) > len(middle_layers) * 0.7, \
            f"Only {len(short_ccl)}/{len(middle_layers)} middle layers have CCL<1.0"
