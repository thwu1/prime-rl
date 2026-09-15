#!/usr/bin/env python3
"""
Generate a synthetic particle collision event dataset in ROOT format
and a calibration SQLite database for the VLQ T->tH search task.
Events are drawn from fixed distributions with a deterministic seed
so the downstream analysis yields are reproducible.
"""
import numpy as np
import uproot
import sqlite3
import os

SEED = 20260610
N_EVENTS = 10000
MAX_JETS = 15
MAX_LEPTONS = 4


def generate_root():
    rng = np.random.RandomState(SEED)

    # ------------------------------------------------------------------ #
    #  Number of objects per event                                        #
    # ------------------------------------------------------------------ #
    n_jets = rng.poisson(5.8, N_EVENTS).clip(0, MAX_JETS).astype(np.int32)

    n_leptons = np.zeros(N_EVENTS, dtype=np.int32)
    u = rng.random(N_EVENTS)
    n_leptons[u < 0.22] = 0
    n_leptons[(u >= 0.22) & (u < 0.75)] = 1
    n_leptons[(u >= 0.75) & (u < 0.92)] = 2
    n_leptons[(u >= 0.92) & (u < 0.98)] = 3
    n_leptons[u >= 0.98] = 4

    # ------------------------------------------------------------------ #
    #  Jet arrays                                                         #
    # ------------------------------------------------------------------ #
    jet_pt = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
    jet_eta = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
    jet_phi = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
    jet_mass = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
    jet_btag_deepcsv = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)
    jet_btag_csvv2 = np.zeros((N_EVENTS, MAX_JETS), dtype=np.float64)

    for i in range(N_EVENTS):
        nj = n_jets[i]
        if nj > 0:
            pt = rng.exponential(65.0, nj) + 22.0
            pt = np.sort(pt)[::-1]
            jet_pt[i, :nj] = pt
            jet_eta[i, :nj] = rng.normal(0.0, 1.3, nj)
            jet_phi[i, :nj] = rng.uniform(-np.pi, np.pi, nj)
            jet_mass[i, :nj] = np.abs(rng.normal(12.0, 8.0, nj)) + 0.5

            is_hf = rng.random(nj) < 0.28
            jet_btag_deepcsv[i, :nj] = np.where(
                is_hf,
                rng.beta(8.0, 1.0, nj),
                rng.beta(1.0, 5.0, nj),
            )
            # CSVv2: older tagger with broader distributions
            jet_btag_csvv2[i, :nj] = np.where(
                is_hf,
                rng.beta(5.0, 1.5, nj),
                rng.beta(1.0, 3.0, nj),
            )

    # ------------------------------------------------------------------ #
    #  Lepton arrays                                                      #
    # ------------------------------------------------------------------ #
    lepton_pt = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.float64)
    lepton_eta = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.float64)
    lepton_phi = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.float64)
    lepton_charge = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.int32)
    lepton_flavor = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.int32)
    lepton_mini_iso = np.zeros((N_EVENTS, MAX_LEPTONS), dtype=np.float64)

    for i in range(N_EVENTS):
        nl = n_leptons[i]
        if nl > 0:
            lepton_pt[i, :nl] = rng.exponential(35.0, nl) + 5.0
            lepton_eta[i, :nl] = rng.normal(0.0, 1.1, nl)
            lepton_phi[i, :nl] = rng.uniform(-np.pi, np.pi, nl)
            lepton_charge[i, :nl] = rng.choice([-1, 1], nl)
            lepton_flavor[i, :nl] = rng.choice([0, 1], nl)
            lepton_mini_iso[i, :nl] = rng.exponential(0.07, nl)

    # ------------------------------------------------------------------ #
    #  Missing transverse momentum                                        #
    # ------------------------------------------------------------------ #
    met = rng.exponential(180.0, N_EVENTS) + 30.0
    met_phi = rng.uniform(-np.pi, np.pi, N_EVENTS)

    # ------------------------------------------------------------------ #
    #  Per-event generator weights                                        #
    # ------------------------------------------------------------------ #
    event_weight = rng.lognormal(0.0, 0.5, N_EVENTS)

    # ------------------------------------------------------------------ #
    #  Write ROOT file                                                    #
    # ------------------------------------------------------------------ #
    os.makedirs("/app/data", exist_ok=True)
    with uproot.recreate("/app/data/signal.root") as f:
        f["Events"] = {
            "nJet": n_jets,
            "Jet_pt": jet_pt,
            "Jet_eta": jet_eta,
            "Jet_phi": jet_phi,
            "Jet_mass": jet_mass,
            "Jet_btagDeepCSV": jet_btag_deepcsv,
            "Jet_btagCSVv2": jet_btag_csvv2,
            "nLepton": n_leptons,
            "Lepton_pt": lepton_pt,
            "Lepton_eta": lepton_eta,
            "Lepton_phi": lepton_phi,
            "Lepton_charge": lepton_charge,
            "Lepton_flavor": lepton_flavor,
            "Lepton_miniIso": lepton_mini_iso,
            "MET_pt": met,
            "MET_phi": met_phi,
            "genWeight": event_weight,
        }
        f["Metadata"] = {
            "luminosity_ifb": np.array([137.0]),
            "cross_section_pb": np.array([0.0252]),
            "sqrt_s_gev": np.array([13000.0]),
            "n_generated": np.array([N_EVENTS], dtype=np.int64),
        }

    print(f"Generated {N_EVENTS} events -> /app/data/signal.root")


