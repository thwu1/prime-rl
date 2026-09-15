"""
Independent verification of EUR multicurve calibration, portfolio pricing,
and bucketed PV01 sensitivity computation.

Reads calibrated zero rates from /app/results.json and re-computes all
calibration instrument PVs, portfolio PVs, and PV01 sensitivities using
correct multicurve pricing (log-linear DF interpolation, OIS discounting,
spread added to 3M leg).

"""

import json
import math
import os
import pytest

TOLERANCE = 1.0e-6
PV_TOLERANCE = 0.01
PV01_TOLERANCE = 0.5
BUMP = 0.0001

# ── Market data (EUR, valuation 2015-11-20) ──────────────────────────

MARKET = {
    "OIS:1M": -0.0019,   "OIS:2M": -0.00235,  "OIS:3M": -0.0025,
    "OIS:6M": -0.0028,   "OIS:1Y": -0.0031,   "OIS:2Y": -0.0033,
    "OIS:3Y": -0.0028,   "OIS:4Y": -0.0017,   "OIS:5Y": -0.0006,
    "OIS:7Y":  0.0021,   "OIS:10Y": 0.006,    "OIS:15Y": 0.0102,
    "OIS:20Y": 0.0122,   "OIS:30Y": 0.013,

    "FIX6M:0D": -0.00024, "FRA6M:6Mx12M": -0.0023,
    "IRS6M:2Y": -0.0011,  "IRS6M:3Y": -0.00055,
    "IRS6M:4Y":  0.0005,  "IRS6M:5Y":  0.0018,
    "IRS6M:7Y":  0.0045,  "IRS6M:10Y": 0.0083,
    "IRS6M:15Y": 0.01225, "IRS6M:20Y": 0.014,
    "IRS6M:30Y": 0.01455,

    "FIX3M:0D": -0.00095, "FRA3M:3Mx6M": -0.002,
    "BS3M6M:1Y":  0.00115, "BS3M6M:2Y":  0.00103,
    "BS3M6M:3Y":  0.00103, "BS3M6M:4Y":  0.00106,
    "BS3M6M:5Y":  0.00109, "BS3M6M:7Y":  0.00106,
    "BS3M6M:10Y": 0.00092, "BS3M6M:15Y": 0.00072,
    "BS3M6M:20Y": 0.00059, "BS3M6M:30Y": 0.00043,
}

PORTFOLIO = [
    {"id": "SWAP-1", "type": "IRS6M", "tenor": 5.0,  "rate": 0.0025,  "notional": 10000000.0},
    {"id": "SWAP-2", "type": "IRS6M", "tenor": 10.0, "rate": 0.009,   "notional": 25000000.0},
    {"id": "SWAP-3", "type": "OIS",   "tenor": 2.0,  "rate": -0.003,  "notional": 15000000.0},
    {"id": "SWAP-4", "type": "BS3M6M","tenor": 7.0,  "rate": 0.001,   "notional": 20000000.0},
    {"id": "SWAP-5", "type": "IRS6M", "tenor": 30.0, "rate": 0.016,   "notional": 5000000.0},
]

CURVE_NAMES = ["EUR-DSCON-OIS", "EUR-EURIBOR6M-IRS", "EUR-EURIBOR3M-BS"]
OIS_NODE_COUNT = 14
IRS_NODE_COUNT = 11
BS_NODE_COUNT = 12


# ── Correct curve interpolation (log-linear on DF) ──────────────────

