#!/usr/bin/env python3
"""Generate synthetic signal events for stop pair production analysis.
"""
import numpy as np
import os

SEED = 42
N_EVENTS = 100000
MAX_JETS = 10
MAX_LEPS = 4

np.random.seed(SEED)

# --- Jet generation ---
# Poisson-distributed jet multiplicity, clipped to [1, MAX_JETS]
n_jets = np.minimum(np.random.poisson(6.0, N_EVENTS), MAX_JETS).astype(np.int32)
n_jets = np.maximum(n_jets, 1)

jet_pt = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
jet_eta = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
jet_phi = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
jet_btag = np.zeros((N_EVENTS, MAX_JETS), dtype=np.int32)

# Column-wise vectorized generation
for col in range(MAX_JETS):
    mask = n_jets > col
    n_valid = mask.sum()
    if n_valid > 0:
        # Jet pT: exponential decay above 20 GeV threshold
        jet_pt[mask, col] = 20.0 + np.random.exponential(80.0, n_valid)
        # Pseudorapidity: Gaussian centered at 0
        jet_eta[mask, col] = np.random.normal(0, 1.3, n_valid)
        # Azimuthal angle: uniform
        jet_phi[mask, col] = np.random.uniform(-np.pi, np.pi, n_valid)
        # b-tagging: flat 20% probability per jet
        jet_btag[mask, col] = (np.random.uniform(0, 1, n_valid) < 0.20).astype(np.int32)

# Sort jets by pT within each event (descending)
for i in range(N_EVENTS):
    nj = n_jets[i]
    if nj > 1:
        idx = np.argsort(jet_pt[i, :nj])[::-1]
        jet_pt[i, :nj] = jet_pt[i, idx]
        jet_eta[i, :nj] = jet_eta[i, idx]
        jet_phi[i, :nj] = jet_phi[i, idx]
        jet_btag[i, :nj] = jet_btag[i, idx]

# --- Lepton generation ---
# ~12% have 1 lepton, ~3% have 2 (from W->lnu decays)
n_lep = np.zeros(N_EVENTS, dtype=np.int32)
lep_rand = np.random.uniform(0, 1, N_EVENTS)
n_lep[lep_rand < 0.12] = 1
n_lep[lep_rand < 0.03] = 2

lep_pt = np.zeros((N_EVENTS, MAX_LEPS), dtype=np.float64)
lep_eta = np.zeros((N_EVENTS, MAX_LEPS), dtype=np.float64)
lep_phi = np.zeros((N_EVENTS, MAX_LEPS), dtype=np.float64)

for col in range(MAX_LEPS):
    mask = n_lep > col
    n_valid = mask.sum()
    if n_valid > 0:
        lep_pt[mask, col] = 5.0 + np.random.exponential(25.0, n_valid)
        lep_eta[mask, col] = np.random.normal(0, 1.5, n_valid)
        lep_phi[mask, col] = np.random.uniform(-np.pi, np.pi, n_valid)

# --- MET generation ---
# Gamma-distributed MET (from neutralinos + neutrinos)
met_pt = 30.0 + np.random.gamma(2.8, 130.0, N_EVENTS)
met_phi = np.random.uniform(-np.pi, np.pi, N_EVENTS)

# --- Event weights ---
# Near-unity weights with small variation (generator-level)
weight = np.abs(np.random.normal(1.0, 0.08, N_EVENTS))
weight = np.maximum(weight, 0.1)

# --- Save ---
os.makedirs('/app/data', exist_ok=True)
np.savez_compressed('/app/data/events.npz',
    n_jets=n_jets,
    jet_pt=jet_pt,
    jet_eta=jet_eta,
    jet_phi=jet_phi,
    jet_btag=jet_btag,
    n_lep=n_lep,
    lep_pt=lep_pt,
    lep_eta=lep_eta,
    lep_phi=lep_phi,
    met_pt=met_pt,
    met_phi=met_phi,
    weight=weight
)
print(f"Generated {N_EVENTS} events saved to /app/data/events.npz")
