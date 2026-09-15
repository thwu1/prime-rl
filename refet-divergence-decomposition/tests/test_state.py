"""
Tests for ASCE Standardized Reference Evapotranspiration engine.

Golden reference values derived from the Fallon, NV AgriMet station
(elev=1208.5m, lat=39.4575deg, lon=-118.77388deg, zw=3.0m)
for 2015-07-01 (DOY 182).
"""


import math
import sys

import pytest

sys.path.insert(0, '/app')
from et_engine import compute_daily, compute_hourly, decompose_daily_divergence


# ---------------------------------------------------------------------------
# Station and weather parameters
# ---------------------------------------------------------------------------
ELEV = 1208.5
LAT_DEG = 39.4575
LON_DEG = -118.77388
LAT = LAT_DEG * math.pi / 180.0
LON = LON_DEG * math.pi / 180.0
ZW = 3.0

# Daily inputs (DOY 182, 2015-07-01)
DOY = 182
TMIN = (66.65 - 32.0) * 5.0 / 9.0       # 19.25 C
TMAX = (102.80 - 32.0) * 5.0 / 9.0      # ~39.333 C
EA_D = 1.2206674169951346                 # kPa, from Tdew=49.84F
RS_D = 674.07 * 0.041868                 # MJ m-2 d-1
UZ_D = 4.80 * 0.44704                    # m s-1

# Hourly inputs (DOY 182, 18:00 UTC = 11:00 AM PDT)
TMEAN_H = (91.80 - 32.0) * 5.0 / 9.0    # ~33.222 C
EA_H = 1.1990099614301906                # kPa
RS_H = 61.16 * 0.041868                  # MJ m-2 h-1
UZ_H = 3.33 * 0.44704                    # m s-1
TIME_H = 18.0


# ===========================================================================
# Daily ASCE method tests
# ===========================================================================
class TestDailyASCE:
    """Verify daily reference ET using ASCE simplified method."""

    @pytest.fixture(scope='class')
    def result(self):
        return compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, method='asce'
        )

    def test_pair(self, result):
        assert result['pair'] == pytest.approx(87.80710537212929, rel=1e-8)

    def test_es_slope(self, result):
        assert result['es_slope'] == pytest.approx(0.23488581814172638, rel=1e-8)

    def test_es(self, result):
        assert result['es'] == pytest.approx(4.6747236227258835, rel=1e-8)

    def test_ea(self, result):
        assert result['ea'] == pytest.approx(EA_D, rel=1e-10)

    def test_dr(self, result):
        assert result['dr'] == pytest.approx(0.9670012223491632, rel=1e-8)

    def test_u2(self, result):
        assert result['u2'] == pytest.approx(1.976111757722194, rel=1e-8)

    def test_delta(self, result):
        assert result['delta'] == pytest.approx(0.4029517192078854, rel=1e-8)

    def test_ra(self, result):
        assert result['ra'] == pytest.approx(41.64824567735701, rel=1e-8)

    def test_vpd_positive(self, result):
        assert result['vpd'] > 0

    def test_eto_less_than_etr(self, result):
        """ETo (grass, cn=900) must be less than ETr (alfalfa, cn=1600)."""
        assert result['eto'] < result['etr']

    def test_eto_reasonable(self, result):
        """ASCE ETo should fall in the specified range for Fallon station."""
        assert result['eto'] > 7.94
        assert result['eto'] < 8.10

    def test_etr(self, result):
        assert result['etr'] == pytest.approx(10.626087665395694, rel=1e-6)


