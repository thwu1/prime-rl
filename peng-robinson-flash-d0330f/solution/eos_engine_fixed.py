
"""
Cubic Equation of State engine — Peng-Robinson and Soave-Redlich-Kwong.
Reference solution with all bugs fixed and extensions implemented.
"""

import ctypes
import math
import os
import tomllib

R_GAS = 8.314462618153241  # J/(mol*K)

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libcubic.so")
_lib = ctypes.CDLL(_LIB_PATH)

_lib.eos_pressure.restype = ctypes.c_double
_lib.eos_pressure.argtypes = [ctypes.c_double] * 8

_lib.eos_solve_Z.restype = ctypes.c_int
_lib.eos_solve_Z.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ctypes.POINTER(ctypes.c_double),
]


def load_params(filepath):
    """Parse a TOML parameter file and return (names, Tc, Pc, omega, kij)."""
    with open(filepath, "rb") as f:
        data = tomllib.load(f)
    species = data["species"]
    names = list(species.keys())
    nc = len(names)
    Tc = [species[n]["Tc"] for n in names]
    Pc = [species[n]["Pc"] for n in names]
    omega = [species[n]["omega"] for n in names]
    kij = [[0.0] * nc for _ in range(nc)]
    for entry in data.get("interactions", []):
        s1, s2, val = entry["species1"], entry["species2"], entry["kij"]
        if s1 in names and s2 in names:
            i, j = names.index(s1), names.index(s2)
            kij[i][j] = val
            kij[j][i] = val
    return names, Tc, Pc, omega, kij


