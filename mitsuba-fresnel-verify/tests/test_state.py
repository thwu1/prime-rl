"""Verify microfacet renderer output correctness."""

import json
import math
import pytest

RESULTS_PATH = '/app/output.json'

# Material parameters (independent copy — not read from scene.json)
EXT_IOR = 1.0
INT_IOR = 1.5
CONDUCTOR_ETA = [0.183, 0.312, 1.557]
CONDUCTOR_K = [3.424, 2.385, 1.893]
ALPHA = 0.3

FRESNEL_ANGLES = [0, 15, 30, 45, 60, 75, 85]
NDF_ANGLES = [0, 10, 20, 30, 45, 60]
G1_ANGLES = [15, 30, 45, 60, 75, 85]
BRDF_PAIRS = [
    {"theta_i": 30, "theta_o": 30, "phi_o": 180, "label": "specular_30"},
    {"theta_i": 60, "theta_o": 60, "phi_o": 180, "label": "specular_60"},
    {"theta_i": 45, "theta_o": 45, "phi_o": 180, "label": "specular_45"},
    {"theta_i": 30, "theta_o": 50, "phi_o": 180, "label": "offspec_30_50"},
    {"theta_i": 75, "theta_o": 30, "phi_o": 180, "label": "offspec_75_30"},
]

# Tolerances
TOL_FRESNEL_DIEL = 1e-6
TOL_FRESNEL_COND = 1e-4
TOL_NDF_REL = 0.02
TOL_NDF_ABS = 1e-6
TOL_G1 = 0.015
TOL_BRDF_REL = 0.05
TOL_BRDF_ABS = 1e-5


# --------------- Reference implementations ---------------

def ref_fresnel_dielectric(cos_i, n1, n2):
    sin2_t = (n1 / n2) ** 2 * (1.0 - cos_i ** 2)
    if sin2_t >= 1.0:
        return 1.0
    cos_t = math.sqrt(1.0 - sin2_t)
    rs = (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)
    rp = (n2 * cos_i - n1 * cos_t) / (n2 * cos_i + n1 * cos_t)
    return 0.5 * (rs * rs + rp * rp)


def ref_fresnel_conductor(cos_i, eta, k):
    cos2 = cos_i ** 2
    sin2 = 1.0 - cos2
    eta2 = eta ** 2
    k2 = k ** 2
    t0 = eta2 - k2 - sin2
    a2b2 = math.sqrt(t0 ** 2 + 4.0 * eta2 * k2)
    t1 = a2b2 + cos2
    a = math.sqrt(max(0.0, 0.5 * (a2b2 + t0)))
    t2 = 2.0 * a * cos_i
    rs = (t1 - t2) / (t1 + t2)
    t3 = cos2 * a2b2 + sin2 * sin2
    t4 = t2 * sin2
    rp = rs * (t3 - t4) / (t3 + t4)
    return 0.5 * (rs + rp)


def ref_beckmann_ndf(cos_h, alpha):
    if cos_h <= 1e-10:
        return 0.0
    cos2 = cos_h ** 2
    cos4 = cos2 ** 2
    tan2 = (1.0 - cos2) / cos2
    return math.exp(-tan2 / (alpha ** 2)) / (math.pi * alpha ** 2 * cos4)


def ref_smith_g1(cos_v, alpha):
    """Exact Smith G1 via error function."""
    if cos_v >= 1.0:
        return 1.0
    if cos_v <= 0.0:
        return 0.0
    sin_v = math.sqrt(1.0 - cos_v ** 2)
    tan_v = sin_v / cos_v
    a = 1.0 / (alpha * tan_v)
    return 2.0 / (1.0 + math.erf(a) + math.exp(-a * a) / (a * math.sqrt(math.pi)))


# --------------- Fixtures ---------------

@pytest.fixture(scope='module')
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


# --------------- Dielectric Fresnel ---------------

