"""
Tests for the ASHRAE psychrometric calculator and HVAC coil process simulator.
Validates against ASHRAE Handbook - Fundamentals (2017) reference values.

"""

import subprocess
import math
import os
import pytest


PROGRAM = "/app/psychro_calc"


# ---------------------------------------------------------------------------
# Reference implementation — correct ASHRAE SI psychrometric equations
# Used to compute golden values for COIL process tests.
# ---------------------------------------------------------------------------

def _ref_sat_vap_pres(tdb):
    """Correct saturation vapor pressure (Pa) per ASHRAE eqn 5 & 6."""
    T = tdb + 273.15
    if tdb <= 0.01:  # triple point
        lnpws = (-5.6745359e3 / T + 6.3925247 - 9.677843e-3 * T
                 + 6.2215701e-7 * T**2 + 2.0747825e-9 * T**3
                 - 9.484024e-13 * T**4 + 4.1635019 * math.log(T))
    else:
        lnpws = (-5.8002206e3 / T + 1.3914993 - 4.8640239e-2 * T
                 + 4.1764768e-5 * T**2 - 1.4452093e-8 * T**3
                 + 6.5459673 * math.log(T))
    return math.exp(lnpws)


def _ref_hum_ratio_from_vp(vp, p):
    """Humidity ratio from vapor pressure, eqn 20."""
    return max(0.621945 * vp / (p - vp), 1e-7)


def _ref_sat_hum_ratio(tdb, p):
    """Saturated humidity ratio."""
    return _ref_hum_ratio_from_vp(_ref_sat_vap_pres(tdb), p)


def _ref_hum_ratio_from_twb(tdb, twb, p):
    """Humidity ratio from wet-bulb, eqn 33/35."""
    wsstar = _ref_sat_hum_ratio(twb, p)
    if twb >= 0.0:
        w = ((2501.0 - 2.326 * twb) * wsstar - 1.006 * (tdb - twb)) / \
            (2501.0 + 1.86 * tdb - 4.186 * twb)
    else:
        w = ((2830.0 - 0.24 * twb) * wsstar - 1.006 * (tdb - twb)) / \
            (2830.0 + 1.86 * tdb - 2.1 * twb)
    return max(w, 1e-7)


def _ref_enthalpy(tdb, w):
    """Moist air enthalpy (J/kg_da), eqn 30."""
    return (1.006 * tdb + w * (2501.0 + 1.86 * tdb)) * 1000.0


def _ref_volume(tdb, w, p):
    """Moist air specific volume (m^3/kg_da), eqn 26."""
    return 287.042 * (tdb + 273.15) * (1.0 + 1.607858 * w) / p


def _ref_tdb_from_h_w(h, w):
    """Dry-bulb from enthalpy and humidity ratio (inverse of eqn 30)."""
    return (h / 1000.0 - 2501.0 * w) / (1.006 + 1.86 * w)


# ---------------------------------------------------------------------------
# Helper to communicate with the C program
# ---------------------------------------------------------------------------

