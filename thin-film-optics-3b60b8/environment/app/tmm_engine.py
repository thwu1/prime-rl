"""Transfer matrix method engine for multilayer thin-film optics.

Implements the coherent TMM for planar multilayer stacks with complex
refractive indices, arbitrary angles, and both s- and p-polarization.
"""

import sys
import numpy as np
from numpy import cos, inf, zeros, array, exp, conj, pi, sin, seterr
from numpy.lib.scimath import arcsin

EPSILON = sys.float_info.epsilon


def _make_2x2(a, b, c, d, dtype=complex):
    """Build a 2x2 numpy array efficiently."""
    m = np.empty((2, 2), dtype=dtype)
    m[0, 0] = a
    m[0, 1] = b
    m[1, 0] = c
    m[1, 1] = d
    return m


def _is_forward_angle(n, theta):
    """Determine whether theta represents a forward-propagating wave in
    a medium with refractive index n.  For complex n and theta this is
    non-trivial: the forward wave is the one that decays (if evanescent)
    or carries power in the +z direction (if propagating)."""
    ncostheta = n * cos(theta)
    if abs(ncostheta.imag) > 100 * EPSILON:
        return bool(ncostheta.imag > 0)
    else:
        return bool(ncostheta.real > 0)


def _list_snell(n_list, th_0):
    """Compute propagation angle in every layer via Snell's law.
    Uses complex-safe arcsin so that angles can be complex."""
    angles = arcsin(n_list[0] * np.sin(th_0) / n_list)
    if not _is_forward_angle(n_list[0], angles[0]):
        angles[0] = pi - angles[0]
    if not _is_forward_angle(n_list[-1], angles[-1]):
        angles[-1] = pi - angles[-1]
    return angles


def _interface_r(pol, n_i, n_f, th_i, th_f):
    """Fresnel reflection amplitude at a single interface."""
    if pol == 's':
        return ((n_i * cos(th_i) - n_f * cos(th_f))
                / (n_i * cos(th_i) + n_f * cos(th_f)))
    else:
        return ((n_f * cos(th_i) - n_i * cos(th_f))
                / (n_f * cos(th_i) + n_i * cos(th_f)))


def _interface_t(pol, n_i, n_f, th_i, th_f):
    """Fresnel transmission amplitude at a single interface."""
    if pol == 's':
        return (2 * n_i * cos(th_i)
                / (n_i * cos(th_i) + n_f * cos(th_f)))
    else:
        return (2 * n_i * cos(th_i)
                / (n_f * cos(th_i) + n_i * cos(th_f)))


def _R_from_r(r):
    """Reflected power from reflection amplitude."""
    return float(abs(r) ** 2)


def _T_from_t(pol, t, n_i, n_f, th_i, th_f):
    """Transmitted power from transmission amplitude."""
    if pol == 's':
        return float(abs(t ** 2) * ((n_f * cos(th_f)).real
                                    / (n_i * cos(th_i)).real))
    else:
        return float(abs(t ** 2) * (abs(n_f * cos(th_f))
                                    / abs(n_i * cos(th_i))))


def _power_entering_from_r(pol, r, n_i, th_i):
    """Power entering the first interface, given reflection amplitude."""
    if pol == 's':
        return float((n_i * cos(th_i) * (1 + conj(r)) * (1 - r)).real
                     / (n_i * cos(th_i)).real)
    else:
        return float((n_i * conj(cos(th_i)) * (1 + r) * (1 - conj(r))).real
                     / (n_i * conj(cos(th_i))).real)


def _interface_R(pol, n_i, n_f, th_i, th_f):
    """Reflected power fraction at a single interface."""
    return _R_from_r(_interface_r(pol, n_i, n_f, th_i, th_f))


def _interface_T(pol, n_i, n_f, th_i, th_f):
    """Transmitted power fraction at a single interface."""
    t = _interface_t(pol, n_i, n_f, th_i, th_f)
    return _T_from_t(pol, t, n_i, n_f, th_i, th_f)


