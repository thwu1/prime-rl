#!/usr/bin/env python3
"""Reference analysis implementation used by tests for comparison.

This is an independent copy of the analysis logic. It writes reference
yields to /tmp/reference_yields.json so test_state.py can compare.
"""

import math
import json
import numpy as np


def wrap_dphi(dphi):
    """Fold delta-phi into [-pi, pi]."""
    return dphi - 2.0 * math.pi * round(dphi / (2.0 * math.pi))


def run_reference():
    data = np.load('/app/data/events.npz')
    with open('/app/config/signal_info.json') as f:
        info = json.load(f)

    sigma_fb  = info['cross_section_pb'] * 1000.0
    sigma_nlo = sigma_fb * info['k_factor_nlo_nll']
    lumi      = info['luminosity_fb']
    n_gen     = info['n_events_generated']
    norm      = sigma_nlo * lumi / n_gen

    met_edges = [250.0, 350.0, 450.0, 550.0, float('inf')]
    n_bins    = len(met_edges) - 1
    counts    = [0] * n_bins

    n_ev = len(data['event_id'])

    for i in range(n_ev):
        nj = int(data['n_jets'][i])
        nl = int(data['n_lep'][i])

        # Signal leptons
        sig = []
        for l in range(nl):
            pt  = float(data['lep_pt'][i, l])
            eta = float(data['lep_eta'][i, l])
            pdg = int(data['lep_pdgid'][i, l])
            iso = float(data['lep_reliso'][i, l])
            if pt < 20.0:
                continue
            aeta = abs(eta)
            apdg = abs(pdg)
            if apdg == 11:
                if aeta > 2.5 or (1.4442 < aeta < 1.566) or iso > 0.1:
                    continue
            elif apdg == 13:
                if aeta > 2.4 or iso > 0.15:
                    continue
            else:
                continue
            sig.append((pt, eta, float(data['lep_phi'][i, l])))

        if len(sig) != 1:
            continue
        lpt, leta, lphi = sig[0]

        # Baseline veto
        nb = 0
        for l in range(nl):
            if float(data['lep_pt'][i, l]) >= 10.0 and abs(float(data['lep_eta'][i, l])) <= 2.5:
                nb += 1
        if nb > 1:
            continue

        # Jet selection + overlap removal
        jets = []
        for j in range(nj):
            jpt  = float(data['jet_pt'][i, j])
            jeta = float(data['jet_eta'][i, j])
            jphi = float(data['jet_phi'][i, j])
            jbt  = int(data['jet_btag'][i, j])
            if jpt < 30.0 or abs(jeta) > 2.4:
                continue
            de = jeta - leta
            dp = wrap_dphi(jphi - lphi)
            if math.sqrt(de * de + dp * dp) < 0.4:
                continue
            jets.append((jpt, jeta, jphi, jbt))

        if len(jets) < 4:
            continue
        jets.sort(key=lambda x: -x[0])

        # b-tag
        bjets = [(p, e, ph) for p, e, ph, b in jets if b]
        if not bjets:
            continue

        # MET
        met = float(data['met'][i])
        if met <= 250.0:
            continue
        mphi = float(data['met_phi'][i])

        # MT
        dp_lm = wrap_dphi(lphi - mphi)
        mt = math.sqrt(2.0 * lpt * met * (1.0 - math.cos(dp_lm)))
        if mt <= 150.0:
            continue

        # M_lb
        mmlb = float('inf')
        for bp, be, bph in bjets:
            de = leta - be
            dp = wrap_dphi(lphi - bph)
            sq = 2.0 * lpt * bp * (math.cosh(de) - math.cos(dp))
            mmlb = min(mmlb, math.sqrt(max(0.0, sq)))
        if mmlb >= 175.0:
            continue

        # dphi(jet, MET)
        ok = True
        for ji, (jp, je, jph, jb) in enumerate(jets):
            adp = abs(wrap_dphi(jph - mphi))
            if ji < 2 and adp < 0.5:
                ok = False
                break
            if ji >= 2 and adp < 0.3:
                ok = False
                break
        if not ok:
            continue

        # Bin
        for k in range(n_bins):
            if met_edges[k] <= met < met_edges[k + 1]:
                counts[k] += 1
                break

    yields = [c * norm for c in counts]
    return yields


if __name__ == '__main__':
    yields = run_reference()
    with open('/tmp/reference_yields.json', 'w') as f:
        json.dump(yields, f)
    print(f"Reference yields: {yields}")
