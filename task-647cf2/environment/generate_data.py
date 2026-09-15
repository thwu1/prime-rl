#!/usr/bin/env python3
"""Generate synthetic MC events in ROOT TTree format.
"""
import numpy as np
import uproot
import os

SEED = 73
MAX_JETS = 10
MAX_LEPS = 4


def generate(rng, n, is_signal):
    mu_j = 5.5 if is_signal else 4.5
    n_jets = np.clip(rng.poisson(mu_j, n), 1, MAX_JETS).astype(np.int32)

    jet_pt = np.zeros((n, MAX_JETS), dtype=np.float64)
    jet_eta = np.zeros((n, MAX_JETS), dtype=np.float64)
    jet_phi = np.zeros((n, MAX_JETS), dtype=np.float64)
    jet_btag = np.zeros((n, MAX_JETS), dtype=np.int32)

    for c in range(MAX_JETS):
        m = n_jets > c
        nv = m.sum()
        if nv == 0:
            continue
        sc = 90.0 if is_signal else 55.0
        jet_pt[m, c] = 25.0 + rng.exponential(sc, nv)
        jet_eta[m, c] = rng.normal(0.0, 1.3, nv)
        jet_phi[m, c] = rng.uniform(-np.pi, np.pi, nv)
        bp = 0.25 if is_signal else 0.18
        jet_btag[m, c] = (rng.uniform(0, 1, nv) < bp).astype(np.int32)

    for i in range(n):
        nj = n_jets[i]
        if nj > 1:
            idx = np.argsort(jet_pt[i, :nj])[::-1]
            jet_pt[i, :nj] = jet_pt[i, idx]
            jet_eta[i, :nj] = jet_eta[i, idx]
            jet_phi[i, :nj] = jet_phi[i, idx]
            jet_btag[i, :nj] = jet_btag[i, idx]

    n_lep = np.zeros(n, dtype=np.int32)
    lr = rng.uniform(0, 1, n)
    f1, f2 = (0.10, 0.02) if is_signal else (0.25, 0.08)
    n_lep[lr < f1] = 1
    n_lep[lr < f2] = 2

    lep_pt = np.zeros((n, MAX_LEPS), dtype=np.float64)
    lep_eta = np.zeros((n, MAX_LEPS), dtype=np.float64)
    lep_phi = np.zeros((n, MAX_LEPS), dtype=np.float64)
    for c in range(MAX_LEPS):
        m = n_lep > c
        nv = m.sum()
        if nv > 0:
            lep_pt[m, c] = 5.0 + rng.exponential(25.0, nv)
            lep_eta[m, c] = rng.normal(0.0, 1.5, nv)
            lep_phi[m, c] = rng.uniform(-np.pi, np.pi, nv)

    sh, sc, off = (3.0, 140.0, 40.0) if is_signal else (2.2, 70.0, 15.0)
    met = off + rng.gamma(sh, sc, n)
    met_phi = rng.uniform(-np.pi, np.pi, n)

    weight = np.maximum(np.abs(rng.normal(1.0, 0.06, n)), 0.1)

    return {
        'n_jets': n_jets,
        'jet_pt': jet_pt,
        'jet_eta': jet_eta,
        'jet_phi': jet_phi,
        'jet_btag': jet_btag,
        'n_lep': n_lep,
        'lep_pt': lep_pt,
        'lep_eta': lep_eta,
        'lep_phi': lep_phi,
        'met': met,
        'met_phi': met_phi,
        'weight': weight,
    }


rng = np.random.RandomState(SEED)
os.makedirs('/app/data', exist_ok=True)

sig = generate(rng, 50000, True)
with uproot.recreate('/app/data/signal.root') as f:
    f['events'] = sig

bkg = generate(rng, 200000, False)
with uproot.recreate('/app/data/background.root') as f:
    f['events'] = bkg

print("Generated signal.root (50000) and background.root (200000)")
