#!/usr/bin/env python3
"""
Solution: stop pair production exclusion analysis pipeline.
"""
import numpy as np
import uproot
import json
import math
import pyhf


def dphi(phi1, phi2):
    dp = abs(phi1 - phi2)
    return dp if dp <= math.pi else 2.0 * math.pi - dp


def delta_r(eta1, phi1, eta2, phi2):
    return math.sqrt((eta1 - eta2) ** 2 + dphi(phi1, phi2) ** 2)


def read_tree(path):
    f = uproot.open(path)
    t = f['events']
    return {k: t[k].array(library='np') for k in t.keys()}


def process(data, jes, btag_sf=None):
    """Process events through selection. Returns (sr_weights, cr_weights) per bin."""
    N = len(data['weight'])
    edges = [250.0, 350.0, 450.0, 600.0, 800.0, float('inf')]
    sr_w = [0.0] * 5
    cr_w = [0.0] * 5

    for i in range(N):
        nj = int(data['n_jets'][i])
        nl = int(data['n_lep'][i])
        w = float(data['weight'][i])

        # JES correction
        jpt = [float(data['jet_pt'][i, j]) * jes for j in range(nj)]
        jeta = [float(data['jet_eta'][i, j]) for j in range(nj)]
        jphi = [float(data['jet_phi'][i, j]) for j in range(nj)]
        jbt = [int(data['jet_btag'][i, j]) for j in range(nj)]

        # Type-I MET correction
        mx = float(data['met'][i]) * math.cos(float(data['met_phi'][i]))
        my = float(data['met'][i]) * math.sin(float(data['met_phi'][i]))
        for j in range(nj):
            rpt = float(data['jet_pt'][i, j])
            if rpt > 15.0:
                mx -= (jes - 1.0) * rpt * math.cos(float(data['jet_phi'][i, j]))
                my -= (jes - 1.0) * rpt * math.sin(float(data['jet_phi'][i, j]))
        met_val = math.sqrt(mx * mx + my * my)
        mphi = math.atan2(my, mx)

        # Jet selection
        spt, seta, sphi, sbt = [], [], [], []
        for j in range(nj):
            if jpt[j] > 30.0 and abs(jeta[j]) < 2.4:
                spt.append(jpt[j])
                seta.append(jeta[j])
                sphi.append(jphi[j])
                sbt.append(jbt[j])

        # Lepton candidates
        lce, lcp = [], []
        for li in range(nl):
            lp = float(data['lep_pt'][i, li])
            le = float(data['lep_eta'][i, li])
            lph = float(data['lep_phi'][i, li])
            if lp > 10.0 and abs(le) < 2.5:
                lce.append(le)
                lcp.append(lph)

        # Overlap removal 1: jets near leptons
        apt, aeta, aphi, abt = [], [], [], []
        for ji in range(len(spt)):
            ok = True
            for li in range(len(lce)):
                if delta_r(seta[ji], sphi[ji], lce[li], lcp[li]) < 0.2:
                    ok = False
                    break
            if ok:
                apt.append(spt[ji])
                aeta.append(seta[ji])
                aphi.append(sphi[ji])
                abt.append(sbt[ji])

        # Overlap removal 2: leptons near surviving jets
        nlep = 0
        for li in range(len(lce)):
            ok = True
            for ji in range(len(apt)):
                if delta_r(lce[li], lcp[li], aeta[ji], aphi[ji]) < 0.4:
                    ok = False
                    break
            if ok:
                nlep += 1

        # Baseline selection
        if nlep > 0:
            continue
        naj = len(apt)
        if naj < 4:
            continue

        order = sorted(range(naj), key=lambda k: apt[k], reverse=True)
        apt = [apt[k] for k in order]
        aeta = [aeta[k] for k in order]
        aphi = [aphi[k] for k in order]
        abt = [abt[k] for k in order]

        bidx = [k for k in range(naj) if abt[k] == 1]
        if not bidx:
            continue
        if met_val <= 250.0:
            continue
        if apt[0] <= 100.0:
            continue
        nc = min(4, naj)
        if min(dphi(aphi[k], mphi) for k in range(nc)) <= 0.5:
            continue

        # btag SF reweighting (applied after selection)
        if btag_sf is not None:
            w *= btag_sf ** len(bidx)

        HT = sum(apt)
        ms = met_val / math.sqrt(HT)

        # MET bin
        bn = -1
        for b in range(5):
            if edges[b] <= met_val < edges[b + 1]:
                bn = b
                break
        if bn < 0:
            continue

        # Common SR/CR cuts
        ok_common = True
        if HT <= 500.0:
            ok_common = False
        if ok_common and apt[bidx[0]] <= 80.0:
            ok_common = False
        if ok_common and len(bidx) >= 2:
            if abs(aeta[bidx[0]] - aeta[bidx[1]]) >= 2.0:
                ok_common = False
        if not ok_common:
            continue

        # SR vs CR by MET significance
        if ms > 12.0:
            sr_w[bn] += w
        elif ms >= 5.0:
            cr_w[bn] += w

    return sr_w, cr_w


def to_yields(weights, sum_all_w, xsec, lumi):
    nexp = xsec * lumi * 1000.0
    return [nexp * wv / sum_all_w for wv in weights]


