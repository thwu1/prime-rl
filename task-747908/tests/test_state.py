
import json
import math
import os
import sys
import pytest

sys.path.insert(0, "/app")

# ---------------------------------------------------------------------------
# Reference implementation of WCV_TAUMOD from PVS specifications
# Used to verify the agent's implementation
# ---------------------------------------------------------------------------

def _sq(x):
    return x * x

def _sqv2(v):
    return v[0] ** 2 + v[1] ** 2

def _dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]

def _ref_horizontal_wcv_taumod_interval(T, s, v, TAUMOD, DTHR):
    """Reference: horizontal_WCV_taumod_interval from PVS"""
    ss = _sqv2(s)
    vv = _sqv2(v)
    sv = _dot2(s, v)
    d2 = _sq(DTHR)
    a = vv
    b = 2.0 * sv + TAUMOD * vv
    c = ss + TAUMOD * sv - d2

    if a < 1e-30:
        return (0.0, T) if ss <= d2 else (T, 0.0)

    if ss <= d2:
        dl = sv ** 2 - vv * (ss - d2)
        if dl < 0:
            return (T, 0.0)
        return (0.0, min(T, (-sv + math.sqrt(dl)) / vv))

    if sv >= 0:
        return (T, 0.0)

    disc = b * b - 4.0 * a * c
    if disc < 0:
        return (T, 0.0)

    dl = sv ** 2 - vv * (ss - d2)
    if dl < 0:
        return (T, 0.0)

    r = (-b - math.sqrt(disc)) / (2.0 * a)
    if r > T:
        return (T, 0.0)

    return (max(0.0, r), min(T, (-sv + math.sqrt(dl)) / vv))


def _ref_theta_H(H, sz, vz, eps):
    """Compute altitude crossing time.
    eps=-1: entry (earlier crossing into band)
    eps=+1: exit (later crossing out of band)
    """
    if eps * vz > 0:
        return (H - sz) / vz
    else:
        return (-H - sz) / vz


def _ref_vertical_wcv_interval(B, T, sz, vz, TCOA, ZTHR):
    """Reference: vertical_WCV_interval from PVS"""
    if abs(vz) < 1e-15:
        return (B, T) if abs(sz) <= ZTHR else (T, B)

    act_H = max(ZTHR, abs(vz) * TCOA)
    ce = _ref_theta_H(act_H, sz, vz, -1)
    cx = _ref_theta_H(ZTHR, sz, vz, 1)

    if T < ce or cx < B:
        return (T, B)
    return (max(B, ce), min(T, cx))


def _ref_horizontal_wcv_check(s, v, TAUMOD, DTHR):
    """Instantaneous horizontal WCV check"""
    ss = _sqv2(s)
    d2 = _sq(DTHR)
    if ss <= d2:
        return True
    sv = _dot2(s, v)
    if sv >= 0:
        return False
    vv = _sqv2(v)
    if vv < 1e-30:
        return False
    tc = -sv / vv
    sc = (s[0] + tc * v[0], s[1] + tc * v[1])
    if _sqv2(sc) > d2:
        return False
    tm = (d2 - ss) / sv
    return 0 <= tm <= TAUMOD


def _ref_wcv_taumod_interval(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR):
    """Reference: WCV_taumod_interval from PVS"""
    s2 = (s3[0], s3[1])
    v2 = (v3[0], v3[1])
    sz = s3[2]
    vz = v3[2]

    ve, vx = _ref_vertical_wcv_interval(B, T, sz, vz, TCOA, ZTHR)
    if ve > vx:
        return (T, B)

    if abs(ve - vx) < 1e-15:
        ss = (s2[0] + ve * v2[0], s2[1] + ve * v2[1])
        if _ref_horizontal_wcv_check(ss, v2, TAUMOD, DTHR):
            return (ve, ve)
        return (T, B)

    sh = (s2[0] + ve * v2[0], s2[1] + ve * v2[1])
    he, hx = _ref_horizontal_wcv_taumod_interval(vx - ve, sh, v2, TAUMOD, DTHR)
    if he > hx:
        return (T, B)
    return (he + ve, hx + ve)


