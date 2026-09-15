
"""
Multilayer thin-film optics simulator — draft implementation.
"""

from __future__ import division, print_function, absolute_import

import numpy as np
from numpy import cos, sin, inf, zeros, array, exp, conj, pi
import sys

EPSILON = sys.float_info.epsilon


def _make_2x2(a, b, c, d):
    """Construct a 2x2 complex matrix."""
    m = np.empty((2, 2), dtype=complex)
    m[0, 0] = a
    m[0, 1] = b
    m[1, 0] = c
    m[1, 1] = d
    return m


def is_forward_angle(n, theta):
    """Determine if theta corresponds to a forward-traveling wave in medium n."""
    ncostheta = n * cos(theta)
    if abs(ncostheta.imag) > 100 * EPSILON:
        return bool(ncostheta.imag > 0)
    else:
        return bool(ncostheta.real > 0)


def snell(n_1, n_2, th_1):
    """Snell's law: return propagation angle in medium n_2."""
    th_2_guess = np.arcsin(n_1 * np.sin(th_1) / n_2)
    if is_forward_angle(n_2, th_2_guess):
        return th_2_guess
    else:
        return pi - th_2_guess


def list_snell(n_list, th_0):
    """Apply Snell's law across all layers."""
    angles = np.arcsin(n_list[0] * np.sin(th_0) / n_list)
    if not is_forward_angle(n_list[0], angles[0]):
        angles[0] = pi - angles[0]
    if not is_forward_angle(n_list[-1], angles[-1]):
        angles[-1] = pi - angles[-1]
    return angles


def interface_r(pol, n_i, n_f, th_i, th_f):
    """Fresnel reflection amplitude at a single interface."""
    if pol == 's':
        return ((n_i * cos(th_i) - n_f * cos(th_f)) /
                (n_i * cos(th_i) + n_f * cos(th_f)))
    else:
        return ((n_f * cos(th_i) - n_i * cos(th_f)) /
                (n_f * cos(th_i) + n_i * cos(th_f)))


def interface_t(pol, n_i, n_f, th_i, th_f):
    """Fresnel transmission amplitude at a single interface."""
    if pol == 's':
        return 2 * n_i * cos(th_i) / (n_i * cos(th_i) + n_f * cos(th_f))
    else:
        return 2 * n_i * cos(th_i) / (n_f * cos(th_i) + n_i * cos(th_f))


def R_from_r(r):
    """Reflected power from reflection amplitude."""
    return abs(r) ** 2


def T_from_t(pol, t, n_i, n_f, th_i, th_f):
    """Transmitted power from transmission amplitude."""
    return abs(t ** 2) * ((n_f * cos(th_f)).real / (n_i * cos(th_i)).real)


def power_entering_from_r(pol, r, n_i, th_i):
    """Power entering the first layer from the reflection amplitude."""
    return 1 - abs(r) ** 2


