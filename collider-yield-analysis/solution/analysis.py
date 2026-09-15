#!/usr/bin/env python3
"""
Solution: VLQ T->tH analysis — reads ROOT file directly with uproot,
queries SQLite calibration database, implements correct event selection,
computes systematic variations, and writes final results.

Fixes applied relative to the buggy pipeline:
  1. ROOT extraction: reads Jet_btagDeepCSV (not Jet_btagCSVv2)
  2. Aplanarity: uses smallest eigenvalue (evals[0]) not largest (evals[-1])
  3. Overlap removal: checks delta-R only against tight lepton, not all leptons
  4. Normalization: divides by sum of weights, not event count N
"""
import math
import json
import os
import sqlite3
import numpy as np
import uproot
import yaml


def dphi(a, b):
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def dr(eta1, phi1, eta2, phi2):
    de = eta1 - eta2
    dp = dphi(phi1, phi2)
    return math.sqrt(de * de + dp * dp)


def aplanarity(pts, etas, phis):
    n = len(pts)
    px = np.array([pts[k] * math.cos(phis[k]) for k in range(n)])
    py = np.array([pts[k] * math.sin(phis[k]) for k in range(n)])
    pz = np.array([pts[k] * math.sinh(etas[k]) for k in range(n)])
    p = np.stack([px, py, pz], axis=1)
    denom = float(np.sum(p * p))
    if denom == 0.0:
        return 0.0
    S = p.T @ p / denom
    evals = np.linalg.eigvalsh(S)
    return 1.5 * float(evals[0])  # smallest eigenvalue


def load_data():
    """Read event data directly from ROOT file with correct branches."""
    f = uproot.open("/app/data/signal.root")
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


def load_calibration():
    """Read calibration parameters from SQLite database."""
    conn = sqlite3.connect("/app/calibration/calib.db")
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


def run_selection(data, jes_scale=1.0, btag_threshold=0.8838):
    """Run the full event selection. Returns normalized yields per MET bin."""
    jet_pt_raw = data["jet_pt"]
    jet_eta = data["jet_eta"]
    jet_phi = data["jet_phi"]
    jet_btag = data["jet_btag"]
    n_jets_arr = data["n_jets"]
    lep_pt = data["lep_pt"]
    lep_eta = data["lep_eta"]
    lep_phi = data["lep_phi"]
    lep_flavor = data["lep_flavor"]
    lep_iso = data["lep_iso"]
    n_leps_arr = data["n_leps"]
    met_arr = data["met"]
    met_phi_arr = data["met_phi"]
    wt_arr = data["weights"]

    N = len(met_arr)
    total_weight = float(np.sum(wt_arr))
    norm = data["lumi"] * data["xsec"] * 1000.0

    bin_edges = [250.0, 350.0, 500.0, 700.0, float("inf")]
    n_bins = len(bin_edges) - 1
    yields = np.zeros(n_bins)

    for i in range(N):
        nj = int(n_jets_arr[i])
        nl = int(n_leps_arr[i])
        w = float(wt_arr[i])

        # Tight lepton selection
        tight = []
        for k in range(nl):
            pt = float(lep_pt[i, k])
            if pt <= 25.0:
                continue
            if float(lep_iso[i, k]) >= 0.1:
                continue
            fl = int(lep_flavor[i, k])
            ae = abs(float(lep_eta[i, k]))
            if fl == 0 and ae >= 2.1:
                continue
            if fl == 1 and ae >= 2.4:
                continue
            tight.append(k)

        if len(tight) != 1:
            continue
        ti = tight[0]

        # Loose lepton veto
        extra = 0
        for k in range(nl):
            if k == ti:
                continue
            if (float(lep_pt[i, k]) > 10.0
                    and abs(float(lep_eta[i, k])) < 2.5
                    and float(lep_iso[i, k]) < 0.4):
                extra += 1
        if extra > 0:
            continue

        tl_pt = float(lep_pt[i, ti])
        tl_eta = float(lep_eta[i, ti])
        tl_phi = float(lep_phi[i, ti])

        # Jet selection + overlap removal with TIGHT LEPTON ONLY
        sel = []
        for k in range(nj):
            pt_j = float(jet_pt_raw[i, k]) * jes_scale
            if pt_j <= 30.0:
                continue
            if abs(float(jet_eta[i, k])) >= 2.4:
                continue
            if dr(float(jet_eta[i, k]), float(jet_phi[i, k]),
                  tl_eta, tl_phi) < 0.4:
                continue
            sel.append(k)

        if len(sel) < 4:
            continue

        bjets = [k for k in sel if float(jet_btag[i, k]) > btag_threshold]
        if len(bjets) < 1:
            continue

        mval = float(met_arr[i])
        if mval <= 250.0:
            continue

        mp = float(met_phi_arr[i])
        if (abs(dphi(float(jet_phi[i, sel[0]]), mp)) <= 0.5
                or abs(dphi(float(jet_phi[i, sel[1]]), mp)) <= 0.5):
            continue

        dp_lm = dphi(tl_phi, mp)
        mt = math.sqrt(2.0 * tl_pt * mval * (1.0 - math.cos(dp_lm)))
        if mt <= 150.0:
            continue

        j_pts = [float(jet_pt_raw[i, k]) * jes_scale for k in sel]
        j_etas = [float(jet_eta[i, k]) for k in sel]
        j_phis = [float(jet_phi[i, k]) for k in sel]
        aplan = aplanarity(j_pts, j_etas, j_phis)
        if aplan <= 0.04:
            continue

        if len(sel) < 5:
            continue

        mlb_min = float("inf")
        for bk in bjets:
            de = tl_eta - float(jet_eta[i, bk])
            dp2 = dphi(tl_phi, float(jet_phi[i, bk]))
            pt_b = float(jet_pt_raw[i, bk]) * jes_scale
            mlb = math.sqrt(2.0 * tl_pt * pt_b
                            * (math.cosh(de) - math.cos(dp2)))
            mlb_min = min(mlb_min, mlb)
        if mlb_min > 175.0:
            continue

        for b in range(n_bins):
            if bin_edges[b] <= mval < bin_edges[b + 1]:
                yields[b] += w
                break

    # Correct normalization: divide by sum of weights, not N
    yields *= norm / total_weight
    return yields


