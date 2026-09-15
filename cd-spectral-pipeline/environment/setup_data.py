#!/usr/bin/env python3
"""Generate deterministic CD spectroscopy test data for the cdspec pipeline."""
import os
import math
import json
import random


random.seed(42)

DATA_DIR = "/app/data"
LIBRARY_DIR = os.path.join(DATA_DIR, "library")
VALIDATION_DIR = os.path.join(DATA_DIR, "validation")

WAVELENGTHS = [float(w) for w in range(190, 261)]  # 190-260 nm, 1 nm step


def gaussian(x, amp, center, two_sigma_sq):
    """Gaussian: amp * exp(-(x-center)^2 / two_sigma_sq)."""
    return amp * math.exp(-(x - center) ** 2 / two_sigma_sq)


def basis_helix(wl):
    """Alpha-helix basis spectrum (delta epsilon)."""
    return (gaussian(wl, 23.0, 192.0, 18.0)
            - gaussian(wl, 11.0, 208.0, 24.5)
            - gaussian(wl, 12.0, 222.0, 32.0))


def basis_strand(wl):
    """Beta-strand basis spectrum (delta epsilon)."""
    return (gaussian(wl, 4.5, 196.0, 32.0)
            - gaussian(wl, 4.8, 218.0, 50.0))


def basis_turn(wl):
    """Turn basis spectrum (delta epsilon)."""
    return (gaussian(wl, 4.0, 190.0, 18.0)
            - gaussian(wl, 3.0, 205.0, 32.0)
            + gaussian(wl, 1.2, 225.0, 50.0))


def basis_coil(wl):
    """Unordered/coil basis spectrum (delta epsilon)."""
    return (-gaussian(wl, 6.5, 198.0, 24.5)
            + gaussian(wl, 1.5, 220.0, 50.0))


BASIS_FUNCS = [basis_helix, basis_strand, basis_turn, basis_coil]


def make_spectrum(fracs, wavelengths=None, noise_std=0.0):
    """Generate a composite spectrum from basis fractions + optional noise."""
    if wavelengths is None:
        wavelengths = WAVELENGTHS
    spectrum = []
    for wl in wavelengths:
        val = sum(f * fn(wl) for f, fn in zip(fracs, BASIS_FUNCS))
        if noise_std > 0:
            val += random.gauss(0, noise_std)
        spectrum.append(round(val, 6))
    return spectrum