class InterpolatedCurve:
    """Log-linear DF interpolation: ln(DF) is piecewise-linear in t."""

    def __init__(self, times, zero_rates):
        self.times = list(times)
        self.rates = list(zero_rates)

    def discount_factor(self, t):
        if t <= 0.0:
            return 1.0
        if t <= self.times[0]:
            return math.exp(-self.rates[0] * t)
        if t >= self.times[-1]:
            return math.exp(-self.rates[-1] * t)

        idx = 0
        while idx < len(self.times) - 1 and self.times[idx + 1] < t:
            idx += 1

        t1, t2 = self.times[idx], self.times[idx + 1]
        r1, r2 = self.rates[idx], self.rates[idx + 1]
        w = (t - t1) / (t2 - t1)

        # Log-linear on DF  <=>  linear on r*t
        rt = r1 * t1 + (r2 * t2 - r1 * t1) * w
        return math.exp(-rt)

    def forward_rate(self, t1, t2):
        df1 = self.discount_factor(t1)
        df2 = self.discount_factor(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)


# ── Correct pricing functions ────────────────────────────────────────

def ois_swap_pv(disc, tenor, rate):
    flt = 1.0 - disc.discount_factor(tenor)
    fix = 0.0
    if tenor <= 1.0 + 1e-9:
        fix = rate * tenor * disc.discount_factor(tenor)
    else:
        for y in range(1, round(tenor) + 1):
            fix += rate * 1.0 * disc.discount_factor(float(y))
    return flt - fix


def irs_swap_pv(disc, fwd6m, tenor, rate):
    """Correct: OIS discounting, EURIBOR-6M projection."""
    flt = 0.0
    for i in range(round(tenor * 2)):
        t1, t2 = i * 0.5, (i + 1) * 0.5
        flt += fwd6m.forward_rate(t1, t2) * 0.5 * disc.discount_factor(t2)
    fix = 0.0
    for y in range(1, round(tenor) + 1):
        fix += rate * 1.0 * disc.discount_factor(float(y))
    return flt - fix


def basis_swap_pv(disc, fwd3m, fwd6m, tenor, spread):
    """Correct: spread ADDED to 3M leg."""
    leg3 = 0.0
    for i in range(round(tenor * 4)):
        t1, t2 = i * 0.25, (i + 1) * 0.25
        f = fwd3m.forward_rate(t1, t2)
        leg3 += (f + spread) * 0.25 * disc.discount_factor(t2)
    leg6 = 0.0
    for i in range(round(tenor * 2)):
        t1, t2 = i * 0.5, (i + 1) * 0.5
        leg6 += fwd6m.forward_rate(t1, t2) * 0.5 * disc.discount_factor(t2)
    return leg3 - leg6


def fixing_pv(disc, fwd, tenor, rate):
    f = fwd.forward_rate(0.0, tenor)
    df = disc.discount_factor(tenor)
    return (f - rate) * tenor * df


def fra_pv(disc, fwd, start, end, rate):
    f = fwd.forward_rate(start, end)
    tau = end - start
    df = disc.discount_factor(end)
    return (f - rate) * tau * df / (1.0 + f * tau)


def price_swap(disc, e6m, e3m, swap_type, tenor, rate):
    if swap_type == "OIS":
        return ois_swap_pv(disc, tenor, rate)
    elif swap_type == "IRS6M":
        return irs_swap_pv(disc, e6m, tenor, rate)
    elif swap_type == "BS3M6M":
        return basis_swap_pv(disc, e3m, e6m, tenor, rate)
    else:
        raise ValueError(f"Unknown type: {swap_type}")


def compute_pv01(disc, e6m, e3m, swap_type, tenor, rate, notional):
    """Independently compute bucketed PV01 via bump-and-revalue."""
    curves_map = [
        ("EUR-DSCON-OIS", disc),
        ("EUR-EURIBOR6M-IRS", e6m),
        ("EUR-EURIBOR3M-BS", e3m),
    ]
    base_pv = notional * price_swap(disc, e6m, e3m, swap_type, tenor, rate)
    result = {}
    for name, curve in curves_map:
        pv01s = []
        for j in range(len(curve.rates)):
            orig = curve.rates[j]
            curve.rates[j] = orig + BUMP
            bumped_pv = notional * price_swap(
                disc, e6m, e3m, swap_type, tenor, rate)
            pv01s.append(bumped_pv - base_pv)
            curve.rates[j] = orig
        result[name] = pv01s
    return result


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def results():
    with open("/app/results.json") as fh:
        return json.load(fh)


