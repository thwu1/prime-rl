"""
Verification tests for the VLQ T->tH analysis.

Independently reads the ROOT file with uproot (correct DeepCSV branch),
queries the SQLite calibration database, computes reference nominal yields,
systematic variations, total uncertainty, and Asimov significance, then
compares against the agent's output.
"""
import os
import math
import json
import sqlite3
import numpy as np
import uproot
import yaml
import pytest

ROOT_PATH = "/app/data/signal.root"
CALIB_PATH = "/app/calibration/calib.db"
OUTPUT_PATH = "/app/results/results.yaml"
BG_PATH = "/app/data/background_yields.json"
BIN_EDGES = [250.0, 350.0, 500.0, 700.0, float("inf")]
N_BINS = len(BIN_EDGES) - 1


# -------------------------------------------------------------------- #
#  Independent reference implementation                                 #
# -------------------------------------------------------------------- #

def _dphi(a, b):
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def _dr(eta1, phi1, eta2, phi2):
    de = eta1 - eta2
    dp = _dphi(phi1, phi2)
    return math.sqrt(de * de + dp * dp)


def _aplanarity(px_arr, py_arr, pz_arr):
    p = np.stack([px_arr, py_arr, pz_arr], axis=1)
    denom = float(np.sum(p * p))
    if denom == 0.0:
        return 0.0
    S = p.T @ p / denom
    evals = np.linalg.eigvalsh(S)
    return 1.5 * float(evals[0])


def _load_data():
    """Read event data directly from ROOT file using correct DeepCSV branch."""
    f = uproot.open(ROOT_PATH)
    tree = f["Events"]
    meta = f["Metadata"]
    data = {
        "jet_pt": tree["Jet_pt"].array(library="np"),
        "jet_eta": tree["Jet_eta"].array(library="np"),
        "jet_phi": tree["Jet_phi"].array(library="np"),
        "jet_btag": tree["Jet_btagDeepCSV"].array(library="np"),
        "n_jets": tree["nJet"].array(library="np"),
        "lep_pt": tree["Lepton_pt"].array(library="np"),
        "lep_eta": tree["Lepton_eta"].array(library="np"),
        "lep_phi": tree["Lepton_phi"].array(library="np"),
        "lep_flavor": tree["Lepton_flavor"].array(library="np"),
        "lep_iso": tree["Lepton_miniIso"].array(library="np"),
        "n_leps": tree["nLepton"].array(library="np"),
        "met": tree["MET_pt"].array(library="np"),
        "met_phi": tree["MET_phi"].array(library="np"),
        "weights": tree["genWeight"].array(library="np"),
        "lumi": float(meta["luminosity_ifb"].array(library="np")[0]),
        "xsec": float(meta["cross_section_pb"].array(library="np")[0]),
    }
    f.close()
    return data


def _load_calibration():
    """Read calibration parameters from SQLite database."""
    conn = sqlite3.connect(CALIB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT threshold FROM working_points "
        "WHERE algorithm='DeepCSV' AND wp_label='medium' AND era='Run2'"
    )
    btag_wp = c.fetchone()[0]
    c.execute(
        "SELECT value FROM systematic_uncertainties "
        "WHERE source='JES' AND parameter='scale_delta'"
    )
    jes_delta = c.fetchone()[0]
    c.execute(
        "SELECT value FROM systematic_uncertainties "
        "WHERE source='btag_sf' AND parameter='threshold_delta'"
    )
    btag_delta = c.fetchone()[0]
    conn.close()
    return btag_wp, jes_delta, btag_delta