class _CubicEOS:
    """Abstract base for two-parameter cubic equations of state."""

    _Omega_a = None
    _Omega_b = None
    _delta1 = None
    _delta2 = None

    def __init__(self, Tc, Pc, omega, kij=None):
        self.nc = len(Tc)
        self.Tc = list(Tc)
        self.Pc = list(Pc)
        self.omega = list(omega)
        if kij is None:
            self.kij = [[0.0] * self.nc for _ in range(self.nc)]
        else:
            self.kij = [list(row) for row in kij]
        self.bi = [self._Omega_b * R_GAS * Tc[i] / Pc[i]
                    for i in range(self.nc)]
        self.aci = [self._Omega_a * R_GAS ** 2 * Tc[i] ** 2 / Pc[i]
                     for i in range(self.nc)]
        self.kappai = [self._kappa(omega[i]) for i in range(self.nc)]

    @staticmethod
    def _kappa(omega):
        raise NotImplementedError

    def _alpha(self, T):
        return [(1.0 + self.kappai[i] * (1.0 - math.sqrt(T / self.Tc[i]))) ** 2
                for i in range(self.nc)]

    def _dalpha_dT(self, T):
        out = []
        for i in range(self.nc):
            sqrtTr = math.sqrt(T / self.Tc[i])
            out.append(
                -(1.0 + self.kappai[i] * (1.0 - sqrtTr))
                * self.kappai[i] / math.sqrt(T * self.Tc[i]))
        return out

    def _mix_ab(self, T, x):
        alpha = self._alpha(T)
        ai = [self.aci[i] * alpha[i] for i in range(self.nc)]
        b_mix = sum(x[i] * self.bi[i] for i in range(self.nc))
        nc = self.nc
        aij = [[0.0] * nc for _ in range(nc)]
        a_mix = 0.0
        for i in range(nc):
            for j in range(nc):
                aij[i][j] = math.sqrt(ai[i] * ai[j]) * (1.0 - self.kij[i][j])
                a_mix += x[i] * x[j] * aij[i][j]
        return a_mix, b_mix, ai, aij

    def _da_mix_dT(self, T, x):
        alpha = self._alpha(T)
        dalpha = self._dalpha_dT(T)
        ai = [self.aci[i] * alpha[i] for i in range(self.nc)]
        dai = [self.aci[i] * dalpha[i] for i in range(self.nc)]
        nc = self.nc
        da_mix = 0.0
        for i in range(nc):
            for j in range(nc):
                sqrt_aiaj = math.sqrt(ai[i] * ai[j])
                if sqrt_aiaj > 0:
                    d_sqrt = (dai[i] * ai[j] + ai[i] * dai[j]) / (2.0 * sqrt_aiaj)
                else:
                    d_sqrt = 0.0
                da_mix += x[i] * x[j] * d_sqrt * (1.0 - self.kij[i][j])
        return da_mix

    def _solve_cubic_Z(self, A, B):
        roots = (ctypes.c_double * 3)()
        nroots = _lib.eos_solve_Z(A, B, self._delta1, self._delta2, roots)
        return sorted(roots[i] for i in range(nroots))

    def _select_Z(self, real_roots, phase):
        if not real_roots:
            raise ValueError("No valid Z root")
        if len(real_roots) == 1:
            return real_roots[0]
        if phase in ('liquid', 'l'):
            return min(real_roots)
        return max(real_roots)

    def pressure(self, V, T, z):
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        return _lib.eos_pressure(V, T, n, a_mix, b_mix,
                                 self._delta1, self._delta2, R_GAS)

    def volume(self, p, T, z, phase='vapor'):
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        RT = R_GAS * T
        A = a_mix * p / (RT * RT)
        B = b_mix * p / RT
        real_roots = self._solve_cubic_Z(A, B)
        Z = self._select_Z(real_roots, phase)
        return Z * n * RT / p

    def a_res(self, V, T, z):
        """Dimensionless residual Helmholtz energy A_res / (n R T)."""
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        nb = n * b_mix
        d1, d2 = self._delta1, self._delta2
        dd = d1 - d2
        term1 = -math.log(1.0 - nb / V)
        if abs(dd) < 1e-30:
            term2 = -a_mix / (b_mix * R_GAS * T) * nb / (V + nb * d1)
        else:
            term2 = (-a_mix / (dd * b_mix * R_GAS * T)
                     * math.log((V + nb * d1) / (V + nb * d2)))
        return term1 + term2

    def fugacity_coefficients(self, p, T, z, phase='vapor'):
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, ai, aij = self._mix_ab(T, x)
        RT = R_GAS * T
        A = a_mix * p / (RT * RT)
        B = b_mix * p / RT
        real_roots = self._solve_cubic_Z(A, B)
        Z = self._select_Z(real_roots, phase)

        d1, d2 = self._delta1, self._delta2
        dd = d1 - d2

        arg1 = Z + d1 * B
        arg2 = Z + d2 * B
        if arg1 <= 0 or arg2 <= 0:
            return [1.0] * self.nc
        if abs(dd) < 1e-30:
            ln_ratio = B / arg1
        else:
            ln_ratio = math.log(arg1 / arg2)

        phi = []
        for i in range(self.nc):
            sum_xj_aij = sum(x[j] * aij[i][j] for j in range(self.nc))
            bi_bm = self.bi[i] / b_mix
            two_sum_over_a = 2.0 * sum_xj_aij / a_mix
            if abs(dd) < 1e-30:
                coeff = A / B
            else:
                coeff = A / (dd * B)
            lnphi = (bi_bm * (Z - 1.0)
                     - math.log(max(Z - B, 1e-300))
                     - coeff * (two_sum_over_a - bi_bm) * ln_ratio)
            phi.append(math.exp(lnphi))
        return phi

    def enthalpy_departure(self, p, T, z, phase='vapor'):
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        da_dT = self._da_mix_dT(T, x)
        V = self.volume(p, T, z, phase)
        Z = p * V / (n * R_GAS * T)
        nb = n * b_mix
        d1, d2 = self._delta1, self._delta2
        dd = d1 - d2
        if abs(dd) < 1e-30:
            log_part = nb / (V + nb * d1)
        else:
            log_part = math.log((V + nb * d1) / (V + nb * d2))
        if abs(dd) > 1e-30:
            H_dep = (R_GAS * T * (Z - 1.0)
                     + (T * da_dT - a_mix) / (dd * b_mix) * log_part)
        else:
            H_dep = (R_GAS * T * (Z - 1.0)
                     + (T * da_dT - a_mix) / b_mix * log_part)
        return H_dep

    def entropy_departure(self, p, T, z, phase='vapor'):
        n = sum(z)
        x = [zi / n for zi in z]
        a_mix, b_mix, _, _ = self._mix_ab(T, x)
        da_dT = self._da_mix_dT(T, x)
        V = self.volume(p, T, z, phase)
        Z = p * V / (n * R_GAS * T)
        B = b_mix * p / (R_GAS * T)
        nb = n * b_mix
        d1, d2 = self._delta1, self._delta2
        dd = d1 - d2
        if abs(dd) < 1e-30:
            log_part = nb / (V + nb * d1)
        else:
            log_part = math.log((V + nb * d1) / (V + nb * d2))
        if abs(dd) < 1e-30:
            S_dep = R_GAS * math.log(max(Z - B, 1e-300)) + da_dT / b_mix * log_part
        else:
            S_dep = (R_GAS * math.log(max(Z - B, 1e-300))
                     + da_dT / (dd * b_mix) * log_part)
        return S_dep

    def _solve_rr(self, K, zf):
        Kmin, Kmax = min(K), max(K)
        if Kmax <= 1.0:
            return -1.0
        if Kmin >= 1.0:
            return 2.0
        bmin = max(0.0, 1.0 / (1.0 - Kmax))
        bmax = min(1.0, 1.0 / (1.0 - Kmin))
        beta = 0.5 * (bmin + bmax)
        nc = len(zf)
        for _ in range(200):
            f = sum(zf[i] * (K[i] - 1.0) / (1.0 + beta * (K[i] - 1.0))
                    for i in range(nc))
            df = -sum(zf[i] * (K[i] - 1.0) ** 2
                      / (1.0 + beta * (K[i] - 1.0)) ** 2
                      for i in range(nc))
            if abs(df) < 1e-30:
                break
            db = -f / df
            bn = beta + db
            if bn < bmin or bn > bmax:
                if f > 0:
                    bmin = beta
                else:
                    bmax = beta
                beta = 0.5 * (bmin + bmax)
            else:
                if f > 0:
                    bmin = beta
                else:
                    bmax = beta
                beta = bn
            if abs(db) < 1e-14:
                break
        return beta

    def tp_flash(self, p, T, z):
        n = sum(z)
        zf = [zi / n for zi in z]
        nc = self.nc
        K = [(self.Pc[i] / p)
             * math.exp(5.37 * (1.0 + self.omega[i])
                        * (1.0 - self.Tc[i] / T))
             for i in range(nc)]
        g0 = sum(zf[i] * (K[i] - 1.0) for i in range(nc))
        g1 = sum(zf[i] * (1.0 - 1.0 / K[i]) for i in range(nc))
        if g0 <= 0 or g1 >= 0:
            return None
        for _ in range(300):
            beta = self._solve_rr(K, zf)
            if beta < -1e-6 or beta > 1.0 + 1e-6:
                return None
            beta = max(0.0, min(1.0, beta))
            xl = [zf[i] / (1.0 + beta * (K[i] - 1.0)) for i in range(nc)]
            sx = sum(xl)
            xl = [v / sx for v in xl]
            yv = [K[i] * xl[i] for i in range(nc)]
            sy = sum(yv)
            yv = [v / sy for v in yv]
            phi_l = self.fugacity_coefficients(p, T, xl, 'liquid')
            phi_v = self.fugacity_coefficients(p, T, yv, 'vapor')
            K_new = [phi_l[i] / max(phi_v[i], 1e-300) for i in range(nc)]
            err = max(abs(math.log(K_new[i] / K[i])) for i in range(nc))
            K = K_new
            if err < 1e-12:
                break
            g0 = sum(zf[i] * (K[i] - 1.0) for i in range(nc))
            g1 = sum(zf[i] * (1.0 - 1.0 / K[i]) for i in range(nc))
            if g0 <= 0 or g1 >= 0:
                return None
        beta = self._solve_rr(K, zf)
        if beta < -1e-6 or beta > 1.0 + 1e-6:
            return None
        beta = max(0.0, min(1.0, beta))
        xl = [zf[i] / (1.0 + beta * (K[i] - 1.0)) for i in range(nc)]
        sx = sum(xl)
        xl = [v / sx for v in xl]
        yv = [K[i] * xl[i] for i in range(nc)]
        sy = sum(yv)
        yv = [v / sy for v in yv]
        return {'beta': beta, 'x': xl, 'y': yv}

    def bubble_pressure(self, T, z):
        x = list(z)
        sx = sum(x)
        x = [v / sx for v in x]
        nc = self.nc
        K_w = [self.Pc[i]
               * math.exp(5.37 * (1.0 + self.omega[i])
                          * (1.0 - self.Tc[i] / T))
               for i in range(nc)]
        P = sum(x[i] * K_w[i] for i in range(nc))
        y = list(x)
        for _ in range(500):
            phi_l = self.fugacity_coefficients(P, T, x, 'liquid')
            phi_v = self.fugacity_coefficients(P, T, y, 'vapor')
            K = [phi_l[i] / max(phi_v[i], 1e-300) for i in range(nc)]
            y_new = [K[i] * x[i] for i in range(nc)]
            sy = sum(y_new)
            if abs(sy - 1.0) < 1e-10:
                return P
            P *= sy
            if P < 1.0:
                P = 1.0
            y = [v / sy for v in y_new]
        return P

    def dew_pressure(self, T, z):
        y = list(z)
        sy = sum(y)
        y = [v / sy for v in y]
        nc = self.nc
        K_w = [self.Pc[i]
               * math.exp(5.37 * (1.0 + self.omega[i])
                          * (1.0 - self.Tc[i] / T))
               for i in range(nc)]
        P = 1.0 / sum(y[i] / K_w[i] for i in range(nc))
        x = list(y)
        for _ in range(500):
            phi_v = self.fugacity_coefficients(P, T, y, 'vapor')
            phi_l = self.fugacity_coefficients(P, T, x, 'liquid')
            K = [phi_l[i] / max(phi_v[i], 1e-300) for i in range(nc)]
            x_new = [y[i] / max(K[i], 1e-300) for i in range(nc)]
            sx = sum(x_new)
            if abs(sx - 1.0) < 1e-10:
                return P
            P /= sx
            if P < 1.0:
                P = 1.0
            x = [v / sx for v in x_new]
        return P


class PengRobinson(_CubicEOS):
    _Omega_a = 0.45724
    _Omega_b = 0.07780
    _delta1 = 1.0 + math.sqrt(2.0)
    _delta2 = 1.0 - math.sqrt(2.0)

    @staticmethod
    def _kappa(omega):
        return 0.37464 + 1.54226 * omega - 0.26992 * omega ** 2


class SRK(_CubicEOS):
    _Omega_a = 0.42748
    _Omega_b = 0.08664
    _delta1 = 1.0
    _delta2 = 0.0

    @staticmethod
    def _kappa(omega):
        return 0.480 + 1.574 * omega - 0.176 * omega ** 2
