"""

Tests for WCV detector output verification.
Verifies /app/results.json against independently computed expected values
derived from the PVS formal specifications for NASA DAIDALUS WCV detection.
"""

import json
import math
import os
import pytest


@pytest.fixture
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"Results file not found at {path}"
    with open(path) as f:
        data = json.load(f)
    assert "results" in data, "results.json must have a 'results' key"
    return {r["id"]: r for r in data["results"]}


@pytest.fixture
def config():
    with open("/app/config.json") as f:
        return json.load(f)


# --- Helper to independently compute expected values ---

def _sq(x):
    return x * x


def _sqv(v):
    return sum(x * x for x in v)


def _dot(s, v):
    return sum(a * b for a, b in zip(s, v))


def _delta_D(s, v, D):
    cross_sq = _sqv(s) * _sqv(v) - _sq(_dot(s, v))
    return _sq(D) * _sqv(v) - cross_sq


def _theta_D(s, v, D, eps):
    dd = _delta_D(s, v, D)
    if dd < 0:
        return None
    vv = _sqv(v)
    if vv < 1e-30:
        return None
    return (-_dot(s, v) + eps * math.sqrt(dd)) / vv


def _h_wcv_interval(T, s, v, TAUMOD, DTHR):
    a = _sqv(v)
    sv = _dot(s, v)
    b = 2 * sv + TAUMOD * a
    c = _sqv(s) + TAUMOD * sv - _sq(DTHR)
    ss = _sqv(s)
    if a < 1e-30 and ss <= _sq(DTHR):
        return (0.0, T)
    if ss <= _sq(DTHR):
        td = _theta_D(s, v, DTHR, 1)
        return (0.0, min(T, td)) if td is not None else (0.0, T)
    if sv >= 0 or b * b - 4 * a * c < 0:
        return None
    dd = _delta_D(s, v, DTHR)
    disc = b * b - 4 * a * c
    r_entry = (-b - math.sqrt(disc)) / (2 * a)
    if dd >= 0 and r_entry <= T:
        td_exit = _theta_D(s, v, DTHR, 1)
        if td_exit is None:
            return None
        entry = max(0.0, r_entry)
        exit_t = min(T, td_exit)
        return (entry, exit_t) if entry <= exit_t else None
    return None


def _v_wcv_interval(B, T, sz, vz, ZTHR, TCOA):
    if abs(vz) < 1e-12:
        return (B, T) if abs(sz) <= ZTHR else None
    act_H = max(ZTHR, abs(vz) * TCOA)
    t_a, t_b = (act_H - sz) / vz, (-act_H - sz) / vz
    centry = min(t_a, t_b)
    t_c, t_d = (ZTHR - sz) / vz, (-ZTHR - sz) / vz
    cexit = max(t_c, t_d)
    if T < centry or cexit < B:
        return None
    entry, exit_t = max(B, centry), min(T, cexit)
    return (entry, exit_t) if entry <= exit_t else None


def _horizontal_wcv_check(s, v, DTHR, TTHR_hr):
    if _sqv(s) <= _sq(DTHR):
        return True
    sv = _dot(s, v)
    vv = _sqv(v)
    t_cpa = -sv / vv if sv < 0 and vv > 1e-30 else 0.0
    s_cpa = [s[i] + t_cpa * v[i] for i in range(len(s))]
    if _sqv(s_cpa) <= _sq(DTHR):
        if sv < 0:
            tm = (_sq(DTHR) - _sqv(s)) / sv
            if 0 <= tm <= TTHR_hr:
                return True
    return False


def _wcv_3d_interval(s, v, sz, vz, DTHR, ZTHR, TTHR, TCOA, T_s):
    vert = _v_wcv_interval(0, T_s, sz, vz, ZTHR, TCOA)
    if vert is None:
        return None
    ve, vx = vert
    if abs(vx - ve) < 1e-12:
        t_hr = ve / 3600.0
        ss = [s[i] + t_hr * v[i] for i in range(2)]
        if _horizontal_wcv_check(ss, v, DTHR, TTHR / 3600.0):
            return (ve, ve)
        return None
    T_hr = (vx - ve) / 3600.0
    s_sh = [s[i] + (ve / 3600.0) * v[i] for i in range(2)]
    horiz = _h_wcv_interval(T_hr, s_sh, v, TTHR / 3600.0, DTHR)
    if horiz is None:
        return None
    return (horiz[0] * 3600.0 + ve, horiz[1] * 3600.0 + ve)