def _ref_wcv_taumod_detection(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR):
    """Reference: WCV_taumod_detection from PVS"""
    if abs(B - T) < 1e-15:
        return False
    if B > T:
        return False
    e, x = _ref_wcv_taumod_interval(B, T, s3, v3, TAUMOD, TCOA, DTHR, ZTHR)
    return e <= x


# ---------------------------------------------------------------------------
# Encounter / config processing helpers
# ---------------------------------------------------------------------------

def _load_encounters():
    encs = []
    enc_dir = "/app/data/encounters"
    for fn in sorted(os.listdir(enc_dir)):
        if fn.endswith(".json"):
            with open(os.path.join(enc_dir, fn)) as f:
                encs.append(json.load(f))
    return encs


def _load_configs():
    cfgs = []
    cfg_dir = "/app/data/configs"
    for fn in sorted(os.listdir(cfg_dir)):
        if fn.endswith(".json"):
            with open(os.path.join(cfg_dir, fn)) as f:
                cfgs.append(json.load(f))
    return cfgs


def _aircraft_velocity(trk_deg, gs_knot, vs_fpm):
    trk_rad = math.radians(trk_deg)
    gs_nmi_s = gs_knot / 3600.0
    vx = gs_nmi_s * math.sin(trk_rad)
    vy = gs_nmi_s * math.cos(trk_rad)
    vz = vs_fpm / 60.0
    return (vx, vy, vz)


def _compute_relative_state(own, intr):
    sx = own["sx_nmi"] - intr["sx_nmi"]
    sy = own["sy_nmi"] - intr["sy_nmi"]
    sz = own["sz_ft"] - intr["sz_ft"]
    vo = _aircraft_velocity(own["trk_deg"], own["gs_knot"], own["vs_fpm"])
    vi = _aircraft_velocity(intr["trk_deg"], intr["gs_knot"], intr["vs_fpm"])
    vx = vo[0] - vi[0]
    vy = vo[1] - vi[1]
    vz = vo[2] - vi[2]
    return (sx, sy, sz), (vx, vy, vz)


def _compute_expected_results():
    """Compute reference results for all encounter/config pairs."""
    results = []
    for enc in _load_encounters():
        for cfg in _load_configs():
            for intr in enc["intruders"]:
                s3, v3 = _compute_relative_state(enc["ownship"], intr)
                T = cfg["lookahead_s"]
                conflict = _ref_wcv_taumod_detection(
                    0, T, s3, v3,
                    cfg["TAUMOD_s"], cfg["TCOA_s"],
                    cfg["DTHR_nmi"], cfg["ZTHR_ft"]
                )
                entry, exit_ = None, None
                if conflict:
                    e, x = _ref_wcv_taumod_interval(
                        0, T, s3, v3,
                        cfg["TAUMOD_s"], cfg["TCOA_s"],
                        cfg["DTHR_nmi"], cfg["ZTHR_ft"]
                    )
                    entry, exit_ = e, x
                results.append({
                    "encounter": enc["name"],
                    "intruder": intr["id"],
                    "config": cfg["name"],
                    "conflict": conflict,
                    "entry_time_s": entry,
                    "exit_time_s": exit_,
                })
    return results


# ---------------------------------------------------------------------------
# Unit tests for the agent's module
# ---------------------------------------------------------------------------

