#!/usr/bin/env python3
"""Phased array communication link budget analyzer.

Computes Dolph-Chebyshev weights, array directivity, impedance matching
through transmission lines, and end-to-end link budget.
"""

import json
import sys
import numpy as np


# ──────────────────────────────────────────────────────────────────────
# Chebyshev polynomial evaluation
# ──────────────────────────────────────────────────────────────────────

def chebyshev_poly(n, x):
    """Evaluate Chebyshev polynomial T_n(x) for real x."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    result = np.zeros_like(x)

    mask_in = np.abs(x) <= 1.0
    if np.any(mask_in):
        result[mask_in] = np.cos(n * np.arccos(np.clip(x[mask_in], -1.0, 1.0)))

    mask_pos = x > 1.0
    if np.any(mask_pos):
        result[mask_pos] = np.cosh(n * np.arccosh(x[mask_pos]))

    mask_neg = x < -1.0
    if np.any(mask_neg):
        result[mask_neg] = ((-1) ** n) * np.cosh(n * np.arccosh(-x[mask_neg]))

    return result


# ──────────────────────────────────────────────────────────────────────
# Dolph-Chebyshev weights via DFT method
# ──────────────────────────────────────────────────────────────────────

def dolph_chebyshev_weights(N, sll_dB):
    """Compute normalized Dolph-Chebyshev amplitude weights.

    Parameters
    ----------
    N : int
        Number of array elements.
    sll_dB : float
        Sidelobe level in dB (negative, e.g. -25).

    Returns
    -------
    w : ndarray of shape (N,)
        Real, symmetric weights normalized so max(w) == 1.0.
    """
    at = abs(sll_dB)
    R0 = 10.0 ** (at / 20.0)
    M = N - 1  # Chebyshev polynomial order

    x0 = np.cosh(np.arccosh(R0) / M)

    # Sample T_M at N equispaced points on the cos circle
    k = np.arange(N, dtype=float)
    x = x0 * np.cos(np.pi * k / N)
    p = chebyshev_poly(M, x)

    if N % 2 == 1:
        # Odd N: direct FFT gives real symmetric weights
        W = np.real(np.fft.fft(p))
        n_half = (N + 1) // 2
        w = W[:n_half]
        w = np.concatenate([w[n_half - 1 : 0 : -1], w])
    else:
        # Even N: apply phase correction before FFT
        p_shifted = p * np.exp(1j * np.pi * k / N)
        W = np.real(np.fft.fft(p_shifted))
        n_half = N // 2 + 1
        w = W[:n_half]
        w = np.concatenate([w[n_half - 1 : 0 : -1], w[1:]])

    w = w / np.max(np.abs(w))
    return w


# ──────────────────────────────────────────────────────────────────────
# Array factor
# ──────────────────────────────────────────────────────────────────────

def array_factor(weights, d_lambda, theta, scan_angle_rad):
    """Compute the complex array factor at angles theta.

    Parameters
    ----------
    weights : array-like, length N
        Real amplitude weights.
    d_lambda : float
        Element spacing in wavelengths.
    theta : ndarray
        Observation angles in radians (from z-axis).
    scan_angle_rad : float
        Scan angle in radians.

    Returns
    -------
    af : ndarray (complex)
    """
    N = len(weights)
    kd = 2.0 * np.pi * d_lambda
    psi = kd * (np.cos(theta) - np.cos(scan_angle_rad))

    af = np.zeros_like(theta, dtype=complex)
    for n in range(N):
        af += weights[n] * np.exp(1j * n * psi)
    return af


# ──────────────────────────────────────────────────────────────────────
# Directivity
# ──────────────────────────────────────────────────────────────────────

def compute_directivity_dBi(weights, d_lambda, scan_angle_rad):
    """Compute directivity of the array factor pattern in dBi.

    Assumes isotropic elements, pattern independent of azimuth.
    D = 2 * |AF_max|^2 / integral_0^pi |AF(theta)|^2 sin(theta) d_theta
    """
    N_pts = 20001
    theta = np.linspace(1e-7, np.pi - 1e-7, N_pts)

    af = array_factor(weights, d_lambda, theta, scan_angle_rad)
    af_sq = np.abs(af) ** 2
    U_max = np.max(af_sq)

    integrand = af_sq * np.sin(theta)
    integral = np.trapezoid(integrand, theta)

    D = 2.0 * U_max / integral
    return 10.0 * np.log10(D)


# ──────────────────────────────────────────────────────────────────────
# Transmission line impedance transformation
# ──────────────────────────────────────────────────────────────────────

def tx_line_input_impedance(z_load, z0, length_wavelengths):
    """Input impedance through a lossless transmission line.

    Z_in = Z0 * (Z_L + j*Z0*tan(beta*L)) / (Z0 + j*Z_L*tan(beta*L))
    where beta*L = 2*pi*length_wavelengths.
    """
    beta_L = 2.0 * np.pi * length_wavelengths
    tan_bL = np.tan(beta_L)
    z_in = z0 * (z_load + 1j * z0 * tan_bL) / (z0 + 1j * z_load * tan_bL)
    return z_in


# ──────────────────────────────────────────────────────────────────────
# Reflection coefficient, VSWR, mismatch loss
# ──────────────────────────────────────────────────────────────────────

def reflection_coefficient_mag(z_in, z0):
    """Magnitude of voltage reflection coefficient."""
    gamma = (z_in - z0) / (z_in + z0)
    return abs(gamma)


def vswr(gamma_mag):
    """Voltage standing wave ratio."""
    if gamma_mag >= 1.0:
        return float("inf")
    return (1.0 + gamma_mag) / (1.0 - gamma_mag)


def mismatch_loss_dB(gamma_mag):
    """Power mismatch loss in dB (non-negative)."""
    if gamma_mag >= 1.0:
        return float("inf")
    return -10.0 * np.log10(1.0 - gamma_mag ** 2)


# ──────────────────────────────────────────────────────────────────────
# Link budget
# ──────────────────────────────────────────────────────────────────────

C_LIGHT = 299792458.0  # m/s


def free_space_path_loss_dB(freq_hz, distance_m):
    """Free-space path loss in dB."""
    return 20.0 * np.log10(4.0 * np.pi * distance_m * freq_hz / C_LIGHT)


def received_power_dBm(Pt_W, Gt_dBi, Gr_dBi, freq_hz, dist_m, ml_tx, ml_rx):
    """Received power in dBm using Friis equation."""
    Pt_dBm = 10.0 * np.log10(Pt_W * 1000.0)
    fspl = free_space_path_loss_dB(freq_hz, dist_m)
    return Pt_dBm + Gt_dBi + Gr_dBi - fspl - ml_tx - ml_rx


# ──────────────────────────────────────────────────────────────────────
# Main analysis pipeline
# ──────────────────────────────────────────────────────────────────────

def analyze(scenario):
    """Run the full link budget analysis on a scenario dict."""
    # Extract array parameters
    arr = scenario["array"]
    N = arr["num_elements"]
    d_lam = arr["element_spacing_wavelengths"]
    sll = arr["sidelobe_level_dB"]
    scan_deg = arr["scan_angle_degrees"]
    scan_rad = np.radians(scan_deg)

    freq = scenario["frequency_hz"]
    Pt = scenario["tx_power_watts"]

    tx_ZL = complex(
        scenario["tx_feed_impedance_ohms"][0],
        scenario["tx_feed_impedance_ohms"][1],
    )
    tx_Z0 = scenario["tx_line_z0_ohms"]
    tx_len = scenario["tx_line_length_wavelengths"]

    rx_gain = scenario["rx_gain_dBi"]
    rx_ZL = complex(
        scenario["rx_feed_impedance_ohms"][0],
        scenario["rx_feed_impedance_ohms"][1],
    )
    rx_Z0 = scenario["rx_line_z0_ohms"]
    rx_len = scenario["rx_line_length_wavelengths"]

    dist = scenario["link_distance_meters"]

    # 1. Dolph-Chebyshev weights
    weights = dolph_chebyshev_weights(N, sll)

    # 2. Array directivity
    dir_dBi = compute_directivity_dBi(weights, d_lam, scan_rad)

    # 3. Tx impedance matching
    tx_Zin = tx_line_input_impedance(tx_ZL, tx_Z0, tx_len)
    tx_gamma = reflection_coefficient_mag(tx_Zin, tx_Z0)
    tx_VSWR = vswr(tx_gamma)
    tx_ML = mismatch_loss_dB(tx_gamma)

    # 4. Rx impedance matching
    rx_Zin = tx_line_input_impedance(rx_ZL, rx_Z0, rx_len)
    rx_gamma = reflection_coefficient_mag(rx_Zin, rx_Z0)
    rx_VSWR = vswr(rx_gamma)
    rx_ML = mismatch_loss_dB(rx_gamma)

    # 5. Link budget
    fspl = free_space_path_loss_dB(freq, dist)
    Prx = received_power_dBm(Pt, dir_dBi, rx_gain, freq, dist, tx_ML, rx_ML)

    return {
        "weights": weights.tolist(),
        "array_directivity_dBi": float(dir_dBi),
        "tx_input_impedance_ohms": [float(tx_Zin.real), float(tx_Zin.imag)],
        "tx_reflection_coefficient_mag": float(tx_gamma),
        "tx_vswr": float(tx_VSWR),
        "tx_mismatch_loss_dB": float(tx_ML),
        "rx_input_impedance_ohms": [float(rx_Zin.real), float(rx_Zin.imag)],
        "rx_reflection_coefficient_mag": float(rx_gamma),
        "rx_vswr": float(rx_VSWR),
        "rx_mismatch_loss_dB": float(rx_ML),
        "free_space_path_loss_dB": float(fspl),
        "received_power_dBm": float(Prx),
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        scenario = json.load(f)

    results = analyze(scenario)

    with open(sys.argv[2], "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
