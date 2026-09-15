#!/usr/bin/env python3
"""
Stage 2: Event selection, systematic variations, and significance.
Reads extracted events from NPZ, queries calibration database for
analysis parameters, applies event selection, and writes results.

NOTE: This pipeline implements selection, systematics, and significance.
"""
import math
import json
import os
import sqlite3
import numpy as np
import yaml

NPZ_FILE = "/app/intermediate/events.npz"
CALIB_DB = "/app/calibration/calib.db"
BG_FILE = "/app/data/background_yields.json"
OUTPUT = "/app/results/results.yaml"
BIN_EDGES = [250.0, 350.0, 500.0, 700.0, float("inf")]


def get_calibration():
    """Read analysis parameters from the calibration database."""
    conn = sqlite3.connect(CALIB_DB)
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
    return {"btag_wp": btag_wp, "jes_delta": jes_delta, "btag_delta": btag_delta}


def delta_phi(phi1, phi2):
    """Azimuthal angle difference wrapped to [-pi, pi]."""
    return (phi1 - phi2 + math.pi) % (2.0 * math.pi) - math.pi


def delta_r(eta1, phi1, eta2, phi2):
    """Angular distance in eta-phi plane."""
    deta = eta1 - eta2
    dphi = delta_phi(phi1, phi2)
    return math.sqrt(deta * deta + dphi * dphi)


def compute_aplanarity(pts, etas, phis):
    """Compute event aplanarity from the normalized momentum tensor.

    S_ij = sum_k(p_ki * p_kj) / sum_k(|p_k|^2)
    Aplanarity = 3/2 * eigenvalue of S
    """
    n = len(pts)
    px = np.array([pts[k] * math.cos(phis[k]) for k in range(n)])
    py = np.array([pts[k] * math.sin(phis[k]) for k in range(n)])
    pz = np.array([pts[k] * math.sinh(etas[k]) for k in range(n)])
    p = np.stack([px, py, pz], axis=1)
    denom = float(np.sum(p * p))
    if denom == 0.0:
        return 0.0
    S = p.T @ p / denom
    eigenvalues = np.linalg.eigvalsh(S)
    return 1.5 * float(eigenvalues[-1])


def run_selection(data, jes_scale=1.0, btag_threshold=0.8838):
    """Run full event selection. Returns normalized yields per MET bin."""
    jpt = data["jet_pt"]
    jeta = data["jet_eta"]
    jphi = data["jet_phi"]
    jbtag = data["jet_btag"]
    nj_arr = data["n_jets"]
    lpt = data["lepton_pt"]
    leta = data["lepton_eta"]
    lphi = data["lepton_phi"]
    lflav = data["lepton_flavor"]
    liso = data["lepton_iso"]
    nl_arr = data["n_leptons"]
    met_arr = data["met"]
    metphi_arr = data["met_phi"]
    wt_arr = data["weights"]

    N = len(met_arr)
    n_bins = len(BIN_EDGES) - 1
    yields = np.zeros(n_bins)

    for i in range(N):
        nj = int(nj_arr[i])
        nl = int(nl_arr[i])
        w = float(wt_arr[i])

        # ---- tight lepton selection ----
        tight = []
        for k in range(nl):
            pt_l = float(lpt[i, k])
            if pt_l <= 25.0:
                continue
            if float(liso[i, k]) >= 0.1:
                continue
            fl = int(lflav[i, k])
            ae = abs(float(leta[i, k]))
            if fl == 0 and ae >= 2.1:
                continue
            if fl == 1 and ae >= 2.4:
                continue
            tight.append(k)

        if len(tight) != 1:
            continue
        ti = tight[0]

        # ---- additional loose lepton veto ----
        n_extra = 0
        for k in range(nl):
            if k == ti:
                continue
            if (float(lpt[i, k]) > 10.0
                    and abs(float(leta[i, k])) < 2.5
                    and float(liso[i, k]) < 0.4):
                n_extra += 1
        if n_extra > 0:
            continue

        tl_pt = float(lpt[i, ti])
        tl_eta = float(leta[i, ti])
        tl_phi = float(lphi[i, ti])

        # ---- jet selection + overlap removal ----
        # Remove jets overlapping with any lepton in the event
        sel_jets = []
        for k in range(nj):
            pt_j = float(jpt[i, k]) * jes_scale
            if pt_j <= 30.0:
                continue
            if abs(float(jeta[i, k])) >= 2.4:
                continue
            overlaps = False
            for l_idx in range(nl):
                if delta_r(float(jeta[i, k]), float(jphi[i, k]),
                           float(leta[i, l_idx]),
                           float(lphi[i, l_idx])) < 0.4:
                    overlaps = True
                    break
            if overlaps:
                continue
            sel_jets.append(k)

        if len(sel_jets) < 4:
            continue

        # ---- b-jets ----
        bjets = [k for k in sel_jets
                 if float(jbtag[i, k]) > btag_threshold]
        if len(bjets) < 1:
            continue

        # ---- MET ----
        mval = float(met_arr[i])
        if mval <= 250.0:
            continue

        # ---- delta-phi(leading jets, MET) ----
        mp = float(metphi_arr[i])
        if (abs(delta_phi(float(jphi[i, sel_jets[0]]), mp)) <= 0.5
                or abs(delta_phi(float(jphi[i, sel_jets[1]]), mp)) <= 0.5):
            continue

        # ---- MT ----
        dp = delta_phi(tl_phi, mp)
        mt = math.sqrt(2.0 * tl_pt * mval * (1.0 - math.cos(dp)))
        if mt <= 150.0:
            continue

        # ---- aplanarity ----
        j_pts = [float(jpt[i, k]) * jes_scale for k in sel_jets]
        j_etas = [float(jeta[i, k]) for k in sel_jets]
        j_phis = [float(jphi[i, k]) for k in sel_jets]
        aplan = compute_aplanarity(j_pts, j_etas, j_phis)
        if aplan <= 0.04:
            continue

        # ---- N_jets >= 5 ----
        if len(sel_jets) < 5:
            continue

        # ---- M_lb ----
        mlb_min = float("inf")
        for bk in bjets:
            de = tl_eta - float(jeta[i, bk])
            dp2 = delta_phi(tl_phi, float(jphi[i, bk]))
            pt_b = float(jpt[i, bk]) * jes_scale
            mlb = math.sqrt(
                2.0 * tl_pt * pt_b * (math.cosh(de) - math.cos(dp2))
            )
            mlb_min = min(mlb_min, mlb)
        if mlb_min > 175.0:
            continue

        # ---- passed: histogram in MET ----
        for b in range(n_bins):
            if BIN_EDGES[b] <= mval < BIN_EDGES[b + 1]:
                yields[b] += w
                break

    # Normalize: L * sigma_fb / N_events
    lumi = float(data["luminosity_ifb"])
    xsec = float(data["cross_section_pb"])
    yields *= lumi * xsec * 1000.0 / N

    return yields