class TestHorizontalWCVTaumodInterval:
    """Test horizontal_wcv_taumod_interval against known analytic results."""

    def _import_module(self):
        import wcv_taumod
        return wcv_taumod

    def test_within_dthr_zero_velocity(self):
        """Aircraft within DTHR, zero relative velocity -> whole interval."""
        m = self._import_module()
        e, x = m.horizontal_wcv_taumod_interval(60.0, (0.3, 0.0), (0.0, 0.0), 35.0, 0.66)
        assert e == pytest.approx(0.0, abs=1e-9)
        assert x == pytest.approx(60.0, abs=1e-9)

    def test_within_dthr_nonzero_velocity(self):
        """Aircraft within DTHR, moving -> entry=0, exit at distance crossing."""
        m = self._import_module()
        e, x = m.horizontal_wcv_taumod_interval(60.0, (0.5, 0.0), (0.01, 0.0), 35.0, 0.66)
        assert e == pytest.approx(0.0, abs=1e-6)
        # Exit when distance reaches DTHR
        ref_e, ref_x = _ref_horizontal_wcv_taumod_interval(60.0, (0.5, 0.0), (0.01, 0.0), 35.0, 0.66)
        assert x == pytest.approx(ref_x, abs=0.01)

    def test_diverging_outside_dthr(self):
        """Aircraft outside DTHR, diverging -> empty interval."""
        m = self._import_module()
        e, x = m.horizontal_wcv_taumod_interval(60.0, (5.0, 0.0), (0.1, 0.0), 35.0, 0.66)
        assert e > x, "Expected empty interval for diverging aircraft"

    def test_head_on_conflict(self):
        """Head-on approach should produce conflict interval."""
        m = self._import_module()
        s = (0.0, -10.0)
        v = (0.0, 500.0 / 3600.0)
        e, x = m.horizontal_wcv_taumod_interval(180.0, s, v, 35.0, 0.66)
        ref_e, ref_x = _ref_horizontal_wcv_taumod_interval(180.0, s, v, 35.0, 0.66)
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)
        assert e < x

    def test_no_cpa_within_dthr(self):
        """Crossing encounter where CPA > DTHR -> empty interval."""
        m = self._import_module()
        # CPA distance ~ 1.54 nmi > 0.66
        s = (-6.0, -3.0)
        v = (300.0 / 3600.0, 250.0 / 3600.0)
        e, x = m.horizontal_wcv_taumod_interval(180.0, s, v, 35.0, 0.66)
        assert e > x, "Expected empty interval when CPA > DTHR"

    def test_large_dthr_crossing(self):
        """Same crossing with large DTHR should detect conflict."""
        m = self._import_module()
        s = (-6.0, -3.0)
        v = (300.0 / 3600.0, 250.0 / 3600.0)
        e, x = m.horizontal_wcv_taumod_interval(300.0, s, v, 180.0, 5.0)
        ref_e, ref_x = _ref_horizontal_wcv_taumod_interval(300.0, s, v, 180.0, 5.0)
        assert e <= x
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)