# ===========================================================================
# Daily RefET method tests
# ===========================================================================
class TestDailyRefET:
    """Verify daily reference ET using RefET full-precision method."""

    @pytest.fixture(scope='class')
    def result(self):
        return compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, method='refet'
        )

    def test_pair(self, result):
        assert result['pair'] == pytest.approx(87.81876435813037, rel=1e-8)

    def test_es_slope(self, result):
        assert result['es_slope'] == pytest.approx(0.23489129849801055, rel=1e-8)

    def test_es_same(self, result):
        """es is computed identically in both methods."""
        assert result['es'] == pytest.approx(4.6747236227258835, rel=1e-8)

    def test_delta(self, result):
        assert result['delta'] == pytest.approx(0.40352881013673136, rel=1e-5)

    def test_ra(self, result):
        assert result['ra'] == pytest.approx(41.67610845067083, rel=1e-8)

    def test_rso(self, result):
        """RefET uses the full Appendix D clear-sky model."""
        assert result['rso'] == pytest.approx(31.565939444861765, rel=1e-6)

    def test_fcd(self, result):
        assert result['fcd'] == pytest.approx(0.8569860867772078, rel=1e-6)

    def test_rnl(self, result):
        assert result['rnl'] == pytest.approx(6.556533974825727, rel=1e-6)

    def test_rn(self, result):
        assert result['rn'] == pytest.approx(15.174377350374275, rel=1e-6)

    def test_eto(self, result):
        assert result['eto'] == pytest.approx(7.9422320475712835, rel=1e-6)

    def test_etr(self, result):
        assert result['etr'] == pytest.approx(10.571314344056955, rel=1e-6)


# ===========================================================================
# Hourly ASCE method tests
# ===========================================================================
class TestHourlyASCE:
    """Verify hourly reference ET using ASCE simplified method."""

    @pytest.fixture(scope='class')
    def result(self):
        return compute_hourly(
            TMEAN_H, EA_H, RS_H, UZ_H, ZW, ELEV, LAT, LON, DOY, TIME_H,
            method='asce'
        )

    def test_u2(self, result):
        assert result['u2'] == pytest.approx(1.3709275319197722, rel=1e-8)

    def test_es(self, result):
        assert result['es'] == pytest.approx(5.09318785259078, rel=1e-8)

    def test_eto(self, result):
        assert result['eto'] == pytest.approx(0.6063515410076268, rel=1e-5)

    def test_etr(self, result):
        assert result['etr'] == pytest.approx(0.7196369609713682, rel=1e-5)


# ===========================================================================
# Hourly RefET method tests
# ===========================================================================
class TestHourlyRefET:
    """Verify hourly reference ET using RefET full-precision method."""

    @pytest.fixture(scope='class')
    def result(self):
        return compute_hourly(
            TMEAN_H, EA_H, RS_H, UZ_H, ZW, ELEV, LAT, LON, DOY, TIME_H,
            method='refet'
        )

    def test_eto(self, result):
        assert result['eto'] == pytest.approx(0.6068613650177561, rel=1e-5)

    def test_etr(self, result):
        assert result['etr'] == pytest.approx(0.7201865213918281, rel=1e-5)

    def test_ra(self, result):
        assert result['ra'] == pytest.approx(4.30824147948541, rel=1e-6)


# ===========================================================================
# Divergence decomposition tests
# ===========================================================================
class TestDecomposition:
    """Verify the daily divergence decomposition between method variants."""

    @pytest.fixture(scope='class')
    def decomp(self):
        return decompose_daily_divergence(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, surface='etr'
        )

    def test_total_value(self, decomp):
        expected = 10.626087665395694 - 10.571314344056955
        assert decomp['total'] == pytest.approx(expected, rel=1e-6)

    def test_total_sign(self, decomp):
        """ASCE ETr > RefET ETr for this station/date."""
        assert decomp['total'] > 0

    def test_required_keys(self, decomp):
        required = {
            'total', 'air_pressure', 'es_slope', 'declination',
            'solar_constant', 'clear_sky_radiation', 'residual'
        }
        assert required.issubset(set(decomp.keys()))

    def test_sum_equals_total(self, decomp):
        contrib_keys = [
            'air_pressure', 'es_slope', 'declination',
            'solar_constant', 'clear_sky_radiation', 'residual'
        ]
        contrib_sum = sum(decomp[k] for k in contrib_keys)
        assert contrib_sum == pytest.approx(decomp['total'], rel=1e-10)

    def test_residual_small(self, decomp):
        """Residual (interaction effects) should be small vs total."""
        assert abs(decomp['residual']) < 0.15 * abs(decomp['total'])

    def test_contributions_bounded(self, decomp):
        """No single contribution should exceed three times the total divergence."""
        for key in ['air_pressure', 'es_slope', 'declination',
                    'solar_constant', 'clear_sky_radiation']:
            assert abs(decomp[key]) < 3.0 * abs(decomp['total'])

    def test_clear_sky_radiation_dominant(self, decomp):
        """Clear-sky radiation model difference should be the largest contributor."""
        contribs = {k: abs(decomp[k]) for k in [
            'air_pressure', 'es_slope', 'declination',
            'solar_constant', 'clear_sky_radiation'
        ]}
        assert contribs['clear_sky_radiation'] == max(contribs.values())

    def test_clear_sky_radiation_positive(self, decomp):
        """Switching Rso from simple to full should decrease ET (positive contribution)."""
        assert decomp['clear_sky_radiation'] > 0