def main():
    # Load extracted events
    npz = np.load(NPZ_FILE)
    data = {
        "jet_pt": npz["jet_pt"],
        "jet_eta": npz["jet_eta"],
        "jet_phi": npz["jet_phi"],
        "jet_btag": npz["jet_btag"],
        "n_jets": npz["n_jets"],
        "lepton_pt": npz["lepton_pt"],
        "lepton_eta": npz["lepton_eta"],
        "lepton_phi": npz["lepton_phi"],
        "lepton_flavor": npz["lepton_flavor"],
        "lepton_iso": npz["lepton_iso"],
        "n_leptons": npz["n_leptons"],
        "met": npz["met"],
        "met_phi": npz["met_phi"],
        "weights": npz["weights"],
        "luminosity_ifb": float(npz["luminosity_ifb"]),
        "cross_section_pb": float(npz["cross_section_pb"]),
    }

    # Get calibration parameters from SQLite
    calib = get_calibration()

    # Nominal yields
    nominal = run_selection(data, btag_threshold=calib["btag_wp"])

    # Systematic variations
    jes_d = calib["jes_delta"]
    btag_d = calib["btag_delta"]

    jes_up = run_selection(
        data, jes_scale=1.0 + jes_d, btag_threshold=calib["btag_wp"]
    )
    jes_down = run_selection(
        data, jes_scale=1.0 - jes_d, btag_threshold=calib["btag_wp"]
    )
    btag_up = run_selection(
        data, btag_threshold=calib["btag_wp"] - btag_d
    )
    btag_down = run_selection(
        data, btag_threshold=calib["btag_wp"] + btag_d
    )

    # Total uncertainty per bin (quadrature sum of symmetrized half-diffs)
    delta_jes = np.abs(jes_up - jes_down) / 2.0
    delta_btag = np.abs(btag_up - btag_down) / 2.0
    total_unc = np.sqrt(delta_jes**2 + delta_btag**2)

    # Asimov significance
    with open(BG_FILE) as fh:
        bg = np.array(json.load(fh)["yields"])

    z_sum = 0.0
    for k in range(len(nominal)):
        s = nominal[k]
        b = bg[k]
        if b > 0 and s > 0:
            z_sum += (s + b) * math.log(1.0 + s / b) - s
    significance = math.sqrt(2.0 * z_sum) if z_sum > 0 else 0.0

    # Write results
    with open(OUTPUT) as fh:
        doc = yaml.safe_load(fh)

    for section, values in [
        ("nominal_yields", nominal),
        ("jes_up_yields", jes_up),
        ("jes_down_yields", jes_down),
        ("btag_up_yields", btag_up),
        ("btag_down_yields", btag_down),
        ("total_uncertainty", total_unc),
    ]:
        for idx, entry in enumerate(doc[section]):
            entry["value"] = float(values[idx])

    doc["significance"] = round(float(significance), 6)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as fh:
        yaml.dump(doc, fh, default_flow_style=False, sort_keys=False)

    print(f"Nominal yields: {nominal}")
    print(f"JES up:   {jes_up}")
    print(f"JES down: {jes_down}")
    print(f"b-tag up:   {btag_up}")
    print(f"b-tag down: {btag_down}")
    print(f"Total uncertainty: {total_unc}")
    print(f"Significance: {significance:.6f}")
    print(f"Results written to {OUTPUT}")


if __name__ == "__main__":
    main()