def _compute_expected(enc, config):
    s = [enc["sx_nmi"], enc["sy_nmi"]]
    v = [enc["vx_kn"], enc["vy_kn"]]
    sz, vz_fpm = enc["sz_ft"], enc["vz_fpm"]
    vz = vz_fpm / 60.0
    corr = config["corrective"]
    DTHR, ZTHR = corr["DTHR_nmi"], corr["ZTHR_ft"]
    TTHR, TCOA = corr["TTHR_s"], corr["TCOA_s"]
    lookahead = config["lookahead_s"]

    sv = _dot(s, v)
    tau_mod_s = (_sq(DTHR) - _sqv(s)) / sv * 3600.0 if sv < 0 else -1.0

    h_wcv = _horizontal_wcv_check(s, v, DTHR, TTHR / 3600.0)
    v_wcv = abs(sz) <= ZTHR
    if not v_wcv and abs(vz) > 1e-12 and sz * vz < 0:
        if 0 <= -sz / vz <= TCOA:
            v_wcv = True

    wcv_3d = h_wcv and v_wcv

    interval = _wcv_3d_interval(s, v, sz, vz, DTHR, ZTHR, TTHR, TCOA, lookahead)
    entry_s = interval[0] if interval else -1.0
    exit_s = interval[1] if interval else -1.0

    highest = 0
    for alert in config["alerts"]:
        atime = alert["alerting_time_s"]
        iv = _wcv_3d_interval(s, v, sz, vz, alert["DTHR_nmi"],
                              alert["ZTHR_ft"], alert["TTHR_s"], alert["TCOA_s"], atime)
        if iv is not None and iv[0] <= atime:
            highest = max(highest, alert["level"])

    return {
        "tau_mod_s": tau_mod_s, "horizontal_wcv": h_wcv, "vertical_wcv": v_wcv,
        "wcv_3d": wcv_3d, "time_to_wcv_entry_s": entry_s,
        "time_to_wcv_exit_s": exit_s, "alert_level": highest
    }


# --- Expected values (independently verified from PVS math) ---

EXPECTED = {
    "head_on": {
        "tau_mod_s": 58.955, "horizontal_wcv": False, "vertical_wcv": True,
        "wcv_3d": False, "time_to_wcv_entry_s": 23.29, "time_to_wcv_exit_s": 67.92,
        "alert_level": 3
    },
    "crossing": {
        "tau_mod_s": 51.386, "horizontal_wcv": False, "vertical_wcv": True,
        "wcv_3d": False, "time_to_wcv_entry_s": 15.35, "time_to_wcv_exit_s": 65.88,
        "alert_level": 3
    },
    "slow_approach": {
        "tau_mod_s": 91.98, "horizontal_wcv": False, "vertical_wcv": True,
        "wcv_3d": False, "time_to_wcv_entry_s": 32.26, "time_to_wcv_exit_s": 180.0,
        "alert_level": 2
    },
    "vertical_conflict": {
        "tau_mod_s": -13.363, "horizontal_wcv": True, "vertical_wcv": False,
        "wcv_3d": False, "time_to_wcv_entry_s": -1.0, "time_to_wcv_exit_s": -1.0,
        "alert_level": 1
    },
    "separating": {
        "tau_mod_s": -1.0, "horizontal_wcv": False, "vertical_wcv": True,
        "wcv_3d": False, "time_to_wcv_entry_s": -1.0, "time_to_wcv_exit_s": -1.0,
        "alert_level": 0
    },
    "near_miss": {
        "tau_mod_s": 57.386, "horizontal_wcv": False, "vertical_wcv": True,
        "wcv_3d": False, "time_to_wcv_entry_s": -1.0, "time_to_wcv_exit_s": -1.0,
        "alert_level": 0
    },
    "inside_diverging": {
        "tau_mod_s": -1.0, "horizontal_wcv": True, "vertical_wcv": True,
        "wcv_3d": True, "time_to_wcv_entry_s": 0.0, "time_to_wcv_exit_s": 8.655,
        "alert_level": 3
    },
}

