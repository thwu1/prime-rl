"""
Verification tests for the obstetric biometry and surveillance pipeline.

Tests validate /app/results.json against correct implementations of the
published Hadlock regression equations, Doppler index definitions, Arduini
& Rizzo UA PI reference ranges, and Moore & Cayle AFI normative data.

"""

import json
import math
import os
import pytest


# ============================================================
# Reference implementations (correct formulas)
# ============================================================

def hadlock_mean_efw(wga):
    return math.exp(0.578 + 0.332 * wga - 0.00354 * wga ** 2)


def correct_efw_hadlock_ac(ac):
    ln_efw = 2.695 + 0.253 * ac - 0.00275 * ac ** 2
    return math.exp(ln_efw)


def correct_efw_hadlock1(ac, fl):
    return 10 ** (1.304 + 0.05281 * ac + 0.1938 * fl - 0.004 * ac * fl)


def correct_efw_hadlock3(ac, hc, fl):
    return 10 ** (1.326 - 0.00326 * ac * fl + 0.0107 * hc
                  + 0.0438 * ac + 0.158 * fl)


def correct_efw_hadlock4(ac, hc, bpd, fl):
    return 10 ** (1.3596 + 0.0064 * hc + 0.0424 * ac + 0.174 * fl
                  + 0.00061 * bpd * ac - 0.00386 * ac * fl)


def correct_ga_from_crl(crl_mm):
    crl_cm = crl_mm / 10.0
    return math.exp(1.684969 + 0.315646 * crl_cm
                    - 0.049306 * crl_cm ** 2
                    + 0.004057 * crl_cm ** 3
                    - 0.000120456 * crl_cm ** 4)


def correct_ga_from_bpd(bpd_cm):
    return 9.54 + 1.482 * bpd_cm + 0.1676 * bpd_cm ** 2


def correct_ga_from_hc(hc_cm):
    return 8.96 + 0.540 * hc_cm + 0.0003 * hc_cm ** 3


def correct_ga_from_fl(fl_cm):
    return 10.35 + 2.460 * fl_cm + 0.170 * fl_cm ** 2


def correct_ga_from_ac(ac_cm):
    return 8.14 + 0.753 * ac_cm + 0.0036 * ac_cm ** 2


def correct_percentile(efw, wga):
    mu = math.log(hadlock_mean_efw(wga))
    z = (math.log(efw) - mu) / 0.12
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))) * 100.0


def correct_ri(psv, edv):
    return (psv - edv) / psv


def correct_pi(psv, edv, mean_v):
    return (psv - edv) / mean_v


def correct_cpr(mca_pi, ua_pi):
    return mca_pi / ua_pi


# Arduini & Rizzo (1990) UA PI reference
def correct_arduini_mean(ga_weeks):
    return 1.5400 - 0.01500 * ga_weeks - 0.000100 * ga_weeks ** 2


def correct_arduini_sd(ga_weeks):
    return 0.2600 - 0.00300 * ga_weeks


def correct_ua_pi_zscore(observed_pi, ga_weeks):
    if ga_weeks < 20 or ga_weeks > 42:
        return None
    ref_mean = correct_arduini_mean(ga_weeks)
    ref_sd = correct_arduini_sd(ga_weeks)
    if ref_sd <= 0:
        return None
    return (observed_pi - ref_mean) / ref_sd


# AFI reference data (Moore & Cayle 1990)
AFI_REF_P5 = {
    16: 79, 17: 83, 18: 87, 19: 90, 20: 93, 21: 95, 22: 97, 23: 98,
    24: 98, 25: 97, 26: 97, 27: 95, 28: 94, 29: 92, 30: 90, 31: 88,
    32: 86, 33: 83, 34: 81, 35: 79, 36: 77, 37: 75, 38: 73, 39: 72,
    40: 71, 41: 70, 42: 69
}
AFI_REF_P95 = {
    16: 185, 17: 194, 18: 202, 19: 207, 20: 212, 21: 214, 22: 216,
    23: 218, 24: 219, 25: 221, 26: 223, 27: 226, 28: 228, 29: 231,
    30: 234, 31: 238, 32: 242, 33: 245, 34: 248, 35: 249, 36: 249,
    37: 244, 38: 239, 39: 226, 40: 214, 41: 194, 42: 175
}

Z_CRIT_95 = 1.6448536269514729  # qnorm(0.95)