def coh_tmm(pol, n_list, d_list, th_0, lam_vac):
    """Coherent transfer matrix method for a planar multilayer stack.

    Parameters
    ----------
    pol : str
        Polarization, 's' or 'p'.
    n_list : sequence of complex
        Refractive index of each layer.
    d_list : sequence of float
        Thickness of each layer (first and last must be inf).
    th_0 : float or complex
        Angle of incidence in radians.
    lam_vac : float
        Vacuum wavelength.

    Returns
    -------
    dict with keys r, t, R, T, power_entering, vw_list, kz_list,
    th_list, pol, n_list, d_list, th_0, lam_vac.
    """
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)
    num_layers = n_list.size

    # Propagation angles via Snell's law
    th_list = _list_snell(n_list, th_0)

    # Wavenumber in each layer
    kz_list = 2 * pi * n_list / lam_vac

    # Phase accumulated crossing each layer
    olderr = seterr(invalid='ignore')
    delta = kz_list * d_list
    seterr(**olderr)

    # Cap very opaque layers to avoid numerical overflow
    for i in range(1, num_layers - 1):
        if delta[i].imag > 35:
            delta[i] = delta[i].real + 35j

    # Fresnel coefficients at each interface
    t_list = zeros((num_layers, num_layers), dtype=complex)
    r_list = zeros((num_layers, num_layers), dtype=complex)
    for i in range(num_layers - 1):
        t_list[i, i + 1] = _interface_t(
            pol, n_list[i], n_list[i + 1], th_list[i], th_list[i + 1])
        r_list[i, i + 1] = _interface_r(
            pol, n_list[i], n_list[i + 1], th_list[i], th_list[i + 1])

    # Build transfer matrices for internal layers
    M_list = zeros((num_layers, 2, 2), dtype=complex)
    for i in range(1, num_layers - 1):
        M_list[i] = (1 / t_list[i, i + 1]) * np.dot(
            _make_2x2(exp(-1j * delta[i]), 0, 0, exp(1j * delta[i])),
            _make_2x2(1, r_list[i, i + 1], r_list[i, i + 1], 1))

    # Composite transfer matrix
    Mtilde = _make_2x2(1, 0, 0, 1)
    for i in range(1, num_layers - 1):
        Mtilde = np.dot(Mtilde, M_list[i])
    Mtilde = np.dot(
        _make_2x2(1, r_list[0, 1], r_list[0, 1], 1) / t_list[0, 1],
        Mtilde)

    # Overall reflection and transmission amplitudes
    r = Mtilde[1, 0] / Mtilde[0, 0]
    t = 1 / Mtilde[0, 0]

    # Forward/backward wave amplitudes in each layer
    vw_list = zeros((num_layers, 2), dtype=complex)
    vw = array([[t], [0]])
    vw_list[-1, :] = np.transpose(vw)
    for i in range(num_layers - 2, 0, -1):
        vw = np.dot(M_list[i], vw)
        vw_list[i, :] = np.transpose(vw)

    # Power quantities
    R = _R_from_r(r)
    T = _T_from_t(pol, t, n_list[0], n_list[-1], th_0, th_list[-1])
    power_entering = _power_entering_from_r(pol, r, n_list[0], th_0)

    return {
        'r': r, 't': t, 'R': R, 'T': T,
        'power_entering': power_entering,
        'vw_list': vw_list, 'kz_list': kz_list, 'th_list': th_list,
        'pol': pol, 'n_list': n_list, 'd_list': d_list,
        'th_0': th_0, 'lam_vac': lam_vac,
    }


def coh_tmm_reverse(pol, n_list, d_list, th_0, lam_vac):
    """Run coh_tmm with the stack in reverse order."""
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)
    th_f = arcsin(n_list[0] * np.sin(th_0) / n_list[-1])
    if not _is_forward_angle(n_list[-1], th_f):
        th_f = pi - th_f
    return coh_tmm(pol, n_list[::-1], d_list[::-1], th_f, lam_vac)


def position_resolved(layer, distance, coh_tmm_data):
    """Compute Poynting vector, absorption, and E-field at a point.

    Parameters
    ----------
    layer : int
        Layer index (0 = incident semi-infinite medium).
    distance : float
        Distance into the layer from its start.
    coh_tmm_data : dict
        Output of coh_tmm().

    Returns
    -------
    dict with keys poyn, absor, Ex, Ey, Ez.
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

    # Forward and backward wave amplitudes at this depth
    Ef = v * exp(1j * kz * distance)
    Eb = w * exp(-1j * kz * distance)

    # Poynting vector (normal component, normalized)
    if pol == 's':
        poyn = ((n * cos(th) * conj(Ef + Eb) * (Ef - Eb)).real
                / (n_0 * cos(th_0)).real)
    else:
        poyn = ((n * conj(cos(th)) * (Ef + Eb) * conj(Ef - Eb)).real
                / (n_0 * conj(cos(th_0))).real)

    # Local absorption density
    if pol == 's':
        absor = ((n * cos(th) * kz * abs(Ef + Eb) ** 2).imag
                 / (n_0 * cos(th_0)).real)
    else:
        absor = ((n * conj(cos(th))
                  * (kz * abs(Ef - Eb) ** 2
                     - conj(kz) * abs(Ef + Eb) ** 2)).imag
                 / (n_0 * conj(cos(th_0))).real)

    # Electric field components
    if pol == 's':
        Ex, Ey, Ez = 0, Ef + Eb, 0
    else:
        Ex = (Ef - Eb) * cos(th)
        Ey = 0
        Ez = (-Ef - Eb) * sin(th)

    return {'poyn': poyn, 'absor': absor, 'Ex': Ex, 'Ey': Ey, 'Ez': Ez}


def absorp_in_each_layer(coh_tmm_data):
    """Fraction of incident power absorbed in each layer.

    Returns an array whose entries sum to 1.
    """
    num_layers = len(coh_tmm_data['d_list'])
    power_entering_each = zeros(num_layers)
    power_entering_each[0] = 1
    power_entering_each[1] = coh_tmm_data['power_entering']
    power_entering_each[-1] = coh_tmm_data['T']
    for i in range(2, num_layers - 1):
        power_entering_each[i] = position_resolved(i, 0, coh_tmm_data)['poyn']
    result = zeros(num_layers)
    result[:-1] = -np.diff(power_entering_each)
    result[-1] = power_entering_each[-1]
    return result


def ellips(n_list, d_list, th_0, lam_vac):
    """Compute ellipsometric parameters psi and Delta.

    Returns dict with 'psi' and 'Delta' in radians.
    """
    s_data = coh_tmm('s', n_list, d_list, th_0, lam_vac)
    p_data = coh_tmm('p', n_list, d_list, th_0, lam_vac)
    rs = s_data['r']
    rp = p_data['r']
    return {
        'psi': float(np.arctan(abs(rp / rs))),
        'Delta': float(np.angle(-rp / rs)),
    }