class TestDielectricFresnel:
    def test_structure(self, results):
        assert 'glass_fresnel' in results
        for a in FRESNEL_ANGLES:
            assert str(a) in results['glass_fresnel']

    def test_values(self, results):
        for angle in FRESNEL_ANGLES:
            measured = results['glass_fresnel'][str(angle)]
            expected = ref_fresnel_dielectric(
                math.cos(math.radians(angle)), EXT_IOR, INT_IOR)
            assert abs(measured - expected) < TOL_FRESNEL_DIEL, \
                f"Dielectric Fresnel at {angle} deg: {measured} != {expected}"

    def test_normal_incidence(self, results):
        measured = results['glass_fresnel']['0']
        expected = ((INT_IOR - EXT_IOR) / (INT_IOR + EXT_IOR)) ** 2
        assert abs(measured - expected) < TOL_FRESNEL_DIEL

    def test_monotonically_increasing(self, results):
        vals = [results['glass_fresnel'][str(a)] for a in FRESNEL_ANGLES]
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1] + TOL_FRESNEL_DIEL


# --------------- Conductor Fresnel ---------------

class TestConductorFresnel:
    def test_structure(self, results):
        assert 'gold_fresnel' in results
        for a in FRESNEL_ANGLES:
            assert str(a) in results['gold_fresnel']
            val = results['gold_fresnel'][str(a)]
            assert isinstance(val, list) and len(val) == 3

    def test_values(self, results):
        for angle in FRESNEL_ANGLES:
            measured = results['gold_fresnel'][str(angle)]
            cos_i = math.cos(math.radians(angle))
            for ch in range(3):
                expected = ref_fresnel_conductor(
                    cos_i, CONDUCTOR_ETA[ch], CONDUCTOR_K[ch])
                assert abs(measured[ch] - expected) < TOL_FRESNEL_COND, \
                    f"Conductor Fresnel at {angle} deg ch{ch}: " \
                    f"{measured[ch]} != {expected}"

    def test_normal_incidence_formula(self, results):
        measured = results['gold_fresnel']['0']
        for ch in range(3):
            eta, k = CONDUCTOR_ETA[ch], CONDUCTOR_K[ch]
            expected = ((eta - 1) ** 2 + k ** 2) / ((eta + 1) ** 2 + k ** 2)
            assert abs(measured[ch] - expected) < TOL_FRESNEL_COND

    def test_physical_range(self, results):
        for angle in FRESNEL_ANGLES:
            vals = results['gold_fresnel'][str(angle)]
            for ch in range(3):
                assert 0.0 <= vals[ch] <= 1.0, \
                    f"Conductor Fresnel at {angle} deg ch{ch} = {vals[ch]} " \
                    f"outside [0,1]"


# --------------- Beckmann NDF ---------------

class TestBeckmannNDF:
    def test_structure(self, results):
        assert 'beckmann_ndf_eval' in results
        for a in NDF_ANGLES:
            assert str(a) in results['beckmann_ndf_eval']

    def test_values(self, results):
        for angle in NDF_ANGLES:
            measured = results['beckmann_ndf_eval'][str(angle)]
            expected = ref_beckmann_ndf(math.cos(math.radians(angle)), ALPHA)
            tol = max(TOL_NDF_ABS, TOL_NDF_REL * abs(expected))
            assert abs(measured - expected) < tol, \
                f"NDF at {angle} deg: {measured} != {expected} (tol={tol})"

    def test_peak_at_normal(self, results):
        val_0 = results['beckmann_ndf_eval']['0']
        for angle in NDF_ANGLES[1:]:
            assert val_0 > results['beckmann_ndf_eval'][str(angle)], \
                f"D(0)={val_0} should exceed D({angle})=" \
                f"{results['beckmann_ndf_eval'][str(angle)]}"

    def test_positive(self, results):
        for angle in NDF_ANGLES:
            assert results['beckmann_ndf_eval'][str(angle)] >= 0


# --------------- Smith G1 ---------------

class TestSmithG1:
    def test_structure(self, results):
        assert 'smith_g1_eval' in results
        for a in G1_ANGLES:
            assert str(a) in results['smith_g1_eval']

    def test_values(self, results):
        for angle in G1_ANGLES:
            measured = results['smith_g1_eval'][str(angle)]
            expected = ref_smith_g1(math.cos(math.radians(angle)), ALPHA)
            assert abs(measured - expected) < TOL_G1, \
                f"G1 at {angle} deg: {measured} != {expected}"

    def test_physical_range(self, results):
        for angle in G1_ANGLES:
            val = results['smith_g1_eval'][str(angle)]
            assert 0.0 <= val <= 1.0, \
                f"G1 at {angle} deg = {val} outside [0,1]"

    def test_decreasing_with_angle(self, results):
        vals = [results['smith_g1_eval'][str(a)] for a in G1_ANGLES]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - TOL_G1, \
                f"G1 not decreasing: G1({G1_ANGLES[i]})={vals[i]} < " \
                f"G1({G1_ANGLES[i + 1]})={vals[i + 1]}"