def _compute_yields(data, jes_scale=1.0, btag_threshold=0.8838):
    """Full reference selection with configurable JES and b-tag threshold."""
    jpt = data["jet_pt"]
    jeta = data["jet_eta"]
    jphi = data["jet_phi"]
    jbtag = data["jet_btag"]
    nj_arr = data["n_jets"]
    lpt = data["lep_pt"]
    leta = data["lep_eta"]
    lphi = data["lep_phi"]
    lflav = data["lep_flavor"]
    liso = data["lep_iso"]
    nl_arr = data["n_leps"]
    met_arr = data["met"]
    metphi_arr = data["met_phi"]
    wt_arr = data["weights"]

    total_w = float(np.sum(wt_arr))
    norm = data["lumi"] * data["xsec"] * 1000.0
    yields = np.zeros(N_BINS, dtype=np.float64)
    N = len(met_arr)

    for idx in range(N):
        nj = int(nj_arr[idx])
        nl = int(nl_arr[idx])
        w = float(wt_arr[idx])

        # ---- tight lepton selection ----
        tight = []
        for k in range(nl):
            pt_l = float(lpt[idx, k])
            if pt_l <= 25.0:
                continue
            if float(liso[idx, k]) >= 0.1:
                continue
            fl = int(lflav[idx, k])
            ae = abs(float(leta[idx, k]))
            if fl == 0 and ae >= 2.1:
                continue
            if fl == 1 and ae >= 2.4:
                continue
            tight.append(k)

        if len(tight) != 1:
            continue
        ti = tight[0]

        # ---- additional loose lepton veto ----
        extra_loose = 0
        for k in range(nl):
            if k == ti:
                continue
            if (float(lpt[idx, k]) > 10.0
                    and abs(float(leta[idx, k])) < 2.5
                    and float(liso[idx, k]) < 0.4):
                extra_loose += 1
        if extra_loose > 0:
            continue

        tl_eta = float(leta[idx, ti])
        tl_phi = float(lphi[idx, ti])
        tl_pt = float(lpt[idx, ti])

        # ---- jet selection + overlap removal (tight lepton only) ----
        sel_jets = []
        for k in range(nj):
            pt_j = float(jpt[idx, k]) * jes_scale
            if pt_j <= 30.0:
                continue
            if abs(float(jeta[idx, k])) >= 2.4:
                continue
            if _dr(float(jeta[idx, k]), float(jphi[idx, k]),
                   tl_eta, tl_phi) < 0.4:
                continue
            sel_jets.append(k)

        if len(sel_jets) < 4:
            continue

        # ---- b-jets ----
        bjets = [k for k in sel_jets
                 if float(jbtag[idx, k]) > btag_threshold]
        if len(bjets) < 1:
            continue

        # ---- MET ----
        mval = float(met_arr[idx])
        if mval <= 250.0:
            continue

        # ---- delta-phi (leading two jets, MET) ----
        mp = float(metphi_arr[idx])
        if (abs(_dphi(float(jphi[idx, sel_jets[0]]), mp)) <= 0.5
                or abs(_dphi(float(jphi[idx, sel_jets[1]]), mp)) <= 0.5):
            continue

        # ---- MT ----
        dp_lm = _dphi(tl_phi, mp)
        mt = math.sqrt(2.0 * tl_pt * mval * (1.0 - math.cos(dp_lm)))
        if mt <= 150.0:
            continue

        # ---- aplanarity (with JES-scaled pT) ----
        px = np.array([float(jpt[idx, k]) * jes_scale
                       * math.cos(float(jphi[idx, k]))
                       for k in sel_jets])
        py = np.array([float(jpt[idx, k]) * jes_scale
                       * math.sin(float(jphi[idx, k]))
                       for k in sel_jets])
        pz = np.array([float(jpt[idx, k]) * jes_scale
                       * math.sinh(float(jeta[idx, k]))
                       for k in sel_jets])
        aplan = _aplanarity(px, py, pz)
        if aplan <= 0.04:
            continue

        # ---- N_jets >= 5 ----
        if len(sel_jets) < 5:
            continue

        # ---- M_lb (with JES-scaled pT) ----
        mlb_min = float("inf")
        for bk in bjets:
            de = tl_eta - float(jeta[idx, bk])
            dp = _dphi(tl_phi, float(jphi[idx, bk]))
            pt_b = float(jpt[idx, bk]) * jes_scale
            mlb = math.sqrt(
                2.0 * tl_pt * pt_b
                * (math.cosh(de) - math.cos(dp))
            )
            if mlb < mlb_min:
                mlb_min = mlb
        if mlb_min > 175.0:
            continue

        # ---- passed all cuts: histogram in MET ----
        for b in range(N_BINS):
            if BIN_EDGES[b] <= mval < BIN_EDGES[b + 1]:
                yields[b] += w
                break

    yields *= norm / total_w
    return yields