@pytest.fixture
def curves(results):
    d = results["curves"]
    disc = InterpolatedCurve(
        d["EUR-DSCON-OIS"]["times"],
        d["EUR-DSCON-OIS"]["zero_rates"])
    e6m = InterpolatedCurve(
        d["EUR-EURIBOR6M-IRS"]["times"],
        d["EUR-EURIBOR6M-IRS"]["zero_rates"])
    e3m = InterpolatedCurve(
        d["EUR-EURIBOR3M-BS"]["times"],
        d["EUR-EURIBOR3M-BS"]["zero_rates"])
    return disc, e6m, e3m


# ── Structural tests ────────────────────────────────────────────────

class TestResultsStructure:

    def test_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json missing"

    def test_has_all_curves(self, results):
        for name in CURVE_NAMES:
            assert name in results["curves"], f"curve {name} missing"
            c = results["curves"][name]
            assert "times" in c and "zero_rates" in c and "discount_factors" in c
            assert len(c["times"]) == len(c["zero_rates"])
            assert len(c["times"]) > 0

    def test_curve_node_counts(self, results):
        assert len(results["curves"]["EUR-DSCON-OIS"]["times"]) == OIS_NODE_COUNT
        assert len(results["curves"]["EUR-EURIBOR6M-IRS"]["times"]) == IRS_NODE_COUNT
        assert len(results["curves"]["EUR-EURIBOR3M-BS"]["times"]) == BS_NODE_COUNT

    def test_has_instrument_pvs(self, results):
        assert "instrument_pvs" in results
        assert len(results["instrument_pvs"]) == 37

    def test_has_portfolio(self, results):
        assert "portfolio" in results
        for pos in PORTFOLIO:
            sid = pos["id"]
            assert sid in results["portfolio"], f"portfolio {sid} missing"
            entry = results["portfolio"][sid]
            assert "pv" in entry, f"pv missing for {sid}"
            assert "pv01" in entry, f"pv01 missing for {sid}"
            for cn in CURVE_NAMES:
                assert cn in entry["pv01"], f"pv01[{cn}] missing for {sid}"

    def test_portfolio_pv01_lengths(self, results):
        expected_lengths = {
            "EUR-DSCON-OIS": OIS_NODE_COUNT,
            "EUR-EURIBOR6M-IRS": IRS_NODE_COUNT,
            "EUR-EURIBOR3M-BS": BS_NODE_COUNT,
        }
        for pos in PORTFOLIO:
            sid = pos["id"]
            for cn, expected_len in expected_lengths.items():
                actual = results["portfolio"][sid]["pv01"][cn]
                assert len(actual) == expected_len, \
                    f"{sid} pv01[{cn}] has {len(actual)} entries, expected {expected_len}"


# ── OIS calibration tests ───────────────────────────────────────────

class TestOisCalibration:

    TENORS = {
        "1M": 1/12, "2M": 2/12, "3M": 3/12, "6M": 6/12,
        "1Y": 1, "2Y": 2, "3Y": 3, "4Y": 4,
        "5Y": 5, "7Y": 7, "10Y": 10, "15Y": 15,
        "20Y": 20, "30Y": 30,
    }

    @pytest.mark.parametrize("label,tenor", list(TENORS.items()))
    def test_ois_pv(self, curves, label, tenor):
        disc, _, _ = curves
        pv = ois_swap_pv(disc, tenor, MARKET[f"OIS:{label}"])
        assert abs(pv) < TOLERANCE, (
            f"OIS-{label} PV = {pv:.4e} exceeds {TOLERANCE}")


# ── IRS calibration tests ───────────────────────────────────────────