def main():
    data = load_data()
    btag_wp, jes_delta, btag_delta = load_calibration()

    # Nominal yields
    nominal = run_selection(data, btag_threshold=btag_wp)

    # JES systematic variations
    jes_up = run_selection(data, jes_scale=1.0 + jes_delta,
                           btag_threshold=btag_wp)
    jes_down = run_selection(data, jes_scale=1.0 - jes_delta,
                             btag_threshold=btag_wp)

    # b-tag systematic variations
    btag_up = run_selection(data, btag_threshold=btag_wp - btag_delta)
    btag_down = run_selection(data, btag_threshold=btag_wp + btag_delta)

    # Total uncertainty per bin
    delta_jes = np.abs(jes_up - jes_down) / 2.0
    delta_btag = np.abs(btag_up - btag_down) / 2.0
    total_unc = np.sqrt(delta_jes**2 + delta_btag**2)

    # Asimov significance
    with open("/app/data/background_yields.json") as fh:
        bg_data = json.load(fh)
    bg = np.array(bg_data["yields"])

    z_sum = 0.0
    for k in range(len(nominal)):
        s = nominal[k]
        b = bg[k]
        if b > 0 and s > 0:
            z_sum += (s + b) * math.log(1.0 + s / b) - s
    significance = math.sqrt(2.0 * z_sum) if z_sum > 0 else 0.0

    # Write results
    with open("/app/results/results.yaml") as fh:
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

    os.makedirs(os.path.dirname("/app/results/results.yaml"), exist_ok=True)
    with open("/app/results/results.yaml", "w") as fh:
        yaml.dump(doc, fh, default_flow_style=False, sort_keys=False)

    print(f"Nominal yields: {nominal}")
    print(f"JES up:   {jes_up}")
    print(f"JES down: {jes_down}")
    print(f"b-tag up:   {btag_up}")
    print(f"b-tag down: {btag_down}")
    print(f"Total uncertainty: {total_unc}")
    print(f"Significance: {significance:.6f}")


if __name__ == "__main__":
    main()