def _run(cmd_str):
    """Send one command to psychro_calc, return stdout line."""
    result = subprocess.run(
        [PROGRAM],
        input=cmd_str + "\n",
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, \
        f"psychro_calc failed (rc={result.returncode}): {result.stderr}"
    return result.stdout.strip()


def _run_float(cmd_str):
    """Send one command and return a single float."""
    return float(_run(cmd_str))


def _run_floats(cmd_str):
    """Send one command and return list of floats."""
    return [float(x) for x in _run(cmd_str).split()]


# ---------------------------------------------------------------------------
# Test: saturation vapor pressure (catches reversed triple-point branching)
# Reference: ASHRAE Handbook 2017 Table 3
# ---------------------------------------------------------------------------

class TestSatVapPres:

    @pytest.mark.parametrize("tdb,expected,tol_kind,tol", [
        (-60,  1.08,      "abs", 0.01),
        (-20,  103.24,    "rel", 0.0003),
        (-5,   401.74,    "rel", 0.0003),
        (5,    872.6,     "rel", 0.0003),
        (25,   3169.7,    "rel", 0.0003),
        (50,   12351.3,   "rel", 0.0003),
        (100,  101418.0,  "rel", 0.0003),
        (150,  476101.4,  "rel", 0.0003),
    ])
    def test_ashrae_table3(self, tdb, expected, tol_kind, tol):
        val = _run_float(f"SATVP {tdb}")
        if tol_kind == "abs":
            assert abs(val - expected) <= tol, \
                f"SATVP({tdb}): got {val}, expected {expected} ± {tol}"
        else:
            assert val == pytest.approx(expected, rel=tol), \
                f"SATVP({tdb}): got {val}, expected {expected} rel={tol}"


# ---------------------------------------------------------------------------
# Test: saturation humidity ratio
# Reference: ASHRAE Handbook 2017 Table 2
# ---------------------------------------------------------------------------

class TestSatHumRatio:

    @pytest.mark.parametrize("tdb,expected,tol", [
        (-50, 0.0000243, 0.01),
        (-5,  0.0024863, 0.005),
        (5,   0.005425,  0.005),
        (25,  0.020173,  0.005),
    ])
    def test_ashrae_table2(self, tdb, expected, tol):
        val = _run_float(f"SATW {tdb} 101325")
        assert val == pytest.approx(expected, rel=tol), \
            f"SATW({tdb}): got {val}, expected {expected}"


# ---------------------------------------------------------------------------
# Test: humidity ratio from wet-bulb (catches below-freezing formula bug)
# Reference: Excel-validated values from PsychroLib test suite
# ---------------------------------------------------------------------------

class TestHumRatioFromWetBulb:

    def test_above_freezing(self):
        val = _run_float("W_WB 30 25 95461")
        assert val == pytest.approx(0.0192281274241096, rel=0.0003)

    def test_below_freezing(self):
        val = _run_float("W_WB -1 -5 95461")
        assert val == pytest.approx(0.00120399819933844, rel=0.0003)


# ---------------------------------------------------------------------------
# Test: wet-bulb from humidity ratio (catches tolerance bug)
# ---------------------------------------------------------------------------

class TestWetBulbPrecision:

    def test_round_trip_above_freezing(self):
        """Compute W from (Tdb=30, Twb=25), then recover Twb from W."""
        w = _run_float("W_WB 30 25 95461")
        twb = _run_float(f"WB_W 30 {w:.10f} 95461")
        assert twb == pytest.approx(25.0, abs=0.002), \
            f"Round-trip Twb: got {twb}, expected 25.0"

    def test_round_trip_moderate(self):
        """Compute W from (Tdb=20, Twb=14), then recover Twb from W."""
        w = _run_float("W_WB 20 14 101325")
        twb = _run_float(f"WB_W 20 {w:.10f} 101325")
        assert twb == pytest.approx(14.0, abs=0.002), \
            f"Round-trip Twb: got {twb}, expected 14.0"


# ---------------------------------------------------------------------------
# Test: moist air enthalpy, volume, density (volume catches coefficient bug)
# Reference: Excel-validated values from PsychroLib test suite
# ---------------------------------------------------------------------------

class TestMoistAirProperties:

    def test_enthalpy(self):
        val = _run_float("ENTHALPY 30 0.02")
        assert val == pytest.approx(81316.0, rel=0.0003)

    def test_volume(self):
        val = _run_float("VOLUME 30 0.02 95461")
        assert val == pytest.approx(0.940855374352943, rel=0.0003)

    def test_density(self):
        val = _run_float("DENSITY 30 0.02 95461")
        assert val == pytest.approx(1.08411986348219, rel=0.0003)

    def test_enthalpy_inverse(self):
        """Verify GetTDryBulbFromEnthalpyAndHumRatio via STATE_WB output."""
        vals = _run_floats("STATE_WB 30 25 95461")
        W = vals[0]
        h = vals[5]
        # h should be consistent with (Tdb=30, W)
        h_ref = _ref_enthalpy(30, W)
        assert h == pytest.approx(h_ref, rel=0.001)


# ---------------------------------------------------------------------------
# Test: full psychrometric state — ASHRAE Example 1 SI
# Tdb = 40 C, Twb = 20 C, P = 101325 Pa
# Reference: ASHRAE Handbook 2017 ch. 1 Example 1
# ---------------------------------------------------------------------------

class TestASHRAEExample1:

    def test_from_wet_bulb(self):
        vals = _run_floats("STATE_WB 40 20 101325")
        # Output: W Tdp Twb RH VapPres h v density
        W, Tdp, Twb, RH, VapPres, h, v, density = vals

        assert W == pytest.approx(0.0065, abs=0.0001)
        assert Tdp == pytest.approx(7.0, abs=0.5)
        assert RH == pytest.approx(0.14, abs=0.01)
        assert h == pytest.approx(56700, abs=200)
        assert v == pytest.approx(0.896, rel=0.01)

    def test_round_trip_via_dew_point(self):
        """Compute state from Twb, then recompute Twb from Tdp."""
        vals1 = _run_floats("STATE_WB 40 20 101325")
        Tdp = vals1[1]
        vals2 = _run_floats(f"STATE_DP 40 {Tdp:.4f} 101325")
        Twb_recovered = vals2[2]
        assert Twb_recovered == pytest.approx(20.0, abs=0.15)

    def test_round_trip_via_relhum(self):
        """Compute state from Twb, then recompute Twb from RH."""
        vals1 = _run_floats("STATE_WB 40 20 101325")
        RH = vals1[3]
        vals2 = _run_floats(f"STATE_RH 40 {RH:.6f} 101325")
        Twb_recovered = vals2[2]
        assert Twb_recovered == pytest.approx(20.0, abs=0.15)


# ---------------------------------------------------------------------------
# Test: HVAC cooling coil process
# ---------------------------------------------------------------------------

class TestCoilProcess:

    def _compute_reference(self, oa_tdb, oa_twb, ra_tdb, ra_rh,
                           oa_frac, bf, target_tdb, airflow, p):
        """Compute reference coil process values using correct equations."""
        # Outdoor air state
        w_oa = _ref_hum_ratio_from_twb(oa_tdb, oa_twb, p)
        h_oa = _ref_enthalpy(oa_tdb, w_oa)

        # Return air state
        vp_ra = ra_rh * _ref_sat_vap_pres(ra_tdb)
        w_ra = _ref_hum_ratio_from_vp(vp_ra, p)
        h_ra = _ref_enthalpy(ra_tdb, w_ra)

        # Mixed air
        w_mix = oa_frac * w_oa + (1 - oa_frac) * w_ra
        h_mix = oa_frac * h_oa + (1 - oa_frac) * h_ra
        tdb_mix = _ref_tdb_from_h_w(h_mix, w_mix)

        # Apparatus dew point
        adp = (target_tdb - bf * tdb_mix) / (1 - bf)

        # Leaving air
        leaving_tdb = bf * tdb_mix + (1 - bf) * adp  # == target_tdb
        w_sat_adp = _ref_sat_hum_ratio(adp, p)
        leaving_w = bf * w_mix + (1 - bf) * w_sat_adp
        leaving_h = _ref_enthalpy(leaving_tdb, leaving_w)

        # Loads
        q_total = airflow * (h_mix - leaving_h) / 1000.0
        q_sensible = airflow * 1.006 * (tdb_mix - leaving_tdb)
        q_latent = q_total - q_sensible

        return dict(
            mixed_tdb=tdb_mix, mixed_w=w_mix, adp=adp,
            leaving_tdb=leaving_tdb, leaving_w=leaving_w,
            q_total=q_total, q_sensible=q_sensible, q_latent=q_latent,
        )

    def test_summer_cooling_scenario(self):
        """
        OA: 35 C, 24 C WB  |  RA: 24 C, 50% RH
        30% outdoor air, bypass factor 0.15, target supply 13 C
        airflow 2 kg/s, pressure 101325 Pa
        """
        ref = self._compute_reference(35, 24, 24, 0.5,
                                      0.30, 0.15, 13, 2, 101325)

        vals = _run_floats("COIL 35 24 24 0.5 0.30 0.15 13 2 101325")
        mixed_tdb, mixed_w, adp, leaving_tdb, leaving_w, \
            q_total, q_sensible, q_latent = vals

        assert mixed_tdb == pytest.approx(ref["mixed_tdb"], rel=0.002)
        assert mixed_w == pytest.approx(ref["mixed_w"], rel=0.002)
        assert adp == pytest.approx(ref["adp"], rel=0.002)
        assert leaving_tdb == pytest.approx(ref["leaving_tdb"], abs=0.05)
        assert leaving_w == pytest.approx(ref["leaving_w"], rel=0.005)
        assert q_total == pytest.approx(ref["q_total"], rel=0.005)
        assert q_sensible == pytest.approx(ref["q_sensible"], rel=0.005)
        assert q_latent == pytest.approx(ref["q_latent"], rel=0.02)

    def test_high_oa_scenario(self):
        """
        OA: 32 C, 26 C WB  |  RA: 25 C, 55% RH
        40% outdoor air, bypass factor 0.10, target supply 12.5 C
        airflow 1.5 kg/s, pressure 101325 Pa
        """
        ref = self._compute_reference(32, 26, 25, 0.55,
                                      0.40, 0.10, 12.5, 1.5, 101325)

        vals = _run_floats("COIL 32 26 25 0.55 0.40 0.10 12.5 1.5 101325")
        mixed_tdb, mixed_w, adp, leaving_tdb, leaving_w, \
            q_total, q_sensible, q_latent = vals

        assert mixed_tdb == pytest.approx(ref["mixed_tdb"], rel=0.002)
        assert mixed_w == pytest.approx(ref["mixed_w"], rel=0.002)
        assert adp == pytest.approx(ref["adp"], rel=0.002)
        assert leaving_tdb == pytest.approx(ref["leaving_tdb"], abs=0.05)
        assert leaving_w == pytest.approx(ref["leaving_w"], rel=0.005)
        assert q_total == pytest.approx(ref["q_total"], rel=0.005)
        assert q_sensible == pytest.approx(ref["q_sensible"], rel=0.005)
        assert q_latent == pytest.approx(ref["q_latent"], rel=0.02)

    def test_loads_positive(self):
        """Cooling loads should be positive for a summer scenario."""
        vals = _run_floats("COIL 35 24 24 0.5 0.30 0.15 13 2 101325")
        q_total, q_sensible, q_latent = vals[5], vals[6], vals[7]
        assert q_total > 0, "Total cooling load must be positive"
        assert q_sensible > 0, "Sensible cooling load must be positive"
        assert q_latent > 0, "Latent cooling load must be positive"

    def test_leaving_temp_matches_target(self):
        """Coil leaving temperature should equal the target supply temp."""
        vals = _run_floats("COIL 35 24 24 0.5 0.30 0.15 13 2 101325")
        leaving_tdb = vals[3]
        assert leaving_tdb == pytest.approx(13.0, abs=0.05)
