#!/usr/bin/env python3
"""Reference beamformer implementation."""

import math
import sys

import numpy as np

sys.path.insert(0, "/app")
from lib.txline import (
    input_impedance,
    reflection_coeff_mag,
    vswr,
    mismatch_loss_db,
    fspl_db,
)


class Beamformer:

    def analyze(self, scenario, s_data, coupling):
        arr = scenario["array"]
        N = arr["num_elements"]
        d_lam = arr["element_spacing_wavelengths"]
        sll = arr["sidelobe_level_dB"]
        scan_deg = arr["scan_angle_degrees"]
        scan_rad = np.radians(scan_deg)
        freq = scenario["frequency_hz"]

        # 1. Dolph-Chebyshev ideal weights
        w_ideal = self._dolph_chebyshev(N, sll)

        # 2. Coupling correction: w_applied = C^{-1} @ w_ideal
        C = np.array(coupling, dtype=complex)
        w_complex = np.linalg.solve(C, w_ideal)
        w_coupled_mags = np.abs(w_complex)
        w_coupled_mags = w_coupled_mags / np.max(w_coupled_mags)

        # 3. Directivities
        dir_ideal = self._directivity_dBi(w_ideal, d_lam, scan_rad)
        dir_coupled = self._directivity_dBi(w_complex, d_lam, scan_rad)

        # 4. TX element impedance from S-parameter data
        z_elem = self._s11_to_impedance(s_data, freq)

        # 5. TX impedance matching (convert wavelengths -> degrees for txline)
        tx_z0 = scenario["tx_line_z0_ohms"]
        tx_len_deg = scenario["tx_line_length_wavelengths"] * 360.0
        tx_zin = input_impedance(z_elem, tx_z0, tx_len_deg)
        tx_gamma = reflection_coeff_mag(tx_zin, tx_z0)
        tx_v = vswr(tx_gamma)
        tx_ml = mismatch_loss_db(tx_gamma)

        # 6. RX impedance matching
        rx_zl = complex(
            scenario["rx_load_impedance_ohms"][0],
            scenario["rx_load_impedance_ohms"][1],
        )
        rx_z0 = scenario["rx_line_z0_ohms"]
        rx_len_deg = scenario["rx_line_length_wavelengths"] * 360.0
        rx_zin = input_impedance(rx_zl, rx_z0, rx_len_deg)
        rx_gamma = reflection_coeff_mag(rx_zin, rx_z0)
        rx_v = vswr(rx_gamma)
        rx_ml = mismatch_loss_db(rx_gamma)

        # 7. Link budget
        dist = scenario["link_distance_meters"]
        fspl = fspl_db(freq, dist)
        Pt_dBm = 10.0 * np.log10(scenario["tx_power_watts"] * 1000.0)
        Gr = scenario["rx_gain_dBi"]
        Prx = Pt_dBm + dir_coupled + Gr - fspl - tx_ml - rx_ml

        return {
            "ideal_weights": w_ideal.tolist(),
            "coupled_weights": w_coupled_mags.tolist(),
            "array_directivity_dBi": float(dir_ideal),
            "coupled_directivity_dBi": float(dir_coupled),
            "tx_element_impedance_ohms": [
                float(z_elem.real),
                float(z_elem.imag),
            ],
            "tx_input_impedance_ohms": [
                float(tx_zin.real),
                float(tx_zin.imag),
            ],
            "tx_reflection_coefficient_mag": float(tx_gamma),
            "tx_vswr": float(tx_v),
            "tx_mismatch_loss_dB": float(tx_ml),
            "rx_input_impedance_ohms": [
                float(rx_zin.real),
                float(rx_zin.imag),
            ],
            "rx_reflection_coefficient_mag": float(rx_gamma),
            "rx_vswr": float(rx_v),
            "rx_mismatch_loss_dB": float(rx_ml),
            "free_space_path_loss_dB": float(fspl),
            "received_power_dBm": float(Prx),
        }

    # ------------------------------------------------------------------
    # Chebyshev polynomial evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _cheby_poly(n, x):
        """Evaluate Chebyshev polynomial T_n(x)."""
        x = np.atleast_1d(np.asarray(x, dtype=float))
        result = np.zeros_like(x)

        mask_in = np.abs(x) <= 1.0
        if np.any(mask_in):
            result[mask_in] = np.cos(
                n * np.arccos(np.clip(x[mask_in], -1.0, 1.0))
            )

        mask_pos = x > 1.0
        if np.any(mask_pos):
            result[mask_pos] = np.cosh(n * np.arccosh(x[mask_pos]))

        mask_neg = x < -1.0
        if np.any(mask_neg):
            result[mask_neg] = ((-1) ** n) * np.cosh(
                n * np.arccosh(-x[mask_neg])
            )

        return result

    # ------------------------------------------------------------------
    # Dolph-Chebyshev weights via DFT method
    # ------------------------------------------------------------------

    def _dolph_chebyshev(self, N, sll_dB):
        at = abs(sll_dB)
        R0 = 10.0 ** (at / 20.0)
        M = N - 1

        x0 = np.cosh(np.arccosh(R0) / M)

        k = np.arange(N, dtype=float)
        x = x0 * np.cos(np.pi * k / N)
        p = self._cheby_poly(M, x)

        if N % 2 == 1:
            W = np.real(np.fft.fft(p))
            n_half = (N + 1) // 2
            w = W[:n_half]
            w = np.concatenate([w[n_half - 1 : 0 : -1], w])
        else:
            p_shifted = p * np.exp(1j * np.pi * k / N)
            W = np.real(np.fft.fft(p_shifted))
            n_half = N // 2 + 1
            w = W[:n_half]
            w = np.concatenate([w[n_half - 1 : 0 : -1], w[1:]])

        w = w / np.max(np.abs(w))
        return w

    # ------------------------------------------------------------------
    # Directivity via numerical integration
    # ------------------------------------------------------------------

    def _directivity_dBi(self, weights, d_lambda, scan_rad, n_pts=20001):
        theta = np.linspace(1e-7, np.pi - 1e-7, n_pts)
        kd = 2.0 * np.pi * d_lambda
        psi = kd * (np.cos(theta) - np.cos(scan_rad))

        af = np.zeros_like(theta, dtype=complex)
        for n in range(len(weights)):
            af += weights[n] * np.exp(1j * n * psi)

        af_sq = np.abs(af) ** 2
        U_max = np.max(af_sq)
        integrand = af_sq * np.sin(theta)
        integral = np.trapezoid(integrand, theta)
        D = 2.0 * U_max / integral
        return 10.0 * np.log10(D)

    # ------------------------------------------------------------------
    # S-parameter to impedance conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _s11_to_impedance(s_data, freq):
        z0 = s_data["z0"]
        freqs = np.array(s_data["frequencies"])
        s11_r = np.array([s.real for s in s_data["s11"]])
        s11_i = np.array([s.imag for s in s_data["s11"]])
        sr = float(np.interp(freq, freqs, s11_r))
        si = float(np.interp(freq, freqs, s11_i))
        s11 = complex(sr, si)
        return z0 * (1 + s11) / (1 - s11)