class TestIrsCalibration:

    def test_fix6m(self, curves):
        disc, e6m, _ = curves
        pv = fixing_pv(disc, e6m, 0.5, MARKET["FIX6M:0D"])
        assert abs(pv) < TOLERANCE, f"FIX-6M PV = {pv:.4e}"

    def test_fra_6mx12m(self, curves):
        disc, e6m, _ = curves
        pv = fra_pv(disc, e6m, 0.5, 1.0, MARKET["FRA6M:6Mx12M"])
        assert abs(pv) < TOLERANCE, f"FRA-6Mx12M PV = {pv:.4e}"

    IRS_TENORS = {"2Y": 2, "3Y": 3, "4Y": 4, "5Y": 5,
                  "7Y": 7, "10Y": 10, "15Y": 15, "20Y": 20, "30Y": 30}

    @pytest.mark.parametrize("label,tenor", list(IRS_TENORS.items()))
    def test_irs_pv(self, curves, label, tenor):
        disc, e6m, _ = curves
        pv = irs_swap_pv(disc, e6m, tenor, MARKET[f"IRS6M:{label}"])
        assert abs(pv) < TOLERANCE, (
            f"IRS6M-{label} PV = {pv:.4e} exceeds {TOLERANCE}")


# ── Basis swap calibration tests ────────────────────────────────────

class TestBsCalibration:

    def test_fix3m(self, curves):
        disc, _, e3m = curves
        pv = fixing_pv(disc, e3m, 0.25, MARKET["FIX3M:0D"])
        assert abs(pv) < TOLERANCE, f"FIX-3M PV = {pv:.4e}"

    def test_fra_3mx6m(self, curves):
        disc, _, e3m = curves
        pv = fra_pv(disc, e3m, 0.25, 0.5, MARKET["FRA3M:3Mx6M"])
        assert abs(pv) < TOLERANCE, f"FRA-3Mx6M PV = {pv:.4e}"

    BS_TENORS = {"1Y": 1, "2Y": 2, "3Y": 3, "4Y": 4, "5Y": 5,
                 "7Y": 7, "10Y": 10, "15Y": 15, "20Y": 20, "30Y": 30}

    @pytest.mark.parametrize("label,tenor", list(BS_TENORS.items()))
    def test_bs_pv(self, curves, label, tenor):
        disc, e6m, e3m = curves
        pv = basis_swap_pv(disc, e3m, e6m, tenor,
                           MARKET[f"BS3M6M:{label}"])
        assert abs(pv) < TOLERANCE, (
            f"BS3M6M-{label} PV = {pv:.4e} exceeds {TOLERANCE}")


# ── Portfolio PV tests ──────────────────────────────────────────────

class TestPortfolioPV:

    @pytest.mark.parametrize("pos", PORTFOLIO, ids=[p["id"] for p in PORTFOLIO])
    def test_portfolio_pv(self, results, curves, pos):
        disc, e6m, e3m = curves
        expected_pv = pos["notional"] * price_swap(
            disc, e6m, e3m, pos["type"], pos["tenor"], pos["rate"])
        actual_pv = results["portfolio"][pos["id"]]["pv"]
        assert abs(actual_pv - expected_pv) < PV_TOLERANCE, (
            f"{pos['id']} PV: expected {expected_pv:.4f}, "
            f"got {actual_pv:.4f}")


# ── PV01 tests ──────────────────────────────────────────────────────