def coh_tmm(pol, n_list, d_list, th_0, lam_vac):
    """Main coherent calculation for a multilayer planar stack.

    Returns dict with r, t, R, T, power_entering, vw_list, kz_list, th_list,
    plus the input parameters.
    """
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)
    num_layers = n_list.size

    th_list = list_snell(n_list, th_0)
    kz_list = 2 * pi * n_list * cos(th_list) / lam_vac

    olderr = np.seterr(invalid='ignore')
    delta = kz_list * d_list
    np.seterr(**olderr)

    # Interface coefficients
    t_list = zeros((num_layers, num_layers), dtype=complex)
    r_list = zeros((num_layers, num_layers), dtype=complex)
    for i in range(num_layers - 1):
        t_list[i, i + 1] = interface_t(pol, n_list[i], n_list[i + 1],
                                       th_list[i], th_list[i + 1])
        r_list[i, i + 1] = interface_r(pol, n_list[i], n_list[i + 1],
                                       th_list[i], th_list[i + 1])

    # Per-layer transfer matrices
    M_list = zeros((num_layers, 2, 2), dtype=complex)
    for i in range(1, num_layers - 1):
        M_list[i] = (1 / t_list[i, i + 1]) * np.dot(
            _make_2x2(exp(-1j * delta[i]), 0, 0, exp(1j * delta[i])),
            _make_2x2(1, r_list[i, i + 1], r_list[i, i + 1], 1))

    # Overall transfer matrix
    Mtilde = _make_2x2(1, 0, 0, 1)
    for i in range(1, num_layers - 1):
        Mtilde = np.dot(Mtilde, M_list[i])
    Mtilde = np.dot(
        _make_2x2(1, r_list[0, 1], r_list[0, 1], 1) / t_list[0, 1],
        Mtilde)

    r = Mtilde[1, 0] / Mtilde[0, 0]
    t = 1 / Mtilde[0, 0]

    # Forward/backward wave amplitudes in each layer
    vw_list = zeros((num_layers, 2), dtype=complex)
    vw = array([[t], [0]])
    vw_list[-1, :] = np.transpose(vw)
    for i in range(num_layers - 2, 0, -1):
        vw = np.dot(M_list[i], vw)
        vw_list[i, :] = np.transpose(vw)

    R = R_from_r(r)
    T = T_from_t(pol, t, n_list[0], n_list[-1], th_0, th_list[-1])
    pe = power_entering_from_r(pol, r, n_list[0], th_0)

    return {'r': r, 't': t, 'R': R, 'T': T, 'power_entering': pe,
            'vw_list': vw_list, 'kz_list': kz_list, 'th_list': th_list,
            'pol': pol, 'n_list': n_list, 'd_list': d_list, 'th_0': th_0,
            'lam_vac': lam_vac}


def ellips(n_list, d_list, th_0, lam_vac):
    """Ellipsometric parameters psi and Delta."""
    s_data = coh_tmm('s', n_list, d_list, th_0, lam_vac)
    p_data = coh_tmm('p', n_list, d_list, th_0, lam_vac)
    rs = s_data['r']
    rp = p_data['r']
    return {'psi': np.arctan(abs(rp / rs)), 'Delta': np.angle(-rp / rs)}


def position_resolved(layer, distance, coh_tmm_data):
    """Poynting vector and absorption at a depth within a given layer."""
    if layer > 0:
        v, w = coh_tmm_data['vw_list'][layer]
    else:
        v = 1
        w = coh_tmm_data['r']

    kz = coh_tmm_data['kz_list'][layer]
    th = coh_tmm_data['th_list'][layer]
    n = coh_tmm_data['n_list'][layer]
    n_0 = coh_tmm_data['n_list'][0]
    th_0 = coh_tmm_data['th_0']

    Ef = v * exp(1j * kz * distance)
    Eb = w * exp(-1j * kz * distance)

    poyn = ((n * cos(th) * conj(Ef + Eb) * (Ef - Eb)).real
            / (n_0 * cos(th_0)).real)
    absor = ((n * cos(th) * kz * abs(Ef + Eb) ** 2).imag
             / (n_0 * cos(th_0)).real)

    return {'poyn': poyn, 'absor': absor}


def absorp_in_each_layer(coh_tmm_data):
    """Fraction of incident power absorbed in each layer. Should sum to 1."""
    num_layers = len(coh_tmm_data['d_list'])
    power_entering_each_layer = zeros(num_layers)
    power_entering_each_layer[0] = 1
    power_entering_each_layer[1] = coh_tmm_data['power_entering']
    power_entering_each_layer[-1] = coh_tmm_data['T']
    for i in range(2, num_layers - 1):
        power_entering_each_layer[i] = position_resolved(
            i, 0, coh_tmm_data)['poyn']
    final_answer = zeros(num_layers)
    final_answer[0:-1] = -np.diff(power_entering_each_layer)
    final_answer[-1] = power_entering_each_layer[-1]
    return final_answer