TAU_TOL = 0.5       # seconds tolerance for tau_mod
TIME_TOL = 1.0      # seconds tolerance for entry/exit times
TIME_TOL_SMALL = 0.5  # tighter tolerance for small values


def _assert_time_close(actual, expected, label, tol=TIME_TOL):
    if expected < 0:
        assert actual < 0, f"{label}: expected no violation (-1) but got {actual}"
    else:
        assert abs(actual - expected) < tol, \
            f"{label}: expected {expected:.3f} but got {actual:.3f} (tol={tol})"


# --- Test classes ---

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json")

    def test_all_encounters_present(self, results):
        for eid in EXPECTED:
            assert eid in results, f"Missing encounter '{eid}' in results"

    def test_results_have_required_fields(self, results):
        fields = ["id", "tau_mod_s", "horizontal_wcv", "vertical_wcv",
                  "wcv_3d", "time_to_wcv_entry_s", "time_to_wcv_exit_s", "alert_level"]
        for eid, r in results.items():
            for f in fields:
                assert f in r, f"Missing field '{f}' in result for '{eid}'"


class TestHeadOn:
    def test_tau_mod(self, results):
        r = results["head_on"]
        assert abs(r["tau_mod_s"] - EXPECTED["head_on"]["tau_mod_s"]) < TAU_TOL

    def test_horizontal_wcv(self, results):
        assert results["head_on"]["horizontal_wcv"] == False

    def test_vertical_wcv(self, results):
        assert results["head_on"]["vertical_wcv"] == True

    def test_wcv_3d(self, results):
        assert results["head_on"]["wcv_3d"] == False

    def test_wcv_entry(self, results):
        _assert_time_close(results["head_on"]["time_to_wcv_entry_s"], 23.29, "head_on entry")

    def test_wcv_exit(self, results):
        _assert_time_close(results["head_on"]["time_to_wcv_exit_s"], 67.92, "head_on exit")

    def test_alert_level(self, results):
        assert results["head_on"]["alert_level"] == 3


class TestCrossing:
    def test_tau_mod(self, results):
        assert abs(results["crossing"]["tau_mod_s"] - EXPECTED["crossing"]["tau_mod_s"]) < TAU_TOL

    def test_horizontal_wcv(self, results):
        assert results["crossing"]["horizontal_wcv"] == False

    def test_wcv_entry(self, results):
        _assert_time_close(results["crossing"]["time_to_wcv_entry_s"], 15.35, "crossing entry")

    def test_wcv_exit(self, results):
        _assert_time_close(results["crossing"]["time_to_wcv_exit_s"], 65.88, "crossing exit")

    def test_alert_level(self, results):
        assert results["crossing"]["alert_level"] == 3


class TestSlowApproach:
    """Alert 2 only: taumod entry at ~32s is within 55s alerting but outside 25s."""
    def test_tau_mod(self, results):
        assert abs(results["slow_approach"]["tau_mod_s"] - EXPECTED["slow_approach"]["tau_mod_s"]) < TAU_TOL

    def test_horizontal_wcv(self, results):
        assert results["slow_approach"]["horizontal_wcv"] == False

    def test_wcv_entry(self, results):
        _assert_time_close(results["slow_approach"]["time_to_wcv_entry_s"], 32.26, "slow entry")

    def test_wcv_exit(self, results):
        _assert_time_close(results["slow_approach"]["time_to_wcv_exit_s"], 180.0, "slow exit", tol=2.0)

    def test_alert_level(self, results):
        assert results["slow_approach"]["alert_level"] == 2


