"""
Tests for stop pair production exclusion workspace.
"""
import numpy as np
import uproot
import json
import math
import os
import pytest
import pyhf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dphi(phi1, phi2):
    dp = abs(phi1 - phi2)
    return dp if dp <= math.pi else 2.0 * math.pi - dp


def _dr(eta1, phi1, eta2, phi2):
    return math.sqrt((eta1 - eta2) ** 2 + _dphi(phi1, phi2) ** 2)


def _read(path):
    f = uproot.open(path)
    t = f['events']
    return {k: t[k].array(library='np') for k in t.keys()}


def _process(data, jes):
    """Run event selection, return (sr_weights, cr_weights) per MET bin."""
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
                if _dr(seta[ji], sphi[ji], lce[li], lcp[li]) < 0.2:
                    ok = False
                    break
            if ok:
                apt.append(spt[ji])
                aeta.append(seta[ji])
                aphi.append(sphi[ji])
                abt.append(sbt[ji])

        # Overlap removal 2: leptons near jets
        nlep = 0
        for li in range(len(lce)):
            ok = True
            for ji in range(len(apt)):
                if _dr(lce[li], lcp[li], aeta[ji], aphi[ji]) < 0.4:
                    ok = False
                    break
            if ok:
                nlep += 1

        # Baseline
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
        if min(_dphi(aphi[k], mphi) for k in range(nc)) <= 0.5:
            continue

        HT = sum(apt)
        ms = met_val / math.sqrt(HT)

        bn = -1
        for b in range(5):
            if edges[b] <= met_val < edges[b + 1]:
                bn = b
                break
        if bn < 0:
            continue

        # Common SR/CR cuts (beyond baseline)
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

        if ms > 12.0:
            sr_w[bn] += w
        elif ms >= 5.0:
            cr_w[bn] += w

    return sr_w, cr_w


def _to_yields(weights, sum_w, xsec, lumi):
    nexp = xsec * lumi * 1000.0
    return [nexp * wv / sum_w for wv in weights]