def correct_afi_percentile(afi_mm, ga_weeks):
    if ga_weeks < 16 or ga_weeks > 42:
        return None
    ga_lo = int(math.floor(ga_weeks))
    ga_hi = int(math.ceil(ga_weeks))
    if ga_lo == ga_hi:
        p5 = float(AFI_REF_P5[ga_lo])
        p95 = float(AFI_REF_P95[ga_lo])
    else:
        frac = ga_weeks - ga_lo
        p5 = AFI_REF_P5[ga_lo] + frac * (AFI_REF_P5[ga_hi] - AFI_REF_P5[ga_lo])
        p95 = AFI_REF_P95[ga_lo] + frac * (AFI_REF_P95[ga_hi] - AFI_REF_P95[ga_lo])
    mu = (math.log(p5) + math.log(p95)) / 2
    sigma = (math.log(p95) - math.log(p5)) / (2 * Z_CRIT_95)
    z = (math.log(afi_mm) - mu) / sigma
    return 0.5 * (1 + math.erf(z / math.sqrt(2))) * 100


# ============================================================
# Fixture: load pipeline results
# ============================================================

@pytest.fixture(scope="module")
def pipeline_results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        "Pipeline did not produce /app/results.json. "
        "Ensure Rscript /app/run_pipeline.R completes successfully."
    )
    with open(results_path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON in results.json: {e}")


def get_patient(results, pid):
    for p in results["patients"]:
        if p["id"] == pid:
            return p
    pytest.fail(f"Patient {pid} not found in results")


# ============================================================
# Test: pipeline structure
# ============================================================

def test_pipeline_produces_all_patients(pipeline_results):
    assert "patients" in pipeline_results
    assert len(pipeline_results["patients"]) == 10


# ============================================================
# Tests: CRL gestational age dating (catches unit bug)
# ============================================================

def test_crl_dating_p001_plausible(pipeline_results):
    p = get_patient(pipeline_results, "P001")
    assert p["composite_ga_weeks"] is not None, (
        "P001 composite GA is null — check CRL unit conversion and NA handling")
    expected = correct_ga_from_crl(57.0)
    assert abs(p["composite_ga_weeks"] - expected) < 0.5, (
        f"P001 composite GA {p['composite_ga_weeks']} deviates from "
        f"expected {expected:.2f}")


def test_crl_dating_p001_in_first_trimester(pipeline_results):
    p = get_patient(pipeline_results, "P001")
    assert p["composite_ga_weeks"] is not None
    assert 10.0 < p["composite_ga_weeks"] < 14.0


# ============================================================
# Tests: EFW formulas (catches log-base and coefficient bugs)
# ============================================================

def test_hadlock_ac_efw_uses_exp(pipeline_results):
    p = get_patient(pipeline_results, "P002")
    assert "hadlock_ac" in p.get("efw", {}), "P002 should have hadlock_ac EFW"
    correct = correct_efw_hadlock_ac(15.2)
    actual = p["efw"]["hadlock_ac"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02, (
        f"AC-only EFW {actual:.1f} vs expected {correct:.1f} "
        f"(rel err {rel_err:.3f}) — check log base")


def test_hadlock3_efw_p003_coefficients(pipeline_results):
    p = get_patient(pipeline_results, "P003")
    correct = correct_efw_hadlock3(24.0, 26.5, 5.4)
    actual = p["efw"]["hadlock3"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02, (
        f"Hadlock-3 EFW {actual:.1f} vs expected {correct:.1f} "
        f"(rel err {rel_err:.3f}) — check HC/AC coefficients")


def test_hadlock3_efw_p006_no_bpd(pipeline_results):
    p = get_patient(pipeline_results, "P006")
    assert "hadlock3" in p.get("efw", {}), "P006 should have hadlock3 EFW"
    correct = correct_efw_hadlock3(19.8, 21.5, 4.3)
    actual = p["efw"]["hadlock3"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02


def test_hadlock4_efw_p002(pipeline_results):
    p = get_patient(pipeline_results, "P002")
    correct = correct_efw_hadlock4(15.2, 17.5, 4.7, 3.3)
    actual = p["efw"]["hadlock4"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02


def test_hadlock4_efw_p007(pipeline_results):
    p = get_patient(pipeline_results, "P007")
    correct = correct_efw_hadlock4(38.0, 35.0, 9.5, 8.0)
    actual = p["efw"]["hadlock4"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02


def test_hadlock1_efw_p005(pipeline_results):
    p = get_patient(pipeline_results, "P005")
    correct = correct_efw_hadlock1(32.5, 7.0)
    actual = p["efw"]["hadlock1"]
    rel_err = abs(actual - correct) / correct
    assert rel_err < 0.02


# ============================================================
# Tests: growth percentiles and classification (catches SD bug)
# ============================================================

def test_percentiles_in_valid_range(pipeline_results):
    for p in pipeline_results["patients"]:
        pct = p.get("growth_percentile")
        if pct is not None:
            assert 0 < pct < 100, (
                f"Patient {p['id']} has unreasonable percentile {pct}")


def test_classification_p002_aga(pipeline_results):
    p = get_patient(pipeline_results, "P002")
    assert p["classification"] == "AGA"


def test_classification_p004_sga(pipeline_results):
    p = get_patient(pipeline_results, "P004")
    assert p["classification"] == "SGA"


def test_classification_p005_aga(pipeline_results):
    p = get_patient(pipeline_results, "P005")
    assert p["classification"] == "AGA"


def test_classification_p007_lga(pipeline_results):
    p = get_patient(pipeline_results, "P007")
    assert p["classification"] == "LGA"


def test_classification_p008_sga(pipeline_results):
    p = get_patient(pipeline_results, "P008")
    assert p["classification"] == "SGA"


def test_classification_p009_sga(pipeline_results):
    p = get_patient(pipeline_results, "P009")
    assert p["classification"] == "SGA"


def test_percentile_p004_value(pipeline_results):
    p = get_patient(pipeline_results, "P004")
    efw = correct_efw_hadlock4(24.0, 27.2, 7.3, 5.6)
    expected_pct = correct_percentile(efw, 30)
    assert abs(p["growth_percentile"] - expected_pct) < 2.0


# ============================================================
# Tests: composite GA with missing parameters (catches na.rm bug)
# ============================================================

def test_composite_ga_p001_not_null(pipeline_results):
    p = get_patient(pipeline_results, "P001")
    assert p["composite_ga_weeks"] is not None, (
        "P001 composite GA is null — check NA handling in mean()")


def test_composite_ga_p006_not_null(pipeline_results):
    p = get_patient(pipeline_results, "P006")
    assert p["composite_ga_weeks"] is not None, (
        "P006 composite GA is null — check NA handling in mean()")


def test_composite_ga_p006_in_range(pipeline_results):
    p = get_patient(pipeline_results, "P006")
    assert p["composite_ga_weeks"] is not None
    expected = (correct_ga_from_hc(21.5) + correct_ga_from_fl(4.3)
                + correct_ga_from_ac(19.8)) / 3.0
    assert abs(p["composite_ga_weeks"] - expected) < 0.5


def test_composite_ga_p002_value(pipeline_results):
    p = get_patient(pipeline_results, "P002")
    assert p["composite_ga_weeks"] is not None
    expected = (correct_ga_from_bpd(4.7) + correct_ga_from_hc(17.5)
                + correct_ga_from_fl(3.3) + correct_ga_from_ac(15.2)) / 4.0
    assert abs(p["composite_ga_weeks"] - expected) < 0.5


# ============================================================
# Tests: chart audit (catches chart data bug AND interacting SD bug)
# ============================================================

def test_chart_audit_clean(pipeline_results):
    audit = pipeline_results.get("chart_audit", {})
    assert audit.get("total_errors") == 0, (
        f"Chart audit found {audit.get('total_errors')} error(s)")


# ============================================================
# Tests: P001 has no EFW (only CRL available)
# ============================================================

def test_p001_no_classification(pipeline_results):
    p = get_patient(pipeline_results, "P001")
    assert p["classification"] is None
    assert p["growth_percentile"] is None


# ============================================================
# Tests: Doppler indices (catches RI sign, CPR inversion, AEDF bugs)
# ============================================================

def test_ua_ri_p002_below_one(pipeline_results):
    """RI for normal forward flow must be < 1.0 (catches sign bug)."""
    p = get_patient(pipeline_results, "P002")
    assert p["doppler"] is not None, "P002 should have Doppler data"
    expected_ri = correct_ri(45.2, 11.3)
    assert p["doppler"]["ua_ri"] < 1.0, (
        f"UA RI {p['doppler']['ua_ri']} >= 1.0 — check RI formula sign")
    assert abs(p["doppler"]["ua_ri"] - round(expected_ri, 3)) < 0.01


def test_ua_ri_p003(pipeline_results):
    p = get_patient(pipeline_results, "P003")
    assert p["doppler"] is not None
    expected_ri = correct_ri(42.1, 14.0)
    assert abs(p["doppler"]["ua_ri"] - round(expected_ri, 3)) < 0.01


def test_ua_pi_p002(pipeline_results):
    p = get_patient(pipeline_results, "P002")
    expected_pi = correct_pi(45.2, 11.3, 22.1)
    assert abs(p["doppler"]["ua_pi"] - round(expected_pi, 3)) < 0.01


def test_cpr_p002_above_one(pipeline_results):
    """CPR for normal flow should be > 1.0 (catches inversion bug)."""
    p = get_patient(pipeline_results, "P002")
    assert p["doppler"]["cpr"] is not None
    ua_pi = round(correct_pi(45.2, 11.3, 22.1), 3)
    mca_pi = round(correct_pi(55.0, 12.0, 22.0), 3)
    expected_cpr = mca_pi / ua_pi
    assert p["doppler"]["cpr"] > 1.0, (
        f"CPR {p['doppler']['cpr']} <= 1.0 — check CPR formula direction")
    assert abs(p["doppler"]["cpr"] - round(expected_cpr, 3)) < 0.01


def test_cpr_p004_abnormal(pipeline_results):
    """P004 should have CPR < 1.0 (brain sparing)."""
    p = get_patient(pipeline_results, "P004")
    assert p["doppler"] is not None
    assert p["doppler"]["cpr"] < 1.0, (
        f"P004 CPR {p['doppler']['cpr']} >= 1.0 — expected brain sparing")


def test_cpr_p005_normal(pipeline_results):
    p = get_patient(pipeline_results, "P005")
    assert p["doppler"]["cpr"] > 1.0


def test_doppler_null_p001(pipeline_results):
    """P001 has no Doppler data — doppler must be null."""
    p = get_patient(pipeline_results, "P001")
    assert p["doppler"] is None


def test_doppler_null_p010(pipeline_results):
    """P010 has no Doppler data — doppler must be null."""
    p = get_patient(pipeline_results, "P010")
    assert p["doppler"] is None


def test_doppler_cpr_null_p006(pipeline_results):
    """P006 has UA Doppler but no MCA — CPR must be null."""
    p = get_patient(pipeline_results, "P006")
    assert p["doppler"] is not None, "P006 should have partial Doppler data"
    assert p["doppler"]["cpr"] is None, (
        "P006 has no MCA data — CPR must be null")
    assert p["doppler"]["ua_pi"] is not None


# ============================================================
# Tests: AEDF handling (P008)
# ============================================================

def test_aedf_p008_has_doppler(pipeline_results):
    """AEDF patient must still have Doppler output (not silently dropped)."""
    p = get_patient(pipeline_results, "P008")
    assert p["doppler"] is not None, (
        "P008 (AEDF) Doppler is null — EDV=0 should not drop all data")


def test_aedf_p008_flags(pipeline_results):
    p = get_patient(pipeline_results, "P008")
    assert p["doppler"]["aedf"] is True
    assert p["doppler"]["redf"] is False


def test_aedf_p008_sd_null(pipeline_results):
    """S/D ratio must be null for AEDF (infinite, not representable)."""
    p = get_patient(pipeline_results, "P008")
    assert p["doppler"]["ua_sd"] is None


def test_aedf_p008_ri_one(pipeline_results):
    """RI must equal 1.0 for AEDF (EDV=0 means (S-0)/S = 1)."""
    p = get_patient(pipeline_results, "P008")
    assert abs(p["doppler"]["ua_ri"] - 1.0) < 0.001


def test_aedf_p008_pi_computable(pipeline_results):
    """PI remains computable for AEDF: (S-0)/Mean = S/Mean."""
    p = get_patient(pipeline_results, "P008")
    expected_pi = 55.8 / 16.2
    assert abs(p["doppler"]["ua_pi"] - round(expected_pi, 3)) < 0.01


def test_aedf_p008_cpr(pipeline_results):
    """CPR should still be computed for AEDF patient with MCA data."""
    p = get_patient(pipeline_results, "P008")
    assert p["doppler"]["cpr"] is not None
    assert p["doppler"]["cpr"] < 1.0


# ============================================================
# Tests: REDF handling (P009)
# ============================================================

def test_redf_p009_has_doppler(pipeline_results):
    """REDF patient must still have Doppler output."""
    p = get_patient(pipeline_results, "P009")
    assert p["doppler"] is not None, (
        "P009 (REDF) Doppler is null — negative EDV should not drop all data")


def test_redf_p009_flags(pipeline_results):
    p = get_patient(pipeline_results, "P009")
    assert p["doppler"]["redf"] is True
    assert p["doppler"]["aedf"] is False


def test_redf_p009_sd_null(pipeline_results):
    p = get_patient(pipeline_results, "P009")
    assert p["doppler"]["ua_sd"] is None


def test_redf_p009_ri_above_one(pipeline_results):
    """RI > 1.0 for REDF (reversed flow makes (S-D)/S > 1)."""
    p = get_patient(pipeline_results, "P009")
    expected_ri = correct_ri(48.3, -3.5)
    assert p["doppler"]["ua_ri"] > 1.0
    assert abs(p["doppler"]["ua_ri"] - round(expected_ri, 3)) < 0.01


def test_redf_p009_pi(pipeline_results):
    p = get_patient(pipeline_results, "P009")
    expected_pi = correct_pi(48.3, -3.5, 18.5)
    assert abs(p["doppler"]["ua_pi"] - round(expected_pi, 3)) < 0.01


# ============================================================
# Tests: UA PI z-score (catches polynomial coefficient sign bug)
# ============================================================

def test_ua_pi_zscore_p002_value(pipeline_results):
    """P002 at GA=20 with elevated UA PI should have positive z-score."""
    p = get_patient(pipeline_results, "P002")
    assert p["doppler"] is not None
    assert p["doppler"]["ua_pi_zscore"] is not None, (
        "P002 ua_pi_zscore is null — implement compute_ua_pi_zscore")
    observed_pi = round(correct_pi(45.2, 11.3, 22.1), 3)
    expected_z = correct_ua_pi_zscore(observed_pi, 20)
    assert abs(p["doppler"]["ua_pi_zscore"] - expected_z) < 0.15, (
        f"P002 z-score {p['doppler']['ua_pi_zscore']} vs expected "
        f"{expected_z:.2f} — check reference polynomial coefficients")


def test_ua_pi_zscore_p005_positive(pipeline_results):
    """P005 at GA=36 with slightly elevated PI should have positive z-score.
    The buggy polynomial (wrong quadratic sign) would produce a negative z."""
    p = get_patient(pipeline_results, "P005")
    assert p["doppler"] is not None
    assert p["doppler"]["ua_pi_zscore"] is not None
    observed_pi = round(correct_pi(38.5, 16.7, 22.4), 3)
    expected_z = correct_ua_pi_zscore(observed_pi, 36)
    assert p["doppler"]["ua_pi_zscore"] > 0, (
        f"P005 z-score {p['doppler']['ua_pi_zscore']} <= 0 — "
        f"check sign of quadratic coefficient in reference polynomial")
    assert abs(p["doppler"]["ua_pi_zscore"] - expected_z) < 0.15


def test_ua_pi_zscore_p007_value(pipeline_results):
    """P007 at GA=40 should have positive z-score."""
    p = get_patient(pipeline_results, "P007")
    assert p["doppler"] is not None
    assert p["doppler"]["ua_pi_zscore"] is not None
    observed_pi = round(correct_pi(35.2, 16.8, 21.5), 3)
    expected_z = correct_ua_pi_zscore(observed_pi, 40)
    assert abs(p["doppler"]["ua_pi_zscore"] - expected_z) < 0.15


def test_ua_pi_zscore_p004_high(pipeline_results):
    """P004 has elevated UA PI — z-score should be high (> 3)."""
    p = get_patient(pipeline_results, "P004")
    assert p["doppler"]["ua_pi_zscore"] is not None
    assert p["doppler"]["ua_pi_zscore"] > 3.0, (
        f"P004 z-score {p['doppler']['ua_pi_zscore']} too low — "
        f"expected significantly elevated for abnormal Doppler")


def test_ua_pi_zscore_null_p001(pipeline_results):
    """P001 has no Doppler — ua_pi_zscore not applicable."""
    p = get_patient(pipeline_results, "P001")
    assert p["doppler"] is None


def test_ua_pi_zscore_null_p010(pipeline_results):
    """P010 has no Doppler — ua_pi_zscore not applicable."""
    p = get_patient(pipeline_results, "P010")
    assert p["doppler"] is None


def test_ua_pi_zscore_p008_aedf_computable(pipeline_results):
    """Z-score should still be computable for AEDF patient."""
    p = get_patient(pipeline_results, "P008")
    assert p["doppler"] is not None
    assert p["doppler"]["ua_pi_zscore"] is not None, (
        "AEDF patient should have computable UA PI z-score")
    assert p["doppler"]["ua_pi_zscore"] > 5.0, (
        "AEDF z-score should be very high")


def test_ua_pi_zscore_p006_value(pipeline_results):
    """P006 at GA=24 should have a plausible z-score."""
    p = get_patient(pipeline_results, "P006")
    assert p["doppler"] is not None
    assert p["doppler"]["ua_pi_zscore"] is not None
    observed_pi = round(correct_pi(40.2, 13.4, 21.3), 3)
    expected_z = correct_ua_pi_zscore(observed_pi, 24)
    assert abs(p["doppler"]["ua_pi_zscore"] - expected_z) < 0.15


# ============================================================
# Tests: AFI percentile and classification (catches stub impl)
# ============================================================

def test_afi_null_p001(pipeline_results):
    """P001 has no AFI data — afi must be null."""
    p = get_patient(pipeline_results, "P001")
    assert p["afi"] is None


def test_afi_null_p006(pipeline_results):
    """P006 has no AFI data — afi must be null."""
    p = get_patient(pipeline_results, "P006")
    assert p["afi"] is None


def test_afi_p002_normal(pipeline_results):
    """P002 AFI=145 at GA=20 should be normal."""
    p = get_patient(pipeline_results, "P002")
    assert p["afi"] is not None
    assert p["afi"]["value_mm"] == 145
    assert p["afi"]["classification"] == "normal"
    expected_pct = correct_afi_percentile(145, 20)
    assert p["afi"]["percentile"] is not None
    assert abs(p["afi"]["percentile"] - expected_pct) < 2.0


def test_afi_p004_oligohydramnios(pipeline_results):
    """P004 AFI=82 at GA=30 should be oligohydramnios (below 5th pct)."""
    p = get_patient(pipeline_results, "P004")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "oligohydramnios"
    assert p["afi"]["percentile"] < 5.0


def test_afi_p005_normal(pipeline_results):
    """P005 AFI=135 at GA=36 should be normal."""
    p = get_patient(pipeline_results, "P005")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "normal"


def test_afi_p007_normal(pipeline_results):
    """P007 AFI=112 at GA=40 should be normal."""
    p = get_patient(pipeline_results, "P007")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "normal"


def test_afi_p008_oligohydramnios(pipeline_results):
    """P008 AFI=84 at GA=32 should be oligohydramnios."""
    p = get_patient(pipeline_results, "P008")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "oligohydramnios"
    assert p["afi"]["percentile"] < 5.0


def test_afi_p009_polyhydramnios(pipeline_results):
    """P009 AFI=255 at GA=34 should be polyhydramnios (above 95th pct)."""
    p = get_patient(pipeline_results, "P009")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "polyhydramnios"
    assert p["afi"]["percentile"] > 95.0


def test_afi_p010_oligohydramnios(pipeline_results):
    """P010 AFI=65 at GA=38 should be oligohydramnios."""
    p = get_patient(pipeline_results, "P010")
    assert p["afi"] is not None
    assert p["afi"]["classification"] == "oligohydramnios"
    assert p["afi"]["percentile"] < 5.0


def test_afi_percentile_p002_value(pipeline_results):
    """AFI percentile value for P002 must match log-normal model."""
    p = get_patient(pipeline_results, "P002")
    expected = correct_afi_percentile(145, 20)
    assert abs(p["afi"]["percentile"] - expected) < 2.0


def test_afi_percentile_p010_value(pipeline_results):
    """AFI percentile value for P010 must match log-normal model."""
    p = get_patient(pipeline_results, "P010")
    expected = correct_afi_percentile(65, 38)
    assert abs(p["afi"]["percentile"] - expected) < 2.0