# ===========================================================================
# Edge case and structural tests
# ===========================================================================
class TestEdgeCases:
    """Test edge cases and output structure."""

    def test_high_latitude_polar_night_ra_zero(self):
        """At 80N in winter (DOY 1), extraterrestrial radiation should be zero."""
        lat_high = 80.0 * math.pi / 180.0
        result = compute_daily(
            tmin=-20.0, tmax=-10.0, ea=0.2, rs=0.5,
            uz=2.0, zw=2.0, elev=100.0, lat=lat_high, doy=1,
            method='asce'
        )
        assert result['ra'] == pytest.approx(0.0, abs=1e-10)
        assert not math.isnan(result['eto'])
        assert not math.isinf(result['eto'])

    def test_high_latitude_summer_omega_s_pi(self):
        """At 70N in summer (DOY 182), sunset hour angle should be pi (24h daylight)."""
        lat_high = 70.0 * math.pi / 180.0
        result = compute_daily(
            tmin=5.0, tmax=15.0, ea=0.8, rs=15.0,
            uz=2.0, zw=2.0, elev=100.0, lat=lat_high, doy=182,
            method='asce'
        )
        assert result['omega_s'] == pytest.approx(math.pi, rel=1e-6)

    def test_vpd_non_negative_daily(self):
        """Daily VPD should be clipped to zero when ea > es."""
        result = compute_daily(
            tmin=5.0, tmax=10.0, ea=5.0, rs=10.0,
            uz=2.0, zw=2.0, elev=100.0, lat=0.5, doy=100,
            method='asce'
        )
        assert result['vpd'] >= 0.0

    def test_daily_output_keys(self):
        result = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY
        )
        required = {
            'pair', 'tmean', 'es', 'ea', 'es_slope', 'vpd', 'psy', 'u2',
            'delta', 'dr', 'omega_s', 'ra', 'rso', 'fcd', 'rnl', 'rn',
            'eto', 'etr'
        }
        assert required.issubset(set(result.keys()))

    def test_hourly_output_keys(self):
        result = compute_hourly(
            TMEAN_H, EA_H, RS_H, UZ_H, ZW, ELEV, LAT, LON, DOY, TIME_H
        )
        required = {
            'pair', 'es', 'ea', 'es_slope', 'vpd', 'psy', 'u2',
            'delta', 'dr', 'sc', 'omega', 'omega_s', 'ra', 'rso',
            'fcd', 'rnl', 'rn', 'eto', 'etr'
        }
        assert required.issubset(set(result.keys()))

    def test_daily_default_method_is_asce(self):
        """Default method should be 'asce'."""
        r_default = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY
        )
        r_asce = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, method='asce'
        )
        assert r_default['etr'] == pytest.approx(r_asce['etr'], rel=1e-12)

    def test_method_variants_differ_for_etr(self):
        """ASCE and RefET should produce different ETr values."""
        r_asce = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, method='asce'
        )
        r_refet = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY, method='refet'
        )
        assert r_asce['etr'] != pytest.approx(r_refet['etr'], rel=1e-4)

    def test_tmean_correct(self):
        result = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY
        )
        assert result['tmean'] == pytest.approx(0.5 * (TMIN + TMAX), rel=1e-12)

    def test_psy_from_pair(self):
        """Psychrometric constant = 0.000665 * pair."""
        result = compute_daily(
            TMIN, TMAX, EA_D, RS_D, UZ_D, ZW, ELEV, LAT, DOY
        )
        assert result['psy'] == pytest.approx(0.000665 * result['pair'], rel=1e-10)