def write_csv(path, header, rows):
    """Write a CSV file."""
    with open(path, "w") as f:
        f.write(",".join(str(h) for h in header) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    os.makedirs(VALIDATION_DIR, exist_ok=True)

    # 1. Basis spectra (pure secondary structure reference spectra)
    basis_rows = []
    for wl in WAVELENGTHS:
        basis_rows.append([
            wl,
            round(basis_helix(wl), 6),
            round(basis_strand(wl), 6),
            round(basis_turn(wl), 6),
            round(basis_coil(wl), 6),
        ])
    write_csv(
        os.path.join(DATA_DIR, "basis_spectra.csv"),
        ["wavelength", "helix", "strand", "turn", "coil"],
        basis_rows,
    )

    # 2. Protein A: aldolase-like mixed alpha/beta composition
    fracs_A = [0.425, 0.138, 0.103, 0.334]
    spec_A = make_spectrum(fracs_A, noise_std=0.05)
    write_csv(
        os.path.join(DATA_DIR, "protein_A.csv"),
        ["wavelength", "delta_epsilon"],
        [[WAVELENGTHS[i], spec_A[i]] for i in range(len(WAVELENGTHS))],
    )

    # 3. Protein B: beta-sheet-rich composition
    fracs_B = [0.10, 0.50, 0.15, 0.25]
    spec_B = make_spectrum(fracs_B, noise_std=0.05)
    write_csv(
        os.path.join(DATA_DIR, "protein_B.csv"),
        ["wavelength", "delta_epsilon"],
        [[WAVELENGTHS[i], spec_B[i]] for i in range(len(WAVELENGTHS))],
    )

    # 4. Raw spectrum in millidegrees (for unit conversion testing)
    raw_fracs = [0.30, 0.25, 0.20, 0.25]
    c_mg = 1.0      # mg/mL
    mw = 40000.0     # Da
    nres = 370
    path_l = 0.1     # cm
    mrw = mw / nres
    with open(os.path.join(DATA_DIR, "raw_spectrum.csv"), "w") as f:
        f.write("# concentration_mg_ml=1.0\n")
        f.write("# molecular_weight_da=40000.0\n")
        f.write("# num_residues=370\n")
        f.write("# pathlength_cm=0.1\n")
        f.write("wavelength,millidegrees\n")
        for wl in WAVELENGTHS:
            de = sum(raw_fracs[i] * BASIS_FUNCS[i](wl) for i in range(4))
            mdeg = de * 32980.0 * c_mg * path_l / mrw
            mdeg += random.gauss(0, 2.0)
            f.write("{},{}\n".format(wl, round(mdeg, 4)))

    # 5. Thermal melt data (single two-state transition)
    R = 8.314e-3  # kJ/(mol*K)
    Tm_true = 340.0
    dH_true = 250.0
    a_N, b_N = -15000.0, 30.0
    a_U, b_U = -3000.0, 10.0
    temperatures = [float(t) for t in range(283, 373, 2)]
    melt_rows = []
    for T in temperatures:
        theta_N = a_N + b_N * T
        theta_U = a_U + b_U * T
        exponent = dH_true / R * (1.0 / Tm_true - 1.0 / T)
        exponent = max(min(exponent, 500.0), -500.0)
        K = math.exp(exponent)
        theta = (theta_N + theta_U * K) / (1.0 + K)
        theta += random.gauss(0, 50.0)
        melt_rows.append([T, round(theta, 2)])
    write_csv(
        os.path.join(DATA_DIR, "melt_single.csv"),
        ["temperature_K", "signal"],
        melt_rows,
    )

    # 6. Library of reference spectra for similarity matching
    library_specs = [
        ("ref_mostly_helix.csv", [0.80, 0.05, 0.05, 0.10]),
        ("ref_mostly_strand.csv", [0.05, 0.70, 0.10, 0.15]),
        ("ref_mostly_turn.csv", [0.10, 0.10, 0.50, 0.30]),
        ("ref_mostly_coil.csv", [0.05, 0.05, 0.05, 0.85]),
        ("ref_mixed_1.csv", [0.40, 0.20, 0.15, 0.25]),
        ("ref_mixed_2.csv", [0.30, 0.30, 0.10, 0.30]),
        ("ref_helix_rich.csv", [0.50, 0.10, 0.10, 0.30]),
        ("ref_strand_rich.csv", [0.15, 0.45, 0.20, 0.20]),
    ]
    for name, fracs in library_specs:
        spec = make_spectrum(fracs, noise_std=0.02)
        write_csv(
            os.path.join(LIBRARY_DIR, name),
            ["wavelength", "delta_epsilon"],
            [[WAVELENGTHS[i], spec[i]] for i in range(len(WAVELENGTHS))],
        )

    # === Additional data (appended to preserve random sequence of items 1-6) ===

    # 7. Protein C: turn/coil dominant with near-zero helix (boundary case)
    fracs_C = [0.02, 0.15, 0.30, 0.53]
    spec_C = make_spectrum(fracs_C, noise_std=0.03)
    write_csv(
        os.path.join(DATA_DIR, "protein_C.csv"),
        ["wavelength", "delta_epsilon"],
        [[WAVELENGTHS[i], spec_C[i]] for i in range(len(WAVELENGTHS))],
    )

    # 8. Second thermal melt (steeper cooperative transition)
    Tm_true2 = 320.0
    dH_true2 = 350.0
    a_N2, b_N2 = -12000.0, 25.0
    a_U2, b_U2 = -2000.0, 8.0
    temperatures2 = [float(t) for t in range(283, 363, 2)]
    melt_rows2 = []
    for T in temperatures2:
        theta_N = a_N2 + b_N2 * T
        theta_U = a_U2 + b_U2 * T
        exponent = dH_true2 / R * (1.0 / Tm_true2 - 1.0 / T)
        exponent = max(min(exponent, 500.0), -500.0)
        K = math.exp(exponent)
        theta = (theta_N + theta_U * K) / (1.0 + K)
        theta += random.gauss(0, 40.0)
        melt_rows2.append([T, round(theta, 2)])
    write_csv(
        os.path.join(DATA_DIR, "melt_steep.csv"),
        ["temperature_K", "signal"],
        melt_rows2,
    )

    # 9. Validation test data

    # Good quality spectrum (full 190-260nm range, clean baseline)
    good_spec = make_spectrum(fracs_A, noise_std=0.02)
    write_csv(
        os.path.join(VALIDATION_DIR, "spectrum_good.csv"),
        ["wavelength", "delta_epsilon"],
        [[WAVELENGTHS[i], good_spec[i]] for i in range(len(WAVELENGTHS))],
    )

    # Good metadata (all checks pass)
    with open(os.path.join(VALIDATION_DIR, "meta_good.json"), "w") as f:
        json.dump({
            "instrument_type": "benchtop",
            "ht_voltage_max": 550.0,
            "csa_ratio": 2.01
        }, f, indent=2)

    # Bad metadata (HT too high for benchtop + CSA out of range)
    with open(os.path.join(VALIDATION_DIR, "meta_bad.json"), "w") as f:
        json.dump({
            "instrument_type": "benchtop",
            "ht_voltage_max": 650.0,
            "csa_ratio": 1.80
        }, f, indent=2)

    # Short wavelength range spectrum (starts at 205nm)
    short_wls = [float(w) for w in range(205, 261)]
    short_spec = make_spectrum(fracs_A, wavelengths=short_wls, noise_std=0.02)
    write_csv(
        os.path.join(VALIDATION_DIR, "spectrum_short.csv"),
        ["wavelength", "delta_epsilon"],
        [[short_wls[i], short_spec[i]] for i in range(len(short_wls))],
    )
    with open(os.path.join(VALIDATION_DIR, "meta_short.json"), "w") as f:
        json.dump({
            "instrument_type": "benchtop",
            "ht_voltage_max": 500.0
        }, f, indent=2)

    # Spectrum with bad baseline (systematic offset at long wavelengths)
    bad_baseline_spec = []
    for i, wl in enumerate(WAVELENGTHS):
        val = good_spec[i]
        if wl >= 250:
            val += 3.5  # Simulates scattering artifact
        bad_baseline_spec.append(round(val, 6))
    write_csv(
        os.path.join(VALIDATION_DIR, "spectrum_bad_baseline.csv"),
        ["wavelength", "delta_epsilon"],
        [[WAVELENGTHS[i], bad_baseline_spec[i]] for i in range(len(WAVELENGTHS))],
    )
    with open(os.path.join(VALIDATION_DIR, "meta_baseline.json"), "w") as f:
        json.dump({
            "instrument_type": "benchtop",
            "ht_voltage_max": 500.0
        }, f, indent=2)

    # Synchrotron metadata (HT=650 OK for synchrotron, below 700V threshold)
    with open(os.path.join(VALIDATION_DIR, "meta_synchrotron.json"), "w") as f:
        json.dump({
            "instrument_type": "synchrotron",
            "ht_voltage_max": 650.0,
            "csa_ratio": 2.02
        }, f, indent=2)

    print("Data generated in", DATA_DIR)


if __name__ == "__main__":
    main()