def _rl2(pred, ref):
    p = np.array(pred, dtype=np.float64)
    r = np.array(ref, dtype=np.float64)
    d = np.sum(r ** 2)
    if d == 0:
        return 0.0 if np.sum(p ** 2) == 0 else float('inf')
    return float(np.sqrt(np.sum((p - r) ** 2) / d))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def config():
    with open('/app/data/config.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def reference(config):
    sig = _read('/app/data/signal.root')
    bkg = _read('/app/data/background.root')
    JES = config['jet_energy_scale']
    sw = float(np.sum(sig['weight']))
    bw = float(np.sum(bkg['weight']))
    sxs = config['signal_cross_section_pb']
    bxs = config['background_cross_section_pb']
    lumi = config['luminosity_ifb']

    s_sr, _ = _process(sig, JES)
    b_sr, b_cr = _process(bkg, JES)

    return {
        'sig_sr': _to_yields(s_sr, sw, sxs, lumi),
        'bkg_sr': _to_yields(b_sr, bw, bxs, lumi),
        'bkg_cr': _to_yields(b_cr, bw, bxs, lumi),
    }


@pytest.fixture(scope='module')
def agent_ws():
    with open('/app/workspace.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def agent_results():
    with open('/app/results.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_workspace_exists():
    assert os.path.exists('/app/workspace.json'), "workspace.json not found"


def test_results_exists():
    assert os.path.exists('/app/results.json'), "results.json not found"


def test_workspace_loadable(agent_ws):
    """Workspace must be loadable by pyhf."""
    ws = pyhf.Workspace(agent_ws)
    model = ws.model()
    assert model is not None


def test_workspace_version(agent_ws):
    assert agent_ws.get('version') == '1.0.0', "Workspace version must be 1.0.0"


def test_workspace_measurement(agent_ws):
    ms = agent_ws.get('measurements', [])
    assert len(ms) >= 1, "No measurements in workspace"
    assert ms[0]['config']['poi'] == 'mu', "POI must be 'mu'"


def test_workspace_channels(agent_ws):
    names = {c['name'] for c in agent_ws['channels']}
    assert 'SR' in names, "Missing SR channel"
    assert 'CR' in names, "Missing CR channel"


def test_sr_samples(agent_ws):
    sr = next(c for c in agent_ws['channels'] if c['name'] == 'SR')
    names = {s['name'] for s in sr['samples']}
    assert 'signal' in names, "SR missing 'signal' sample"
    assert 'background' in names, "SR missing 'background' sample"


def test_cr_samples(agent_ws):
    cr = next(c for c in agent_ws['channels'] if c['name'] == 'CR')
    names = {s['name'] for s in cr['samples']}
    assert 'background' in names, "CR missing 'background' sample"


def test_signal_modifiers(agent_ws):
    """Signal sample must have mu, lumi, JES, and btag modifiers."""
    sr = next(c for c in agent_ws['channels'] if c['name'] == 'SR')
    sig = next(s for s in sr['samples'] if s['name'] == 'signal')
    mod_map = {m['name']: m['type'] for m in sig['modifiers']}
    assert 'mu' in mod_map, "Signal missing 'mu' modifier"
    assert mod_map['mu'] == 'normfactor', "'mu' must be normfactor"
    lk = next((k for k in mod_map if 'lumi' in k.lower()), None)
    assert lk is not None, "Signal missing luminosity modifier"
    jk = next((k for k in mod_map if 'jes' in k.lower()), None)
    assert jk is not None, "Signal missing JES modifier"
    bk = next((k for k in mod_map if 'btag' in k.lower() or 'b_tag' in k.lower()), None)
    assert bk is not None, "Signal missing btag modifier"


def test_background_shared_norm(agent_ws):
    """Background normfactor must be shared between SR and CR."""
    nf_names = {}
    for ch in agent_ws['channels']:
        for s in ch['samples']:
            if s['name'] == 'background':
                for m in s['modifiers']:
                    if m['type'] == 'normfactor' and m['name'] != 'mu':
                        nf_names.setdefault(m['name'], []).append(ch['name'])
    shared = {k: v for k, v in nf_names.items() if len(v) >= 2}
    assert shared, "No shared normfactor on background across SR and CR"


def test_observations_are_bkg_only(agent_ws):
    """Observations must be Asimov background-only (mu=0)."""
    for ch in agent_ws['channels']:
        obs = next((o for o in agent_ws['observations'] if o['name'] == ch['name']), None)
        assert obs is not None, f"Missing observation for channel {ch['name']}"
        bkg = next(s for s in ch['samples'] if s['name'] == 'background')
        for idx, (o_val, b_val) in enumerate(zip(obs['data'], bkg['data'])):
            if b_val > 0.01:
                rel = abs(o_val - b_val) / b_val
                assert rel < 0.05, (
                    f"{ch['name']} obs[{idx}]={o_val:.4f} != bkg[{idx}]={b_val:.4f} "
                    f"(rel={rel:.4f}) -- not Asimov bkg-only"
                )


# ---------------------------------------------------------------------------
# Yield accuracy tests
# ---------------------------------------------------------------------------

def test_sr_signal_yields(agent_ws, reference):
    """Signal yields in SR must match reference within 10% relative L2."""
    sr = next(c for c in agent_ws['channels'] if c['name'] == 'SR')
    sig = next(s for s in sr['samples'] if s['name'] == 'signal')
    rl2 = _rl2(sig['data'], reference['sig_sr'])
    assert rl2 < 0.10, (
        f"Signal SR yields relative L2 = {rl2:.4f} (limit 0.10)\n"
        f"  Agent: {[round(v, 2) for v in sig['data']]}\n"
        f"  Ref:   {[round(v, 2) for v in reference['sig_sr']]}"
    )


def test_sr_bkg_yields(agent_ws, reference):
    """Background yields in SR must match reference within 10% relative L2."""
    sr = next(c for c in agent_ws['channels'] if c['name'] == 'SR')
    bkg = next(s for s in sr['samples'] if s['name'] == 'background')
    rl2 = _rl2(bkg['data'], reference['bkg_sr'])
    assert rl2 < 0.10, (
        f"Background SR yields relative L2 = {rl2:.4f} (limit 0.10)\n"
        f"  Agent: {[round(v, 2) for v in bkg['data']]}\n"
        f"  Ref:   {[round(v, 2) for v in reference['bkg_sr']]}"
    )


def test_cr_bkg_yields(agent_ws, reference):
    """Background yields in CR must match reference within 10% relative L2."""
    cr = next(c for c in agent_ws['channels'] if c['name'] == 'CR')
    bkg = next(s for s in cr['samples'] if s['name'] == 'background')
    rl2 = _rl2(bkg['data'], reference['bkg_cr'])
    assert rl2 < 0.10, (
        f"Background CR yields relative L2 = {rl2:.4f} (limit 0.10)\n"
        f"  Agent: {[round(v, 2) for v in bkg['data']]}\n"
        f"  Ref:   {[round(v, 2) for v in reference['bkg_cr']]}"
    )


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------

def test_cls_from_workspace(agent_ws):
    """CLs at mu=1 computed from the workspace must be valid."""
    ws = pyhf.Workspace(agent_ws)
    model = ws.model()
    data = ws.data(model)
    CLs_obs, CLs_exp = pyhf.infer.hypotest(
        1.0, data, model, test_stat="qtilde", return_expected_set=True
    )
    cls_val = float(CLs_obs)
    assert 0 <= cls_val <= 1, f"CLs = {cls_val}, must be in [0, 1]"


def test_results_structure(agent_results):
    """results.json must have correct fields and types."""
    assert 'cls_obs' in agent_results, "Missing 'cls_obs'"
    assert 'cls_exp_band' in agent_results, "Missing 'cls_exp_band'"
    assert 'upper_limit_mu_exp' in agent_results, "Missing 'upper_limit_mu_exp'"
    assert isinstance(agent_results['cls_obs'], (int, float))
    assert len(agent_results['cls_exp_band']) == 5, "cls_exp_band must have 5 entries"
    assert agent_results['upper_limit_mu_exp'] > 0, "upper_limit_mu_exp must be positive"


def test_cls_consistency(agent_ws, agent_results):
    """CLs reported in results.json must match pyhf computation on workspace."""
    ws = pyhf.Workspace(agent_ws)
    model = ws.model()
    data = ws.data(model)
    CLs_obs, _ = pyhf.infer.hypotest(
        1.0, data, model, test_stat="qtilde", return_expected_set=True
    )
    ref_cls = float(CLs_obs)
    agent_cls = float(agent_results['cls_obs'])
    if ref_cls > 1e-6:
        rel = abs(agent_cls - ref_cls) / ref_cls
        assert rel < 0.05, (
            f"CLs mismatch: workspace gives {ref_cls:.6f}, "
            f"results.json says {agent_cls:.6f} (rel={rel:.4f})"
        )
    else:
        assert abs(agent_cls - ref_cls) < 1e-4, (
            f"CLs mismatch near zero: workspace={ref_cls:.8f}, "
            f"results={agent_cls:.8f}"
        )