class TestVerticalWCVInterval:
    """Test vertical_wcv_interval."""

    def _import_module(self):
        import wcv_taumod
        return wcv_taumod

    def test_coaltitude_zero_vz(self):
        """Co-altitude, zero vertical speed -> whole interval."""
        m = self._import_module()
        e, x = m.vertical_wcv_interval(0.0, 180.0, 0.0, 0.0, 0.0, 450.0)
        assert e == pytest.approx(0.0, abs=1e-9)
        assert x == pytest.approx(180.0, abs=1e-9)

    def test_within_zthr_zero_vz(self):
        """Within ZTHR, zero vertical speed -> whole interval."""
        m = self._import_module()
        e, x = m.vertical_wcv_interval(0.0, 180.0, 200.0, 0.0, 0.0, 450.0)
        assert e == pytest.approx(0.0, abs=1e-9)
        assert x == pytest.approx(180.0, abs=1e-9)

    def test_outside_zthr_zero_vz(self):
        """Outside ZTHR, zero vertical speed -> empty interval."""
        m = self._import_module()
        e, x = m.vertical_wcv_interval(0.0, 180.0, 800.0, 0.0, 0.0, 450.0)
        assert e > x, "Expected empty interval outside ZTHR with zero vz"

    def test_descending_into_zthr(self):
        """Aircraft descending into ZTHR band."""
        m = self._import_module()
        # sz=-800 (below by 800ft), vz=+10 (closing), ZTHR=450, TCOA=0
        e, x = m.vertical_wcv_interval(0.0, 180.0, -800.0, 10.0, 0.0, 450.0)
        ref_e, ref_x = _ref_vertical_wcv_interval(0.0, 180.0, -800.0, 10.0, 0.0, 450.0)
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)
        assert e < x

    def test_above_descending_into_zthr(self):
        """Aircraft above, descending into ZTHR band (vz < 0)."""
        m = self._import_module()
        # sz=+800 (above by 800ft), vz=-10 (closing)
        e, x = m.vertical_wcv_interval(0.0, 180.0, 800.0, -10.0, 0.0, 450.0)
        ref_e, ref_x = _ref_vertical_wcv_interval(0.0, 180.0, 800.0, -10.0, 0.0, 450.0)
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)
        assert e < x

    def test_tcoa_extends_interval(self):
        """TCOA > 0 should extend the vertical interval earlier."""
        m = self._import_module()
        e0, x0 = m.vertical_wcv_interval(0.0, 180.0, -800.0, 10.0, 0.0, 450.0)
        e20, x20 = m.vertical_wcv_interval(0.0, 180.0, -800.0, 10.0, 20.0, 450.0)
        assert e20 <= e0, "TCOA should make entry earlier or equal"


