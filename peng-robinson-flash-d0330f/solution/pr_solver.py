
"""
Peng-Robinson Equation of State with multicomponent TP flash.

Reference implementation for this task.
"""

import math
import numpy as np
from scipy.optimize import brentq

R_GAS = 8.314462618153241  # J/(mol*K)


class PengRobinson:
    """Peng-Robinson cubic equation of state for multicomponent mixtures."""

    def __init__(self, Tc, Pc, omega, kij=None):
        self.nc = len(Tc)
        self.Tc = np.array(Tc, dtype=float)
        self.Pc = np.array(Pc, dtype=float)
        self.omega = np.array(omega, dtype=float)
        if kij is None:
            self.kij = np.zeros((self.nc, self.nc))
        else:
            self.kij = np.array(kij, dtype=float)

        # PR constants
        self.bi = 0.07780 * R_GAS * self.Tc / self.Pc
        self.aci = 0.45724 * R_GAS**2 * self.Tc**2 / self.Pc
        self.kappai = (0.37464
                       + 1.54226 * self.omega
                       - 0.26992 * self.omega**2)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _alpha(self, T):
        return (1.0 + self.kappai * (1.0 - np.sqrt(T / self.Tc)))**2

    def _ai(self, T):
        return self.aci * self._alpha(T)

    def _mix_ab(self, T, x):
        """Return (a_mix, b_mix, ai_array, aij_matrix) for mole fractions x."""
        ai = self._ai(T)
        sqrt_ai = np.sqrt(ai)
        aij = np.outer(sqrt_ai, sqrt_ai) * (1.0 - self.kij)
        a_mix = float(x @ aij @ x)
        b_mix = float(x @ self.bi)
        return a_mix, b_mix, ai, aij

    def _solve_cubic_Z(self, A, B):
        """Solve the PR cubic in compressibility factor Z.

        Z^3 - (1-B)*Z^2 + (A - 3B^2 - 2B)*Z - (AB - B^2 - B^3) = 0

        Returns sorted list of real roots > B.
        """
        c2 = -(1.0 - B)
        c1 = A - 3.0 * B * B - 2.0 * B
        c0 = -(A * B - B * B - B * B * B)
        roots = np.roots([1.0, c2, c1, c0])
        real_roots = []
        for r in roots:
            if abs(r.imag) < 1e-10 and r.real > B:
                real_roots.append(float(r.real))
        return sorted(real_roots)

    def _select_Z(self, real_roots, phase):
        if not real_roots:
            raise ValueError("No valid compressibility factor root found")
        if len(real_roots) == 1:
            return real_roots[0]
        if phase in ('vapor', 'v', 'gas', 'g'):
            return max(real_roots)
        elif phase in ('liquid', 'l'):
            return min(real_roots)
        return max(real_roots)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def pressure(self, V, T, z):
        """Pressure [Pa] from total volume V [m3], temperature T [K], moles z."""
        z = np.asarray(z, dtype=float)
        n = float(np.sum(z))
        x = z / n
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        nb = n * b_mix
        P = (n * R_GAS * T / (V - nb)
             - n * n * a_mix / (V * (V + nb) + nb * (V - nb)))
        return float(P)

    def volume(self, p, T, z, phase='vapor'):
        """Total volume [m3] from pressure p [Pa], temperature T [K], moles z."""
        z = np.asarray(z, dtype=float)
        n = float(np.sum(z))
        x = z / n
        a_mix, b_mix, _, _ = self._mix_ab(T, x)

        RT = R_GAS * T
        A = a_mix * p / (RT * RT)
        B = b_mix * p / RT

        real_roots = self._solve_cubic_Z(A, B)
        Z = self._select_Z(real_roots, phase)
        return float(Z * n * RT / p)

    def fugacity_coefficients(self, p, T, z, phase='vapor'):
        """Fugacity coefficients for each component."""
        z = np.asarray(z, dtype=float)
        n = float(np.sum(z))
        x = z / n
        a_mix, b_mix, ai, aij = self._mix_ab(T, x)

        RT = R_GAS * T
        A = a_mix * p / (RT * RT)
        B = b_mix * p / RT

        real_roots = self._solve_cubic_Z(A, B)
        Z = self._select_Z(real_roots, phase)

        sqrt2 = math.sqrt(2.0)
        arg_hi = Z + (1.0 + sqrt2) * B
        arg_lo = Z + (1.0 - sqrt2) * B
        if arg_hi <= 0 or arg_lo <= 0:
            # Fallback: return ones (ideal-like)
            return [1.0] * self.nc
        ln_ratio = math.log(arg_hi / arg_lo)

        ln_phi = np.zeros(self.nc)
        for i in range(self.nc):
            sum_xj_aij = float(np.sum(x * aij[i, :]))
            bi_bm = self.bi[i] / b_mix
            ln_phi[i] = (bi_bm * (Z - 1.0)
                         - math.log(max(Z - B, 1e-300))
                         - A / (2.0 * sqrt2 * B)
                         * (2.0 * sum_xj_aij / a_mix - bi_bm)
                         * ln_ratio)

        return np.exp(ln_phi).tolist()

    def tp_flash(self, p, T, z):
        """Isothermal-isobaric flash.

        Returns {'beta': float, 'x': list, 'y': list} or None.
        """
        z = np.asarray(z, dtype=float)
        n = float(np.sum(z))
        zf = z / n  # feed mole fractions
        nc = self.nc

        # Wilson K-value initialisation
        K = (self.Pc / p) * np.exp(
            5.37 * (1.0 + self.omega) * (1.0 - self.Tc / T))

        # Rachford-Rice feasibility check
        g0 = float(np.sum(zf * (K - 1.0)))
        g1 = float(np.sum(zf * (1.0 - 1.0 / K)))
        if g0 <= 0:
            return None  # subcooled liquid
        if g1 >= 0:
            return None  # superheated vapour

        def rr_func(beta, K_vals):
            return float(np.sum(
                zf * (K_vals - 1.0) / (1.0 + beta * (K_vals - 1.0))))

        max_iter = 300
        tol = 1e-12

        for it in range(max_iter):
            # Solve Rachford-Rice for beta
            try:
                beta = brentq(lambda b: rr_func(b, K), 0.0, 1.0,
                              xtol=1e-14, maxiter=200)
            except ValueError:
                return None

            # Compute phase compositions
            denom = 1.0 + beta * (K - 1.0)
            x_liq = zf / denom
            x_liq = x_liq / np.sum(x_liq)
            y_vap = K * x_liq
            y_vap = y_vap / np.sum(y_vap)

            # Fugacity coefficients
            try:
                phi_l = np.array(self.fugacity_coefficients(
                    p, T, x_liq.tolist(), phase='liquid'))
                phi_v = np.array(self.fugacity_coefficients(
                    p, T, y_vap.tolist(), phase='vapor'))
            except ValueError:
                return None

            K_new = phi_l / np.maximum(phi_v, 1e-300)

            # Convergence
            dK = float(np.max(np.abs(np.log(K_new / K))))
            K = K_new

            if dK < tol:
                break

            # Recheck feasibility
            g0 = float(np.sum(zf * (K - 1.0)))
            g1 = float(np.sum(zf * (1.0 - 1.0 / K)))
            if g0 <= 0 or g1 >= 0:
                return None

        # Final compositions
        try:
            beta = brentq(lambda b: rr_func(b, K), 0.0, 1.0,
                          xtol=1e-14, maxiter=200)
        except ValueError:
            return None

        denom = 1.0 + beta * (K - 1.0)
        x_liq = zf / denom
        x_liq = x_liq / np.sum(x_liq)
        y_vap = K * x_liq
        y_vap = y_vap / np.sum(y_vap)

        return {
            'beta': float(beta),
            'x': x_liq.tolist(),
            'y': y_vap.tolist(),
        }

    def bubble_pressure(self, T, z):
        """Bubble-point pressure [Pa] for liquid composition z (mole fracs)."""
        z = np.asarray(z, dtype=float)
        x = z / np.sum(z)

        # Wilson estimate
        K_w = (self.Pc) * np.exp(
            5.37 * (1.0 + self.omega) * (1.0 - self.Tc / T))
        P = float(np.sum(x * K_w))

        y = x.copy()

        for _ in range(500):
            try:
                phi_l = np.array(self.fugacity_coefficients(
                    P, T, x.tolist(), phase='liquid'))
                phi_v = np.array(self.fugacity_coefficients(
                    P, T, y.tolist(), phase='vapor'))
            except ValueError:
                P *= 0.9
                continue

            K = phi_l / np.maximum(phi_v, 1e-300)
            y_new = K * x
            sum_y = float(np.sum(y_new))

            if abs(sum_y - 1.0) < 1e-10:
                return float(P)

            P *= sum_y
            if P < 1.0:
                P = 1.0
            y = y_new / sum_y

        return float(P)

    def dew_pressure(self, T, z):
        """Dew-point pressure [Pa] for vapour composition z (mole fracs)."""
        z = np.asarray(z, dtype=float)
        y = z / np.sum(z)

        # Wilson estimate
        K_w = (self.Pc) * np.exp(
            5.37 * (1.0 + self.omega) * (1.0 - self.Tc / T))
        P = float(1.0 / np.sum(y / K_w))

        x = y.copy()

        for _ in range(500):
            try:
                phi_v = np.array(self.fugacity_coefficients(
                    P, T, y.tolist(), phase='vapor'))
                phi_l = np.array(self.fugacity_coefficients(
                    P, T, x.tolist(), phase='liquid'))
            except ValueError:
                P *= 1.1
                continue

            K = phi_l / np.maximum(phi_v, 1e-300)
            x_new = y / np.maximum(K, 1e-300)
            sum_x = float(np.sum(x_new))

            if abs(sum_x - 1.0) < 1e-10:
                return float(P)

            P /= sum_x
            if P < 1.0:
                P = 1.0
            x = x_new / sum_x

        return float(P)
