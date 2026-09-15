"""ETD4RK solver for the Kuramoto-Sivashinsky equation.

Implements numerically stable phi-functions and the ETD4RK exponential
time-differencing scheme for solving stiff semi-linear ODEs arising from
spectral discretization of the KS equation.
"""

import numpy as np
from math import factorial


def phi(z, k):
    """Compute phi_k(z) for k = 0, 1, 2, 3.

    phi_0(z) = exp(z)
    phi_{k+1}(z) = (phi_k(z) - 1/k!) / z

    Uses Taylor series for small |z| to avoid catastrophic cancellation,
    and the direct closed-form expression for larger |z|.

    Parameters:
        z: scalar or numpy array (real or complex)
        k: integer, 0 <= k <= 3

    Returns:
        phi_k(z), same shape and type convention as input z
    """
    z_input = np.asarray(z)
    is_scalar = z_input.ndim == 0
    is_real = np.isrealobj(z_input)

    z_arr = np.atleast_1d(z_input).astype(complex)
    result = np.empty_like(z_arr, dtype=complex)

    if k == 0:
        result = np.exp(z_arr)
    else:
        small = np.abs(z_arr) < 0.5
        large = ~small

        # Large |z|: direct formula (well-conditioned)
        if np.any(large):
            zl = z_arr[large]
            ez = np.exp(zl)
            if k == 1:
                result[large] = (ez - 1) / zl
            elif k == 2:
                result[large] = (ez - 1 - zl) / zl ** 2
            elif k == 3:
                result[large] = (ez - 1 - zl - zl ** 2 / 2) / zl ** 3

        # Small |z|: Taylor series phi_k(z) = sum_{n=0}^inf z^n / (n+k)!
        if np.any(small):
            zs = z_arr[small]
            val = np.zeros_like(zs, dtype=complex)
            term = np.ones_like(zs, dtype=complex) / factorial(k)
            for n in range(30):
                val += term
                term *= zs / (n + k + 1)
            result[small] = val

    if is_real:
        result = result.real
    if is_scalar:
        return result.flat[0]
    return result


def solve_ks(L=32 * np.pi, N=128, T=1.0, dt=0.25):
    """Solve the Kuramoto-Sivashinsky equation using ETD4RK.

    u_t + u*u_x + u_xx + u_xxxx = 0  on [0, L] with periodic BC.

    Parameters:
        L: domain length
        N: number of Fourier modes (spatial grid points)
        T: final time
        dt: time step size

    Returns:
        u(x, T) in physical space as a real numpy array of length N
    """
    from problem import setup, nonlinear

    params = setup(L, N)
    k_wave = params["k"]
    Lk = params["Lk"]
    u_hat = params["u0_hat"].astype(complex).copy()

    # Precompute ETD4RK coefficients (element-wise for diagonal L)
    z = dt * Lk
    z_half = z / 2

    E = np.exp(z)
    E_half = np.exp(z_half)

    phi1_half = phi(z_half, 1)
    phi1_full = phi(z, 1)
    phi2_full = phi(z, 2)
    phi3_full = phi(z, 3)

    # Stage coefficient: (h/2) * phi_1(hL/2)
    Q = (dt / 2) * phi1_half

    # Update coefficients
    c1 = dt * (phi1_full - 3 * phi2_full + 4 * phi3_full)
    c2 = dt * (phi2_full - 2 * phi3_full)
    c3 = dt * (-phi2_full + 4 * phi3_full)

    n_steps = int(round(T / dt))
    for _ in range(n_steps):
        Nn = nonlinear(u_hat, k_wave)

        a = E_half * u_hat + Q * Nn
        Na = nonlinear(a, k_wave)

        b = E_half * u_hat + Q * Na
        Nb = nonlinear(b, k_wave)

        c = E_half * a + Q * (2 * Nb - Nn)
        Nc = nonlinear(c, k_wave)

        u_hat = E * u_hat + c1 * Nn + 2 * c2 * (Na + Nb) + c3 * Nc

    return np.fft.ifft(u_hat).real