class TestWCVTaumodInterval:
    """Test wcv_taumod_interval (3D composition)."""

    def _import_module(self):
        import wcv_taumod
        return wcv_taumod

    def test_head_on_coalt(self):
        """Head-on at co-altitude with standard DWC."""
        m = self._import_module()
        s3 = (0.0, -10.0, 0.0)
        v3 = (0.0, 500.0 / 3600.0, 0.0)
        e, x = m.wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        ref_e, ref_x = _ref_wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)
        assert e < x

    def test_descending_intruder(self):
        """Vertical entry determines overall entry time."""
        m = self._import_module()
        s3 = (0.0, -8.0, -800.0)
        v3 = (0.0, 450.0 / 3600.0, 10.0)
        e, x = m.wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        ref_e, ref_x = _ref_wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        assert e == pytest.approx(ref_e, abs=0.5)
        assert x == pytest.approx(ref_x, abs=0.5)

    def test_diverging_no_conflict(self):
        """Diverging aircraft should have no conflict."""
        m = self._import_module()
        s3 = (0.0, 2.0, 0.0)
        v3 = (0.0, 500.0 / 3600.0, 0.0)
        e, x = m.wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        assert e > x, "Expected empty interval for diverging aircraft"

    def test_detection_matches_interval(self):
        """Detection bool should match interval non-emptiness."""
        m = self._import_module()
        s3 = (0.0, -10.0, 0.0)
        v3 = (0.0, 500.0 / 3600.0, 0.0)
        det = m.wcv_taumod_detection(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        e, x = m.wcv_taumod_interval(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0)
        assert det == (e <= x)


class TestWCVTaumodDetection:
    """Test wcv_taumod_detection bool function."""

    def _import_module(self):
        import wcv_taumod
        return wcv_taumod

    def test_conflict_detected(self):
        m = self._import_module()
        s3 = (0.0, -10.0, 0.0)
        v3 = (0.0, 500.0 / 3600.0, 0.0)
        assert m.wcv_taumod_detection(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0) is True

    def test_no_conflict_diverging(self):
        m = self._import_module()
        s3 = (0.0, 5.0, 0.0)
        v3 = (0.0, 0.1, 0.0)
        assert m.wcv_taumod_detection(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0) is False

    def test_no_conflict_vertical_separation(self):
        m = self._import_module()
        s3 = (0.0, -5.0, 2000.0)
        v3 = (0.0, 0.1, 0.0)
        assert m.wcv_taumod_detection(0.0, 180.0, s3, v3, 35.0, 0.0, 0.66, 450.0) is False


# ---------------------------------------------------------------------------
# Integration test: verify results.json
# ---------------------------------------------------------------------------

class TestResultsJSON:
    """Verify the agent's results.json against reference implementation."""

    def test_results_file_exists(self):
        assert os.path.isfile("/app/output/results.json"), \
            "results.json not found at /app/output/results.json"

    def test_results_structure(self):
        with open("/app/output/results.json") as f:
            data = json.load(f)
        assert "results" in data, "Missing 'results' key"
        assert isinstance(data["results"], list), "'results' must be a list"
        assert len(data["results"]) >= 12, \
            f"Expected at least 12 results (4 encounters x 3 configs), got {len(data['results'])}"
        for r in data["results"]:
            assert "encounter" in r
            assert "config" in r
            assert "conflict" in r
            assert isinstance(r["conflict"], bool)

    def test_results_correctness(self):
        with open("/app/output/results.json") as f:
            agent_data = json.load(f)

        expected = _compute_expected_results()

        # Build lookup from agent results
        agent_lookup = {}
        for r in agent_data["results"]:
            key = (r["encounter"], r.get("intruder", ""), r["config"])
            agent_lookup[key] = r

        for exp in expected:
            key = (exp["encounter"], exp["intruder"], exp["config"])
            assert key in agent_lookup, \
                f"Missing result for encounter={exp['encounter']}, intruder={exp['intruder']}, config={exp['config']}"

            agent_r = agent_lookup[key]

            assert agent_r["conflict"] == exp["conflict"], \
                f"Conflict mismatch for {key}: expected {exp['conflict']}, got {agent_r['conflict']}"

            if exp["conflict"]:
                assert agent_r["entry_time_s"] is not None, \
                    f"entry_time_s should not be null for conflict=true: {key}"
                assert agent_r["exit_time_s"] is not None, \
                    f"exit_time_s should not be null for conflict=true: {key}"
                assert agent_r["entry_time_s"] == pytest.approx(exp["entry_time_s"], abs=0.5), \
                    f"entry_time_s mismatch for {key}: expected {exp['entry_time_s']:.3f}, got {agent_r['entry_time_s']}"
                assert agent_r["exit_time_s"] == pytest.approx(exp["exit_time_s"], abs=0.5), \
                    f"exit_time_s mismatch for {key}: expected {exp['exit_time_s']:.3f}, got {agent_r['exit_time_s']}"
            else:
                assert agent_r["entry_time_s"] is None, \
                    f"entry_time_s should be null for conflict=false: {key}"
                assert agent_r["exit_time_s"] is None, \
                    f"exit_time_s should be null for conflict=false: {key}"

    def test_head_on_progressively_wider(self):
        """Wider thresholds should detect earlier and exit later for head-on."""
        with open("/app/output/results.json") as f:
            data = json.load(f)

        ho_results = {}
        for r in data["results"]:
            if r["encounter"] == "head_on_coalt" and r["conflict"]:
                ho_results[r["config"]] = r

        # All configs should detect conflict for head-on
        assert "standard_dwc" in ho_results
        assert "buffered_dwc" in ho_results
        assert "wide_surveillance" in ho_results

        # Wider thresholds -> earlier entry
        assert ho_results["wide_surveillance"]["entry_time_s"] <= \
               ho_results["standard_dwc"]["entry_time_s"] + 0.5

    def test_diverging_only_wide(self):
        """Diverging encounter: only wide_surveillance should detect conflict."""
        with open("/app/output/results.json") as f:
            data = json.load(f)

        div_results = {}
        for r in data["results"]:
            if r["encounter"] == "diverging":
                div_results[r["config"]] = r

        assert not div_results["standard_dwc"]["conflict"]
        assert not div_results["buffered_dwc"]["conflict"]
        assert div_results["wide_surveillance"]["conflict"]
