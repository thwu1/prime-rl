#!/usr/bin/env python3
"""Generate synthetic Monte Carlo signal events for the SUSY stop search task.

Simulates detector-level reconstructed objects for T2tt pair production:
  pp -> t~1 t~1*, t~1 -> t chi0_1
  m(t~1) = 1000 GeV, m(chi0_1) = 50 GeV

Uses a fixed random seed for reproducibility. Output: /app/data/events.npz
"""
import numpy as np
import os

def main():
    rng = np.random.RandomState(20240315)

    N = 48270   # events after generator filter (from 100000 total generated)
    MAX_J = 8   # max jets stored per event
    MAX_L = 3   # max leptons stored per event

    # ---- Event-level counts ----
    event_id = np.arange(N, dtype=np.int32)
    n_jets = np.clip(rng.poisson(5.5, N), 2, MAX_J).astype(np.int32)
    n_lep = rng.choice(
        [0, 1, 2, 3], size=N, p=[0.28, 0.47, 0.20, 0.05]
    ).astype(np.int32)

    # ---- Pre-allocate arrays ----
    jet_pt   = np.zeros((N, MAX_J), dtype=np.float32)
    jet_eta  = np.zeros((N, MAX_J), dtype=np.float32)
    jet_phi  = np.zeros((N, MAX_J), dtype=np.float32)
    jet_btag = np.zeros((N, MAX_J), dtype=np.int32)

    lep_pt     = np.zeros((N, MAX_L), dtype=np.float32)
    lep_eta    = np.zeros((N, MAX_L), dtype=np.float32)
    lep_phi    = np.zeros((N, MAX_L), dtype=np.float32)
    lep_pdgid  = np.zeros((N, MAX_L), dtype=np.int32)
    lep_reliso = np.zeros((N, MAX_L), dtype=np.float32)

    # ---- Bulk random draws ----
    # Jets: first 2 slots model b-jets from top decays (harder pT, higher btag)
    raw_jpt = np.zeros((N, MAX_J), dtype=np.float64)
    raw_jpt[:, :2] = rng.exponential(60, (N, 2)) + 25
    raw_jpt[:, 2:] = rng.exponential(50, (N, MAX_J - 2)) + 15

    raw_jeta = rng.uniform(-3.0, 3.0, (N, MAX_J)).astype(np.float64)
    raw_jphi = rng.uniform(-np.pi, np.pi, (N, MAX_J)).astype(np.float64)

    bt_rand = rng.random((N, MAX_J))
    raw_jbtag = np.zeros((N, MAX_J), dtype=np.int32)
    raw_jbtag[:, :2] = (bt_rand[:, :2] < 0.68).astype(np.int32)
    raw_jbtag[:, 2:] = (bt_rand[:, 2:] < 0.015).astype(np.int32)

    # ---- Per-event: sort jets by pT, mask unused slots ----
    for i in range(N):
        nj = n_jets[i]
        idx = np.argsort(-raw_jpt[i, :nj])
        jet_pt[i, :nj]   = raw_jpt[i, idx].astype(np.float32)
        jet_eta[i, :nj]  = raw_jeta[i, idx].astype(np.float32)
        jet_phi[i, :nj]  = raw_jphi[i, idx].astype(np.float32)
        jet_btag[i, :nj] = raw_jbtag[i, idx]

    # ---- Per-event: generate leptons, sort by pT ----
    for i in range(N):
        nl = n_lep[i]
        if nl == 0:
            continue
        pts = np.sort(rng.exponential(35, nl) + 5)[::-1]
        lep_pt[i, :nl]     = pts.astype(np.float32)
        lep_eta[i, :nl]    = rng.uniform(-2.7, 2.7, nl).astype(np.float32)
        lep_phi[i, :nl]    = rng.uniform(-np.pi, np.pi, nl).astype(np.float32)
        lep_pdgid[i, :nl]  = rng.choice([11, -11, 13, -13], nl)
        lep_reliso[i, :nl] = rng.exponential(0.03, nl).astype(np.float32)

    # ---- MET ----
    met      = (rng.exponential(180, N) + 80).astype(np.float32)
    met_phi  = rng.uniform(-np.pi, np.pi, N).astype(np.float32)

    # ---- Save ----
    os.makedirs('/app/data', exist_ok=True)
    np.savez(
        '/app/data/events.npz',
        event_id=event_id,
        n_jets=n_jets, jet_pt=jet_pt, jet_eta=jet_eta,
        jet_phi=jet_phi, jet_btag=jet_btag,
        n_lep=n_lep, lep_pt=lep_pt, lep_eta=lep_eta,
        lep_phi=lep_phi, lep_pdgid=lep_pdgid, lep_reliso=lep_reliso,
        met=met, met_phi=met_phi,
    )
    print(f"Generated {N} events -> /app/data/events.npz")


if __name__ == '__main__':
    main()