class TestPV01:

    @pytest.mark.parametrize("pos", PORTFOLIO, ids=[p["id"] for p in PORTFOLIO])
    def test_pv01_ois_curve(self, results, curves, pos):
        disc, e6m, e3m = curves
        expected = compute_pv01(disc, e6m, e3m,
                                pos["type"], pos["tenor"],
                                pos["rate"], pos["notional"])
        actual = results["portfolio"][pos["id"]]["pv01"]["EUR-DSCON-OIS"]
        exp_arr = expected["EUR-DSCON-OIS"]
        for j in range(len(exp_arr)):
            assert abs(actual[j] - exp_arr[j]) < PV01_TOLERANCE, (
                f"{pos['id']} OIS node {j}: "
                f"expected {exp_arr[j]:.4f}, got {actual[j]:.4f}")

    @pytest.mark.parametrize("pos", PORTFOLIO, ids=[p["id"] for p in PORTFOLIO])
    def test_pv01_e6m_curve(self, results, curves, pos):
        disc, e6m, e3m = curves
        expected = compute_pv01(disc, e6m, e3m,
                                pos["type"], pos["tenor"],
                                pos["rate"], pos["notional"])
        actual = results["portfolio"][pos["id"]]["pv01"]["EUR-EURIBOR6M-IRS"]
        exp_arr = expected["EUR-EURIBOR6M-IRS"]
        for j in range(len(exp_arr)):
            assert abs(actual[j] - exp_arr[j]) < PV01_TOLERANCE, (
                f"{pos['id']} E6M node {j}: "
                f"expected {exp_arr[j]:.4f}, got {actual[j]:.4f}")

    @pytest.mark.parametrize("pos", PORTFOLIO, ids=[p["id"] for p in PORTFOLIO])
    def test_pv01_e3m_curve(self, results, curves, pos):
        disc, e6m, e3m = curves
        expected = compute_pv01(disc, e6m, e3m,
                                pos["type"], pos["tenor"],
                                pos["rate"], pos["notional"])
        actual = results["portfolio"][pos["id"]]["pv01"]["EUR-EURIBOR3M-BS"]
        exp_arr = expected["EUR-EURIBOR3M-BS"]
        for j in range(len(exp_arr)):
            assert abs(actual[j] - exp_arr[j]) < PV01_TOLERANCE, (
                f"{pos['id']} E3M node {j}: "
                f"expected {exp_arr[j]:.4f}, got {actual[j]:.4f}")


# ── Sanity checks ──────────────────────────────────────────────────

class TestSanity:

    def test_discount_factors_positive(self, curves):
        disc, _, _ = curves
        for t in [0.1, 0.5, 1, 2, 5, 10, 20, 30]:
            df = disc.discount_factor(t)
            assert df > 0, f"DF({t}) = {df} not positive"

    def test_discount_factors_consistent(self, results):
        """Check that reported DFs match exp(-r*t) at node times."""
        for cname in CURVE_NAMES:
            c = results["curves"][cname]
            times = c["times"]
            rates = c["zero_rates"]
            dfs = c["discount_factors"]
            curve = InterpolatedCurve(times, rates)
            for i in range(len(times)):
                expected_df = curve.discount_factor(times[i])
                assert abs(dfs[i] - expected_df) < 1e-10, (
                    f"{cname} DF at t={times[i]}: "
                    f"reported {dfs[i]}, computed {expected_df}")

    def test_forward_rates_reasonable(self, curves):
        for curve, name in zip(curves, ("OIS", "E6M", "E3M")):
            for s in [0.0, 1.0, 5.0, 10.0, 20.0]:
                e = s + 0.5
                if e > 30.0:
                    continue
                fwd = curve.forward_rate(s, e)
                assert -0.02 < fwd < 0.05, (
                    f"{name} fwd({s},{e}) = {fwd:.6f} out of range")

    def test_pv01_zero_for_unrelated_curves(self, results, curves):
        """OIS swaps should have zero PV01 w.r.t. E6M and E3M curves."""
        disc, e6m, e3m = curves
        # SWAP-3 is OIS type
        ois_pv01 = results["portfolio"]["SWAP-3"]["pv01"]
        for cn in ["EUR-EURIBOR6M-IRS", "EUR-EURIBOR3M-BS"]:
            for j, val in enumerate(ois_pv01[cn]):
                assert abs(val) < PV01_TOLERANCE, (
                    f"SWAP-3 (OIS) should have ~0 PV01 for {cn} "
                    f"node {j}, got {val:.4f}")