def generate_calibration():
    os.makedirs("/app/calibration", exist_ok=True)
    db_path = "/app/calibration/calib.db"

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ---- b-tag working points (multiple algorithms/WPs) ----
    c.execute("""CREATE TABLE working_points (
        algorithm TEXT NOT NULL,
        wp_label TEXT NOT NULL,
        era TEXT NOT NULL,
        threshold REAL NOT NULL,
        description TEXT,
        PRIMARY KEY (algorithm, wp_label, era)
    )""")
    wp_data = [
        ("CSVv2", "loose", "Run2", 0.5803, "CSVv2 loose WP"),
        ("CSVv2", "medium", "Run2", 0.8484, "CSVv2 medium WP"),
        ("CSVv2", "tight", "Run2", 0.9535, "CSVv2 tight WP"),
        ("DeepCSV", "loose", "Run2", 0.5426, "DeepCSV loose WP"),
        ("DeepCSV", "medium", "Run2", 0.8838, "DeepCSV medium WP"),
        ("DeepCSV", "tight", "Run2", 0.9693, "DeepCSV tight WP"),
        ("DeepJet", "loose", "Run2", 0.0490, "DeepJet loose WP"),
        ("DeepJet", "medium", "Run2", 0.3040, "DeepJet medium WP"),
        ("DeepJet", "tight", "Run2", 0.7476, "DeepJet tight WP"),
    ]
    c.executemany("INSERT INTO working_points VALUES (?, ?, ?, ?, ?)", wp_data)

    # ---- systematic uncertainties ----
    c.execute("""CREATE TABLE systematic_uncertainties (
        source TEXT NOT NULL,
        parameter TEXT NOT NULL,
        value REAL NOT NULL,
        applicable_to TEXT,
        description TEXT,
        PRIMARY KEY (source, parameter)
    )""")
    syst_data = [
        ("JES", "scale_delta", 0.03, "jet_pt",
         "Fractional jet energy scale uncertainty"),
        ("JER", "smear_delta", 0.05, "jet_pt",
         "Jet energy resolution smearing (not used in SR-A)"),
        ("btag_sf", "threshold_delta", 0.02, "btag_disc",
         "b-tag discriminant threshold shift"),
        ("lepton_sf", "weight_delta", 0.01, "event_weight",
         "Lepton scale factor uncertainty (not used in SR-A)"),
        ("pileup", "weight_delta", 0.005, "event_weight",
         "Pileup reweighting uncertainty (not used in SR-A)"),
    ]
    c.executemany(
        "INSERT INTO systematic_uncertainties VALUES (?, ?, ?, ?, ?)",
        syst_data,
    )

    # ---- analysis configuration ----
    c.execute("""CREATE TABLE analysis_config (
        parameter TEXT PRIMARY KEY,
        value REAL NOT NULL,
        unit TEXT,
        description TEXT
    )""")
    config_data = [
        ("luminosity", 137.0, "ifb", "Integrated luminosity"),
        ("cross_section", 0.0252, "pb", "Signal production cross-section"),
        ("sqrt_s", 13000.0, "GeV", "Centre-of-mass energy"),
    ]
    c.executemany(
        "INSERT INTO analysis_config VALUES (?, ?, ?, ?)", config_data
    )

    conn.commit()
    conn.close()
    print(f"Generated calibration DB -> {db_path}")


if __name__ == "__main__":
    generate_root()
    generate_calibration()