# -------------------------------------------------------------------- #
#  Precompute all reference values                                      #
# -------------------------------------------------------------------- #

_DATA_CACHE = {}


def _get_data():
    if "data" not in _DATA_CACHE:
        _DATA_CACHE["data"] = _load_data()
    return _DATA_CACHE["data"]


_CALIB_CACHE = {}


def _get_calib():
    if "calib" not in _CALIB_CACHE:
        _CALIB_CACHE["calib"] = _load_calibration()
    return _CALIB_CACHE["calib"]


_REF_CACHE = {}


def _get_reference():
    if "ref" not in _REF_CACHE:
        data = _get_data()
        btag_wp, jes_delta, btag_delta = _get_calib()

        nominal = _compute_yields(data, btag_threshold=btag_wp)
        jes_up = _compute_yields(data, jes_scale=1.0 + jes_delta,
                                 btag_threshold=btag_wp)
        jes_down = _compute_yields(data, jes_scale=1.0 - jes_delta,
                                   btag_threshold=btag_wp)
        btag_up = _compute_yields(data, btag_threshold=btag_wp - btag_delta)
        btag_down = _compute_yields(data, btag_threshold=btag_wp + btag_delta)

        delta_jes = np.abs(jes_up - jes_down) / 2.0
        delta_btag = np.abs(btag_up - btag_down) / 2.0
        total_unc = np.sqrt(delta_jes**2 + delta_btag**2)

        with open(BG_PATH) as fh:
            bg = np.array(json.load(fh)["yields"])

        z_sum = 0.0
        for k in range(N_BINS):
            s = nominal[k]
            b = bg[k]
            if b > 0 and s > 0:
                z_sum += (s + b) * math.log(1.0 + s / b) - s
        significance = math.sqrt(2.0 * z_sum) if z_sum > 0 else 0.0

        _REF_CACHE["ref"] = {
            "nominal": nominal,
            "jes_up": jes_up,
            "jes_down": jes_down,
            "btag_up": btag_up,
            "btag_down": btag_down,
            "total_unc": total_unc,
            "significance": significance,
        }
    return _REF_CACHE["ref"]


# -------------------------------------------------------------------- #
#  Load agent output                                                    #
# -------------------------------------------------------------------- #

def _load_agent():
    with open(OUTPUT_PATH) as fh:
        data = yaml.safe_load(fh)
    return data


def _extract_values(data, key):
    return np.array([entry["value"] for entry in data[key]],
                    dtype=np.float64)


def _relative_l2(y_hat, y_ref):
    denom = float(np.sum(y_ref ** 2))
    if denom == 0:
        return float("inf")
    return float(np.sqrt(np.sum((y_hat - y_ref) ** 2) / denom))


# -------------------------------------------------------------------- #
#  Tests                                                                #
# -------------------------------------------------------------------- #

class TestOutputStructure:
    """Verify the output file exists and has correct structure."""

    def test_file_exists(self):
        assert os.path.isfile(OUTPUT_PATH), (
            f"Output file {OUTPUT_PATH} not found"
        )

    def test_valid_yaml(self):
        data = _load_agent()
        assert data is not None, "YAML parsed as None"

    def test_has_all_keys(self):
        data = _load_agent()
        for key in ["nominal_yields", "jes_up_yields", "jes_down_yields",
                     "btag_up_yields", "btag_down_yields",
                     "total_uncertainty", "significance"]:
            assert key in data, f"Missing key '{key}' in output"

    def test_correct_bin_counts(self):
        data = _load_agent()
        for key in ["nominal_yields", "jes_up_yields", "jes_down_yields",
                     "btag_up_yields", "btag_down_yields",
                     "total_uncertainty"]:
            assert len(data[key]) == N_BINS, (
                f"{key}: expected {N_BINS} bins, got {len(data[key])}"
            )

    def test_no_nulls_nominal(self):
        data = _load_agent()
        for i, entry in enumerate(data["nominal_yields"]):
            assert entry["value"] is not None, (
                f"nominal_yields bin {i} is null"
            )

    def test_significance_not_null(self):
        data = _load_agent()
        assert data["significance"] is not None, "significance is null"