class TestVerticalConflict:
    """Alert 1 only: ZTHR=700 triggers but ZTHR=450 doesn't overlap horizontally."""
    def test_tau_mod_negative(self, results):
        r = results["vertical_conflict"]
        assert r["tau_mod_s"] < 0, "tau_mod should be negative (inside DTHR)"

    def test_horizontal_wcv_true(self, results):
        assert results["vertical_conflict"]["horizontal_wcv"] == True

    def test_vertical_wcv_false(self, results):
        assert results["vertical_conflict"]["vertical_wcv"] == False

    def test_wcv_3d_false(self, results):
        assert results["vertical_conflict"]["wcv_3d"] == False

    def test_no_corrective_entry(self, results):
        assert results["vertical_conflict"]["time_to_wcv_entry_s"] < 0

    def test_alert_level_1(self, results):
        assert results["vertical_conflict"]["alert_level"] == 1


class TestSeparating:
    """No alert: aircraft diverging."""
    def test_tau_mod_minus_one(self, results):
        assert results["separating"]["tau_mod_s"] == -1.0

    def test_no_horizontal_wcv(self, results):
        assert results["separating"]["horizontal_wcv"] == False

    def test_no_entry(self, results):
        assert results["separating"]["time_to_wcv_entry_s"] < 0

    def test_alert_level_0(self, results):
        assert results["separating"]["alert_level"] == 0


class TestNearMiss:
    """No alert: CPA = 1.0 nmi > DTHR = 0.66 nmi."""
    def test_tau_mod_positive(self, results):
        assert results["near_miss"]["tau_mod_s"] > 0

    def test_no_horizontal_wcv(self, results):
        assert results["near_miss"]["horizontal_wcv"] == False

    def test_no_entry(self, results):
        assert results["near_miss"]["time_to_wcv_entry_s"] < 0

    def test_alert_level_0(self, results):
        assert results["near_miss"]["alert_level"] == 0


class TestInsideDiverging:
    """Alert 3: currently inside DTHR but s.v = 0 (diverging)."""
    def test_tau_mod_minus_one(self, results):
        assert results["inside_diverging"]["tau_mod_s"] == -1.0

    def test_horizontal_wcv_true(self, results):
        assert results["inside_diverging"]["horizontal_wcv"] == True

    def test_wcv_3d_true(self, results):
        assert results["inside_diverging"]["wcv_3d"] == True

    def test_wcv_entry_zero(self, results):
        assert abs(results["inside_diverging"]["time_to_wcv_entry_s"]) < 0.5

    def test_wcv_exit(self, results):
        _assert_time_close(results["inside_diverging"]["time_to_wcv_exit_s"], 8.655,
                          "inside_diverging exit", tol=TIME_TOL_SMALL)

    def test_alert_level_3(self, results):
        assert results["inside_diverging"]["alert_level"] == 3


class TestCrossValidation:
    """Cross-validate agent results against independent reference implementation."""

    def test_all_encounters_match_reference(self, results, config):
        encounters = json.load(open("/app/encounters.json"))
        for enc in encounters["encounters"]:
            eid = enc["id"]
            if eid not in results:
                continue
            expected = _compute_expected(enc, config)
            actual = results[eid]

            # Alert level must match exactly
            assert actual["alert_level"] == expected["alert_level"], \
                f"{eid}: alert_level mismatch: got {actual['alert_level']} expected {expected['alert_level']}"

            # Boolean flags must match
            assert actual["horizontal_wcv"] == expected["horizontal_wcv"], \
                f"{eid}: horizontal_wcv mismatch"
            assert actual["vertical_wcv"] == expected["vertical_wcv"], \
                f"{eid}: vertical_wcv mismatch"
            assert actual["wcv_3d"] == expected["wcv_3d"], \
                f"{eid}: wcv_3d mismatch"

            # Numeric values within tolerance
            if expected["tau_mod_s"] == -1.0:
                assert actual["tau_mod_s"] == -1.0, f"{eid}: tau_mod should be -1"
            else:
                assert abs(actual["tau_mod_s"] - expected["tau_mod_s"]) < TAU_TOL, \
                    f"{eid}: tau_mod_s off by {abs(actual['tau_mod_s'] - expected['tau_mod_s']):.3f}"

            _assert_time_close(actual["time_to_wcv_entry_s"],
                             expected["time_to_wcv_entry_s"], f"{eid} entry")
            _assert_time_close(actual["time_to_wcv_exit_s"],
                             expected["time_to_wcv_exit_s"], f"{eid} exit")
