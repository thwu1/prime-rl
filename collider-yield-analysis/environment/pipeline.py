#!/usr/bin/env python3
"""
Event selection pipeline for the VLQ T->tH search in semi-leptonic final states.
Implements baseline + SR-A selection from the analysis specification.
Reads events from /app/data/events.h5 and writes nominal yields to
/app/results/results.yaml.

NOTE: This pipeline implements the nominal selection only. Systematic
variations and statistical interpretation are not yet implemented.
"""
import math
import numpy as np
import h5py
import yaml


def delta_phi(phi1, phi2):
    """Azimuthal angle difference wrapped to [-pi, pi]."""
    return (phi1 - phi2 + math.pi) % (2.0 * math.pi) - math.pi


def delta_r(eta1, phi1, eta2, phi2):
    """Angular distance in eta-phi plane."""
    deta = eta1 - eta2
    dphi = delta_phi(phi1, phi2)
    return math.sqrt(deta * deta + dphi * dphi)


def compute_aplanarity(jet_pts, jet_etas, jet_phis):
    """Compute event aplanarity from the normalized momentum tensor.

    S_ij = sum_k(p_ki * p_kj) / sum_k(|p_k|^2)
    Aplanarity = 3/2 * eigenvalue of S
    """
    n = len(jet_pts)
    px = np.array([jet_pts[k] * math.cos(jet_phis[k]) for k in range(n)])
    py = np.array([jet_pts[k] * math.sin(jet_phis[k]) for k in range(n)])
    pz = np.array([jet_pts[k] * math.sinh(jet_etas[k]) for k in range(n)])
    p = np.stack([px, py, pz], axis=1)
    denom = float(np.sum(p * p))
    if denom == 0.0:
        return 0.0
    S = p.T @ p / denom
    eigenvalues = np.linalg.eigvalsh(S)
    return 1.5 * float(eigenvalues[-1])


def invariant_mass_massless(pt1, eta1, phi1, pt2, eta2, phi2):
    """Invariant mass of two massless particles from cylindrical coords."""
    deta = eta1 - eta2
    dphi = delta_phi(phi1, phi2)
    m2 = 2.0 * pt1 * pt2 * (math.cosh(deta) - math.cos(dphi))
    return math.sqrt(max(m2, 0.0))


def main():
    # Load data
    with h5py.File("/app/data/events.h5", "r") as f:
        ev = f["events"]
        jet_pt = ev["jet_pt"][:]
        jet_eta = ev["jet_eta"][:]
        jet_phi = ev["jet_phi"][:]
        jet_btag = ev["jet_btag_disc"][:]
        n_jets_arr = ev["n_jets"][:]
        lep_pt = ev["lepton_pt"][:]
        lep_eta = ev["lepton_eta"][:]
        lep_phi = ev["lepton_phi"][:]
        lep_flavor = ev["lepton_flavor"][:]
        lep_iso = ev["lepton_mini_iso"][:]
        n_leps_arr = ev["n_leptons"][:]
        met_arr = ev["met"][:]
        met_phi_arr = ev["met_phi"][:]
        weights = ev["event_weight"][:]
        lumi = float(f.attrs["luminosity_ifb"])
        xsec = float(f.attrs["cross_section_pb"])

    N = len(met_arr)
    bin_edges = [250.0, 350.0, 500.0, 700.0, float("inf")]
    n_bins = len(bin_edges) - 1
    yields = np.zeros(n_bins)

    for i in range(N):
        nj = int(n_jets_arr[i])
        nl = int(n_leps_arr[i])
        w = float(weights[i])

        # --- Tight lepton selection ---
        tight = []
        for k in range(nl):
            pt_l = float(lep_pt[i, k])
            if pt_l <= 25.0:
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

        # B1: exactly one tight lepton
        if len(tight) != 1:
            continue
        ti = tight[0]

        # B2: additional loose lepton veto
        n_extra = 0
        for k in range(nl):
            if k == ti:
                continue
            if (float(lep_pt[i, k]) > 10.0
                    and abs(float(lep_eta[i, k])) < 2.5
                    and float(lep_iso[i, k]) < 0.4):
                n_extra += 1
        if n_extra > 0:
            continue

        tl_pt = float(lep_pt[i, ti])
        tl_eta = float(lep_eta[i, ti])
        tl_phi = float(lep_phi[i, ti])

        # --- Jet selection with overlap removal ---
        # Remove jets overlapping with any lepton in the event
        sel_jets = []
        for k in range(nj):
            pt_j = float(jet_pt[i, k])
            if pt_j <= 30.0:
                continue
            if abs(float(jet_eta[i, k])) >= 2.4:
                continue
            overlaps = False
            for l_idx in range(nl):
                if delta_r(float(jet_eta[i, k]), float(jet_phi[i, k]),
                           float(lep_eta[i, l_idx]),
                           float(lep_phi[i, l_idx])) < 0.4:
                    overlaps = True
                    break
            if overlaps:
                continue
            sel_jets.append(k)

        # B3: >= 4 jets
        if len(sel_jets) < 4:
            continue

        # B4: >= 1 b-jet
        bjets = [k for k in sel_jets if float(jet_btag[i, k]) > 0.8838]
        if len(bjets) < 1:
            continue

        # B5: MET > 250
        mval = float(met_arr[i])
        if mval <= 250.0:
            continue

        # B6: delta-phi(leading jets, MET)
        mp = float(met_phi_arr[i])
        if (abs(delta_phi(float(jet_phi[i, sel_jets[0]]), mp)) <= 0.5
                or abs(delta_phi(float(jet_phi[i, sel_jets[1]]), mp)) <= 0.5):
            continue

        # --- Signal region SR-A ---

        # S1: MT > 150
        dp = delta_phi(tl_phi, mp)
        mt = math.sqrt(2.0 * tl_pt * mval * (1.0 - math.cos(dp)))
        if mt <= 150.0:
            continue

        # S2: Aplanarity > 0.04
        j_pts = [float(jet_pt[i, k]) for k in sel_jets]
        j_etas = [float(jet_eta[i, k]) for k in sel_jets]
        j_phis = [float(jet_phi[i, k]) for k in sel_jets]
        aplan = compute_aplanarity(j_pts, j_etas, j_phis)
        if aplan <= 0.04:
            continue

        # S3: >= 5 jets
        if len(sel_jets) < 5:
            continue

        # S4: M_lb <= 175
        mlb_min = float("inf")
        for bk in bjets:
            mlb = invariant_mass_massless(
                tl_pt, tl_eta, tl_phi,
                float(jet_pt[i, bk]), float(jet_eta[i, bk]),
                float(jet_phi[i, bk])
            )
            mlb_min = min(mlb_min, mlb)
        if mlb_min > 175.0:
            continue

        # Event passed all cuts
        for b in range(n_bins):
            if bin_edges[b] <= mval < bin_edges[b + 1]:
                yields[b] += w
                break

    # Normalize yields: L * sigma_fb / N_events
    yields *= lumi * xsec * 1000.0 / N

    # Write nominal yields
    with open("/app/results/results.yaml") as fh:
        doc = yaml.safe_load(fh)

    for idx, entry in enumerate(doc["nominal_yields"]):
        entry["value"] = float(yields[idx])

    with open("/app/results/results.yaml", "w") as fh:
        yaml.dump(doc, fh, default_flow_style=False, sort_keys=False)

    print(f"Nominal yields: {yields}")
    print(f"Total: {yields.sum():.4f}")


if __name__ == "__main__":
    main()
