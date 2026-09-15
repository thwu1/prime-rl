
"""
Transfer-matrix method for multilayer optical thin films.
Implements coherent TMM, ellipsometry, position-resolved Poynting/absorption,
and per-layer absorption computation.
"""

from __future__ import division, print_function, absolute_import

import numpy as np
from numpy import cos, sin, inf, zeros, array, exp, conj, pi
from numpy.lib.scimath import arcsin
import sys

EPSILON = sys.float_info.epsilon


def _make_2x2(a, b, c, d):
    """Fast 2x2 complex matrix construction."""
    m = np.empty((2, 2), dtype=complex)
    m[0, 0] = a
    m[0, 1] = b
    m[1, 0] = c
    m[1, 1] = d
    return m


def is_forward_angle(n, theta):
    """Determine if theta is the forward-traveling angle in medium n.

    For absorptive media, the forward wave is the one that decays
    (positive imaginary part of n*cos(theta)). For real media,
    forward means positive real part of n*cos(theta).
    """
    ncostheta = n * cos(theta)
    if abs(ncostheta.imag) > 100 * EPSILON:
        return bool(ncostheta.imag > 0)
    else:
        return bool(ncostheta.real > 0)


def snell(n_1, n_2, th_1):
    """Complex Snell's law: return angle in medium n_2."""
    th_2_guess = arcsin(n_1 * np.sin(th_1) / n_2)
    if is_forward_angle(n_2, th_2_guess):
        return th_2_guess
    else:
        return pi - th_2_guess


def list_snell(n_list, th_0):
    """Snell's law for all layers, ensuring forward angles at endpoints."""
    angles = arcsin(n_list[0] * np.sin(th_0) / n_list)
    if not is_forward_angle(n_list[0], angles[0]):
        angles[0] = pi - angles[0]
    if not is_forward_angle(n_list[-1], angles[-1]):
        angles[-1] = pi - angles[-1]
    return angles


def interface_r(pol, n_i, n_f, th_i, th_f):
    """Fresnel reflection amplitude."""
    if pol == 's':
        return ((n_i * cos(th_i) - n_f * cos(th_f)) /
                (n_i * cos(th_i) + n_f * cos(th_f)))
    else:
        return ((n_f * cos(th_i) - n_i * cos(th_f)) /
                (n_f * cos(th_i) + n_i * cos(th_f)))


def interface_t(pol, n_i, n_f, th_i, th_f):
    """Fresnel transmission amplitude."""
    if pol == 's':
        return 2 * n_i * cos(th_i) / (n_i * cos(th_i) + n_f * cos(th_f))
    else:
        return 2 * n_i * cos(th_i) / (n_f * cos(th_i) + n_i * cos(th_f))


def R_from_r(r):
    """Reflected power from reflection amplitude."""
    return abs(r) ** 2


def T_from_t(pol, t, n_i, n_f, th_i, th_f):
    """Transmitted power from transmission amplitude.

    Uses correct power flux formulas that differ for s and p polarization
    and handle complex (absorptive) media properly.
    """
    if pol == 's':
        return abs(t ** 2) * ((n_f * cos(th_f)).real / (n_i * cos(th_i)).real)
    else:
        return abs(t ** 2) * ((n_f * conj(cos(th_f))).real /
                              (n_i * conj(cos(th_i))).real)


def power_entering_from_r(pol, r, n_i, th_i):
    """Power entering the first interface.

    For absorptive incident media this can differ from 1-R.
    """
    if pol == 's':
        return ((n_i * cos(th_i) * (1 + conj(r)) * (1 - r)).real
                / (n_i * cos(th_i)).real)
    else:
        return ((n_i * conj(cos(th_i)) * (1 + r) * (1 - conj(r))).real
                / (n_i * conj(cos(th_i))).real)


def coh_tmm(pol, n_list, d_list, th_0, lam_vac):
    """Coherent transfer-matrix method for a multilayer planar stack.

    Parameters
    ----------
    pol : str, 's' or 'p'
    n_list : list of complex, refractive indices per layer
    d_list : list of float, thicknesses per layer (first/last = inf)
    th_0 : float, angle of incidence in radians
    lam_vac : float, vacuum wavelength

    Returns
    -------
    dict with keys: r, t, R, T, power_entering, vw_list, kz_list, th_list
    """
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)
    num_layers = n_list.size

    # Angles in each layer via Snell's law
    th_list = list_snell(n_list, th_0)

    # z-component of wavevector
    kz_list = 2 * pi * n_list * cos(th_list) / lam_vac

    # Phase accumulated in each layer
    olderr = np.seterr(invalid='ignore')
    delta = kz_list * d_list
    np.seterr(**olderr)

    # Clamp very opaque layers for numerical stability
    for i in range(1, num_layers - 1):
        if delta[i].imag > 35:
            delta[i] = delta[i].real + 35j

    # Interface Fresnel coefficients
    t_list = zeros((num_layers, num_layers), dtype=complex)
    r_list = zeros((num_layers, num_layers), dtype=complex)
    for i in range(num_layers - 1):
        t_list[i, i + 1] = interface_t(pol, n_list[i], n_list[i + 1],
                                       th_list[i], th_list[i + 1])
        r_list[i, i + 1] = interface_r(pol, n_list[i], n_list[i + 1],
                                       th_list[i], th_list[i + 1])

    # Build transfer matrices per layer
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

    # Reflection and transmission amplitudes
    r = Mtilde[1, 0] / Mtilde[0, 0]
    t = 1 / Mtilde[0, 0]

    # Forward/backward amplitudes in each layer
    vw_list = zeros((num_layers, 2), dtype=complex)
    vw = array([[t], [0]])
    vw_list[-1, :] = np.transpose(vw)
    for i in range(num_layers - 2, 0, -1):
        vw = np.dot(M_list[i], vw)
        vw_list[i, :] = np.transpose(vw)

    # Power quantities
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
    """Poynting vector and absorption at a specific depth in a layer.

    Parameters
    ----------
    layer : int, layer index (0 = incident medium)
    distance : float, depth into the layer
    coh_tmm_data : dict, output of coh_tmm()

    Returns
    -------
    dict with 'poyn' and 'absor'
    """
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
    pol = coh_tmm_data['pol']

    Ef = v * exp(1j * kz * distance)
    Eb = w * exp(-1j * kz * distance)

    if pol == 's':
        poyn = ((n * cos(th) * conj(Ef + Eb) * (Ef - Eb)).real
                / (n_0 * cos(th_0)).real)
        absor = ((n * cos(th) * kz * abs(Ef + Eb) ** 2).imag
                 / (n_0 * cos(th_0)).real)
    else:
        poyn = ((n * conj(cos(th)) * (Ef + Eb) * conj(Ef - Eb)).real
                / (n_0 * conj(cos(th_0))).real)
        absor = ((n * conj(cos(th)) *
                  (kz * abs(Ef - Eb) ** 2 - conj(kz) * abs(Ef + Eb) ** 2)
                  ).imag / (n_0 * conj(cos(th_0))).real)

    return {'poyn': poyn, 'absor': absor}


def absorp_in_each_layer(coh_tmm_data):
    """Fraction of incident power absorbed in each layer.

    First layer absorbs all reflected light; last layer absorbs all
    transmitted light. Sum equals 1.
    """
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