# --------------- BRDF Evaluation ---------------

class TestBRDFEval:
    def test_structure(self, results):
        assert 'gold_brdf_eval' in results
        for pair in BRDF_PAIRS:
            assert pair['label'] in results['gold_brdf_eval']

    def test_values(self, results):
        for pair in BRDF_PAIRS:
            measured = results['gold_brdf_eval'][pair['label']]
            ti = math.radians(pair['theta_i'])
            to = math.radians(pair['theta_o'])
            po = math.radians(pair['phi_o'])
            wi = (math.sin(ti), 0.0, math.cos(ti))
            wo = (math.sin(to) * math.cos(po),
                  math.sin(to) * math.sin(po),
                  math.cos(to))
            hx, hy, hz = wi[0] + wo[0], wi[1] + wo[1], wi[2] + wo[2]
            hmag = math.sqrt(hx ** 2 + hy ** 2 + hz ** 2)
            h = (hx / hmag, hy / hmag, hz / hmag)
            cos_h = h[2]
            wi_h = wi[0] * h[0] + wi[1] * h[1] + wi[2] * h[2]

            D = ref_beckmann_ndf(cos_h, ALPHA)
            G = ref_smith_g1(wi[2], ALPHA) * ref_smith_g1(wo[2], ALPHA)

            for ch in range(3):
                F = ref_fresnel_conductor(
                    abs(wi_h), CONDUCTOR_ETA[ch], CONDUCTOR_K[ch])
                # Cosine-weighted: f_r * cos(theta_o) = F*D*G / (4*cos_i)
                expected = F * D * G / (4.0 * wi[2])
                tol = max(TOL_BRDF_ABS, TOL_BRDF_REL * abs(expected))
                assert abs(measured[ch] - expected) < tol, \
                    f"BRDF {pair['label']} ch{ch}: " \
                    f"{measured[ch]} != {expected} (tol={tol})"

    def test_specular_peak(self, results):
        spec_avg = sum(results['gold_brdf_eval']['specular_30']) / 3.0
        off_avg = sum(results['gold_brdf_eval']['offspec_30_50']) / 3.0
        assert spec_avg > off_avg, \
            f"Specular ({spec_avg}) should exceed off-specular ({off_avg})"

    def test_positive(self, results):
        for pair in BRDF_PAIRS:
            vals = results['gold_brdf_eval'][pair['label']]
            for ch in range(3):
                assert vals[ch] >= 0, \
                    f"BRDF {pair['label']} ch{ch} = {vals[ch]} is negative"


# --------------- MC Reflectance ---------------

class TestMCReflectance:
    def test_structure(self, results):
        assert 'gold_mc_refl' in results
        val = results['gold_mc_refl']
        assert isinstance(val, list) and len(val) == 3

    def test_positive(self, results):
        for ch in range(3):
            assert results['gold_mc_refl'][ch] > 0, \
                f"MC ch{ch} should be positive"

    def test_bounded_by_fresnel(self, results):
        mc = results['gold_mc_refl']
        cos_i = math.cos(math.radians(30))
        for ch in range(3):
            F = ref_fresnel_conductor(
                cos_i, CONDUCTOR_ETA[ch], CONDUCTOR_K[ch])
            assert mc[ch] > 0.70 * F, \
                f"MC ch{ch}={mc[ch]} too low vs 0.70*F_smooth={0.70 * F}"
            assert mc[ch] < F + 0.08, \
                f"MC ch{ch}={mc[ch]} too high vs F_smooth+0.08={F + 0.08}"

    def test_channel_ordering(self, results):
        mc = results['gold_mc_refl']
        assert mc[0] > mc[1] > mc[2], \
            f"Expected R > G > B ordering: {mc}"