class TestNominalYields:
    """Verify corrected nominal yields match reference."""

    def test_non_negative(self):
        data = _load_agent()
        vals = _extract_values(data, "nominal_yields")
        assert np.all(vals >= 0), f"Negative nominal yield(s): {vals}"

    def test_finite(self):
        data = _load_agent()
        vals = _extract_values(data, "nominal_yields")
        assert np.all(np.isfinite(vals)), (
            f"Non-finite nominal yield(s): {vals}"
        )

    def test_not_all_zero(self):
        data = _load_agent()
        vals = _extract_values(data, "nominal_yields")
        assert np.any(vals > 0), "All nominal yields are zero"

    def test_nominal_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "nominal_yields")
        rl2 = _relative_l2(agent, ref["nominal"])
        assert rl2 < 0.01, (
            f"Nominal yields relative L2 = {rl2:.6f} exceeds 0.01. "
            f"Agent: {agent}, Reference: {ref['nominal']}"
        )


class TestJESVariations:
    """Verify JES systematic variation yields."""

    def test_jes_up_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "jes_up_yields")
        rl2 = _relative_l2(agent, ref["jes_up"])
        assert rl2 < 0.02, (
            f"JES up relative L2 = {rl2:.6f} exceeds 0.02. "
            f"Agent: {agent}, Reference: {ref['jes_up']}"
        )

    def test_jes_down_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "jes_down_yields")
        rl2 = _relative_l2(agent, ref["jes_down"])
        assert rl2 < 0.02, (
            f"JES down relative L2 = {rl2:.6f} exceeds 0.02. "
            f"Agent: {agent}, Reference: {ref['jes_down']}"
        )


class TestBtagVariations:
    """Verify b-tag systematic variation yields."""

    def test_btag_up_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "btag_up_yields")
        rl2 = _relative_l2(agent, ref["btag_up"])
        assert rl2 < 0.02, (
            f"b-tag up relative L2 = {rl2:.6f} exceeds 0.02. "
            f"Agent: {agent}, Reference: {ref['btag_up']}"
        )

    def test_btag_down_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "btag_down_yields")
        rl2 = _relative_l2(agent, ref["btag_down"])
        assert rl2 < 0.02, (
            f"b-tag down relative L2 = {rl2:.6f} exceeds 0.02. "
            f"Agent: {agent}, Reference: {ref['btag_down']}"
        )


class TestUncertainty:
    """Verify total systematic uncertainty computation."""

    def test_uncertainty_relative_l2(self):
        ref = _get_reference()
        data = _load_agent()
        agent = _extract_values(data, "total_uncertainty")
        rl2 = _relative_l2(agent, ref["total_unc"])
        assert rl2 < 0.05, (
            f"Total uncertainty relative L2 = {rl2:.6f} exceeds 0.05. "
            f"Agent: {agent}, Reference: {ref['total_unc']}"
        )

    def test_uncertainty_non_negative(self):
        data = _load_agent()
        vals = _extract_values(data, "total_uncertainty")
        assert np.all(vals >= 0), (
            f"Negative uncertainty value(s): {vals}"
        )


class TestSignificance:
    """Verify Asimov significance computation."""

    def test_significance_positive(self):
        data = _load_agent()
        assert data["significance"] > 0, (
            f"Significance should be positive, got {data['significance']}"
        )

    def test_significance_finite(self):
        data = _load_agent()
        assert math.isfinite(data["significance"]), (
            f"Significance is not finite: {data['significance']}"
        )

    def test_significance_accuracy(self):
        ref = _get_reference()
        data = _load_agent()
        agent_sig = float(data["significance"])
        ref_sig = ref["significance"]
        if ref_sig > 0:
            rel_err = abs(agent_sig - ref_sig) / ref_sig
        else:
            rel_err = abs(agent_sig)
        assert rel_err < 0.05, (
            f"Significance relative error = {rel_err:.4f} exceeds 0.05. "
            f"Agent: {agent_sig:.6f}, Reference: {ref_sig:.6f}"
        )
