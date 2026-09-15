#!/usr/bin/env python3
"""Reference solution: implement the single-lepton stop search analysis
and write predicted signal yields to /app/results/histogram.yaml.
"""

import math
import json
import numpy as np
import yaml


def wrap_dphi(dphi):
    """Fold delta-phi into [-pi, pi]."""
    return dphi - 2.0 * math.pi * round(dphi / (2.0 * math.pi))


def run_analysis():
    # ---- Load data ----
    data = np.load('/app/data/events.npz')
    with open('/app/config/signal_info.json') as f:
        info = json.load(f)

    # ---- Normalization ----
    sigma_fb = info['cross_section_pb'] * 1000.0        # pb -> fb
    sigma_nlo = sigma_fb * info['k_factor_nlo_nll']     # apply K-factor
    lumi = info['luminosity_fb']                         # fb^-1
    n_gen = info['n_events_generated']                   # TOTAL generated (before filter)
    norm = sigma_nlo * lumi / n_gen

    # ---- Bin edges ----
    met_edges = [250.0, 350.0, 450.0, 550.0, float('inf')]
    n_bins = len(met_edges) - 1
    bin_counts = [0] * n_bins

    n_events = len(data['event_id'])

    for i in range(n_events):
        nj = int(data['n_jets'][i])
        nl = int(data['n_lep'][i])

        # ---- 1. Signal lepton selection ----
        signal_leps = []
        for l in range(nl):
            pt   = float(data['lep_pt'][i, l])
            eta  = float(data['lep_eta'][i, l])
            pdg  = int(data['lep_pdgid'][i, l])
            iso  = float(data['lep_reliso'][i, l])

            if pt < 20.0:
                continue

            abs_pdg = abs(pdg)
            abs_eta = abs(eta)

            if abs_pdg == 11:                       # electron
                if abs_eta > 2.5:
                    continue
                if 1.4442 < abs_eta < 1.566:        # crack veto
                    continue
                if iso > 0.1:
                    continue
            elif abs_pdg == 13:                      # muon
                if abs_eta > 2.4:
                    continue
                if iso > 0.15:
                    continue
            else:
                continue

            signal_leps.append((pt, eta, float(data['lep_phi'][i, l]), pdg))

        if len(signal_leps) != 1:
            continue

        lep_pt, lep_eta, lep_phi, _ = signal_leps[0]

        # ---- 2. Baseline lepton veto ----
        n_baseline = 0
        for l in range(nl):
            if float(data['lep_pt'][i, l]) >= 10.0 and abs(float(data['lep_eta'][i, l])) <= 2.5:
                n_baseline += 1
        if n_baseline > 1:
            continue

        # ---- 3. Jet selection with overlap removal ----
        sel_jets = []
        for j in range(nj):
            jpt  = float(data['jet_pt'][i, j])
            jeta = float(data['jet_eta'][i, j])
            jphi = float(data['jet_phi'][i, j])
            jbt  = int(data['jet_btag'][i, j])

            if jpt < 30.0 or abs(jeta) > 2.4:
                continue

            # Delta-R overlap removal with signal lepton
            deta = jeta - lep_eta
            dphi = wrap_dphi(jphi - lep_phi)
            dr = math.sqrt(deta * deta + dphi * dphi)
            if dr < 0.4:
                continue

            sel_jets.append((jpt, jeta, jphi, jbt))

        if len(sel_jets) < 4:
            continue

        # Sort by pT descending (should already be, but ensure)
        sel_jets.sort(key=lambda x: -x[0])

        # ---- 4. b-tag requirement ----
        btag_jets = [(pt, eta, phi) for pt, eta, phi, bt in sel_jets if bt]
        if len(btag_jets) < 1:
            continue

        # ---- 5. MET cut ----
        met_val = float(data['met'][i])
        if met_val <= 250.0:
            continue

        met_phi_val = float(data['met_phi'][i])

        # ---- 6. Transverse mass M_T ----
        dphi_lm = wrap_dphi(lep_phi - met_phi_val)
        mt = math.sqrt(2.0 * lep_pt * met_val * (1.0 - math.cos(dphi_lm)))
        if mt <= 150.0:
            continue

        # ---- 7. M_lb (minimum lepton-bjet invariant mass) ----
        min_mlb = float('inf')
        for bpt, beta, bphi in btag_jets:
            deta_lb = lep_eta - beta
            dphi_lb = wrap_dphi(lep_phi - bphi)
            mlb_sq = 2.0 * lep_pt * bpt * (math.cosh(deta_lb) - math.cos(dphi_lb))
            mlb = math.sqrt(max(0.0, mlb_sq))
            if mlb < min_mlb:
                min_mlb = mlb
        if min_mlb >= 175.0:
            continue

        # ---- 8. Delta-phi(jet, MET) requirements ----
        pass_dphi = True
        for j_idx, (jpt, jeta, jphi, jbt) in enumerate(sel_jets):
            adphi = abs(wrap_dphi(jphi - met_phi_val))
            if j_idx < 2:                       # two leading jets
                if adphi < 0.5:
                    pass_dphi = False
                    break
            else:                               # additional jets
                if adphi < 0.3:
                    pass_dphi = False
                    break
        if not pass_dphi:
            continue

        # ---- Bin in MET ----
        for k in range(n_bins):
            if met_edges[k] <= met_val < met_edges[k + 1]:
                bin_counts[k] += 1
                break

    # ---- Compute yields ----
    yields = [c * norm for c in bin_counts]
    return yields


def write_histogram(yields):
    """Read the template, fill bins, write result."""
    with open('/app/results/histogram_template.yaml') as f:
        raw = f.read()

    docs = list(yaml.safe_load_all(raw))
    metadata = docs[0]
    histogram = docs[1]

    for k, y in enumerate(yields):
        histogram['dependent_variables'][0]['values'][k] = {'value': round(y, 6)}

    with open('/app/results/histogram.yaml', 'w') as f:
        yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
        f.write('---\n')
        yaml.dump(histogram, f, default_flow_style=False, sort_keys=False)


if __name__ == '__main__':
    yields = run_analysis()
    write_histogram(yields)
    print(f"Signal yields per MET bin: {yields}")
    print(f"Total signal yield: {sum(yields):.4f}")