def main():
    with open('/app/data/config.json') as f:
        cfg = json.load(f)

    JES = cfg['jet_energy_scale']
    sxs = cfg['signal_cross_section_pb']
    bxs = cfg['background_cross_section_pb']
    lumi = cfg['luminosity_ifb']

    # Read ROOT files
    sig = read_tree('/app/data/signal.root')
    bkg = read_tree('/app/data/background.root')
    sw = float(np.sum(sig['weight']))
    bw = float(np.sum(bkg['weight']))

    # --- Nominal ---
    s_sr, _ = process(sig, JES)
    b_sr, b_cr = process(bkg, JES)
    sig_sr = to_yields(s_sr, sw, sxs, lumi)
    bkg_sr = to_yields(b_sr, bw, bxs, lumi)
    bkg_cr = to_yields(b_cr, bw, bxs, lumi)

    # --- JES up/down ---
    jes_up = JES * 1.023
    jes_dn = JES * 0.977
    s_sr_ju, _ = process(sig, jes_up)
    s_sr_jd, _ = process(sig, jes_dn)
    b_sr_ju, b_cr_ju = process(bkg, jes_up)
    b_sr_jd, b_cr_jd = process(bkg, jes_dn)
    sig_sr_ju = to_yields(s_sr_ju, sw, sxs, lumi)
    sig_sr_jd = to_yields(s_sr_jd, sw, sxs, lumi)
    bkg_sr_ju = to_yields(b_sr_ju, bw, bxs, lumi)
    bkg_sr_jd = to_yields(b_sr_jd, bw, bxs, lumi)
    bkg_cr_ju = to_yields(b_cr_ju, bw, bxs, lumi)
    bkg_cr_jd = to_yields(b_cr_jd, bw, bxs, lumi)

    # --- btag SF up/down (signal only) ---
    s_sr_bu, _ = process(sig, JES, btag_sf=1.08)
    s_sr_bd, _ = process(sig, JES, btag_sf=0.92)
    sig_sr_bu = to_yields(s_sr_bu, sw, sxs, lumi)
    sig_sr_bd = to_yields(s_sr_bd, sw, sxs, lumi)

    # --- Epsilon floor for pyhf ---
    eps = 1e-6

    def safe(v):
        return [max(x, eps) for x in v]

    sig_sr = safe(sig_sr)
    bkg_sr = safe(bkg_sr)
    bkg_cr = safe(bkg_cr)

    # --- Build pyhf workspace ---
    workspace = {
        "channels": [
            {
                "name": "SR",
                "samples": [
                    {
                        "name": "signal",
                        "data": sig_sr,
                        "modifiers": [
                            {"name": "mu", "type": "normfactor", "data": None},
                            {"name": "lumi", "type": "normsys",
                             "data": {"hi": 1.025, "lo": 0.975}},
                            {"name": "JES", "type": "histosys",
                             "data": {"hi_data": safe(sig_sr_ju),
                                      "lo_data": safe(sig_sr_jd)}},
                            {"name": "btag", "type": "histosys",
                             "data": {"hi_data": safe(sig_sr_bu),
                                      "lo_data": safe(sig_sr_bd)}},
                        ]
                    },
                    {
                        "name": "background",
                        "data": bkg_sr,
                        "modifiers": [
                            {"name": "bkg_norm", "type": "normfactor", "data": None},
                            {"name": "JES", "type": "histosys",
                             "data": {"hi_data": safe(bkg_sr_ju),
                                      "lo_data": safe(bkg_sr_jd)}},
                        ]
                    }
                ]
            },
            {
                "name": "CR",
                "samples": [
                    {
                        "name": "background",
                        "data": bkg_cr,
                        "modifiers": [
                            {"name": "bkg_norm", "type": "normfactor", "data": None},
                            {"name": "JES", "type": "histosys",
                             "data": {"hi_data": safe(bkg_cr_ju),
                                      "lo_data": safe(bkg_cr_jd)}},
                        ]
                    }
                ]
            }
        ],
        "observations": [
            {"name": "SR", "data": bkg_sr},
            {"name": "CR", "data": bkg_cr},
        ],
        "measurements": [
            {
                "name": "exclusion",
                "config": {
                    "poi": "mu",
                    "parameters": []
                }
            }
        ],
        "version": "1.0.0"
    }

    with open('/app/workspace.json', 'w') as f:
        json.dump(workspace, f, indent=2)
    print("Workspace written to /app/workspace.json")

    # --- CLs hypothesis test ---
    ws = pyhf.Workspace(workspace)
    model = ws.model()
    data = ws.data(model)

    CLs_obs, CLs_exp = pyhf.infer.hypotest(
        1.0, data, model, test_stat="qtilde", return_expected_set=True
    )

    # Upper limit scan
    poi_scan = np.linspace(0.001, 5.0, 100)
    obs_lim, exp_lims = pyhf.infer.intervals.upper_limits.upper_limit(
        data, model, poi_scan, level=0.05
    )

    results = {
        "cls_obs": float(CLs_obs),
        "cls_exp_band": [float(v) for v in CLs_exp],
        "upper_limit_mu_exp": float(exp_lims[2]),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"CLs(mu=1) = {float(CLs_obs):.6f}")
    print(f"Expected upper limit on mu: {float(exp_lims[2]):.4f}")
    print(f"Signal SR yields: {[round(v, 2) for v in sig_sr]}")
    print(f"Background SR yields: {[round(v, 2) for v in bkg_sr]}")
    print(f"Background CR yields: {[round(v, 2) for v in bkg_cr]}")


if __name__ == '__main__':
    main()
