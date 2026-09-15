"""Transfer matrix method engine for multilayer thin-film optics.

Implements coherent and incoherent TMM for planar multilayer stacks
with complex refractive indices, arbitrary angles, s- and p-polarization.
Uses a C shared library (libmatkernel.so) for the matrix chain product.
"""

import sys
import os
import ctypes
import numpy as np
from numpy import cos, inf, zeros, array, exp, conj, nan, isnan, pi, sin, seterr
from numpy.lib.scimath import arcsin

EPSILON = sys.float_info.epsilon

# Load C kernel for 2x2 complex matrix operations
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libmatkernel.so')
_kernel = ctypes.CDLL(_lib_path)
_kernel.mat2x2_chain_multiply.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_int,
    ctypes.POINTER(ctypes.c_double)]
_kernel.mat2x2_chain_multiply.restype = None


def _make_2x2(a, b, c, d, dtype=complex):
    """Build a 2x2 numpy array efficiently."""
    m = np.empty((2, 2), dtype=dtype)
    m[0, 0] = a
    m[0, 1] = b
    m[1, 0] = c
    m[1, 1] = d
    return m


def _is_forward_angle(n, theta):
    """Determine whether theta represents a forward-propagating wave."""
    ncostheta = n * cos(theta)
    if abs(ncostheta.imag) > 100 * EPSILON:
        return bool(ncostheta.imag > 0)
    else:
        return bool(ncostheta.real > 0)


def _list_snell(n_list, th_0):
    """Compute propagation angle in every layer via Snell's law."""
    angles = arcsin(n_list[0] * np.sin(th_0) / n_list)
    if not _is_forward_angle(n_list[0], angles[0]):
        angles[0] = pi - angles[0]
    if not _is_forward_angle(n_list[-1], angles[-1]):
        angles[-1] = pi - angles[-1]
    return angles


def _snell(n_1, n_2, th_1):
    """Angle in layer 2 via Snell's law."""
    th_2_guess = arcsin(n_1 * np.sin(th_1) / n_2)
    if _is_forward_angle(n_2, th_2_guess):
        return th_2_guess
    else:
        return pi - th_2_guess


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
        return float(abs(t ** 2) * ((n_f * conj(cos(th_f))).real
                                    / (n_i * conj(cos(th_i))).real))


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
    """Coherent transfer matrix method for a planar multilayer stack."""
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)
    num_layers = n_list.size

    th_list = _list_snell(n_list, th_0)
    kz_list = 2 * pi * n_list * cos(th_list) / lam_vac

    olderr = seterr(invalid='ignore')
    delta = kz_list * d_list
    seterr(**olderr)

    for i in range(1, num_layers - 1):
        if delta[i].imag > 35:
            delta[i] = delta[i].real + 35j

    t_list = zeros((num_layers, num_layers), dtype=complex)
    r_list = zeros((num_layers, num_layers), dtype=complex)
    for i in range(num_layers - 1):
        t_list[i, i + 1] = _interface_t(
            pol, n_list[i], n_list[i + 1], th_list[i], th_list[i + 1])
        r_list[i, i + 1] = _interface_r(
            pol, n_list[i], n_list[i + 1], th_list[i], th_list[i + 1])

    M_list = zeros((num_layers, 2, 2), dtype=complex)
    for i in range(1, num_layers - 1):
        M_list[i] = (1 / t_list[i, i + 1]) * np.dot(
            _make_2x2(exp(-1j * delta[i]), 0, 0, exp(1j * delta[i])),
            _make_2x2(1, r_list[i, i + 1], r_list[i, i + 1], 1))

    # Chain-multiply internal transfer matrices via C kernel
    n_internal = num_layers - 2
    if n_internal > 0:
        flat = np.empty(n_internal * 8)
        for idx in range(n_internal):
            m = M_list[idx + 1]
            base = idx * 8
            flat[base] = m[0, 0].real
            flat[base + 1] = m[0, 0].imag
            flat[base + 2] = m[0, 1].real
            flat[base + 3] = m[0, 1].imag
            flat[base + 4] = m[1, 0].real
            flat[base + 5] = m[1, 0].imag
            flat[base + 6] = m[1, 1].real
            flat[base + 7] = m[1, 1].imag
        out = (ctypes.c_double * 8)()
        _kernel.mat2x2_chain_multiply(
            flat.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            n_internal, out)
        Mtilde = _make_2x2(
            complex(out[0], out[1]), complex(out[2], out[3]),
            complex(out[4], out[5]), complex(out[6], out[7]))
    else:
        Mtilde = _make_2x2(1, 0, 0, 1)

    Mtilde = np.dot(
        _make_2x2(1, r_list[0, 1], r_list[0, 1], 1) / t_list[0, 1],
        Mtilde)

    r = Mtilde[1, 0] / Mtilde[0, 0]
    t = 1 / Mtilde[0, 0]

    vw_list = zeros((num_layers, 2), dtype=complex)
    vw = array([[t], [0]])
    vw_list[-1, :] = np.transpose(vw)
    for i in range(num_layers - 2, 0, -1):
        vw = np.dot(M_list[i], vw)
        vw_list[i, :] = np.transpose(vw)

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
    th_f = _snell(n_list[0], n_list[-1], th_0)
    return coh_tmm(pol, n_list[::-1], d_list[::-1], th_f, lam_vac)


def position_resolved(layer, distance, coh_tmm_data):
    """Compute Poynting vector, absorption, and E-field at a point."""
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
    else:
        poyn = ((n * conj(cos(th)) * (Ef + Eb) * conj(Ef - Eb)).real
                / (n_0 * conj(cos(th_0))).real)

    if pol == 's':
        absor = ((n * cos(th) * kz * abs(Ef + Eb) ** 2).imag
                 / (n_0 * cos(th_0)).real)
    else:
        absor = ((n * conj(cos(th))
                  * (kz * abs(Ef - Eb) ** 2
                     - conj(kz) * abs(Ef + Eb) ** 2)).imag
                 / (n_0 * conj(cos(th_0))).real)

    if pol == 's':
        Ex, Ey, Ez = 0, Ef + Eb, 0
    else:
        Ex = (Ef - Eb) * cos(th)
        Ey = 0
        Ez = (-Ef - Eb) * sin(th)

    return {'poyn': poyn, 'absor': absor, 'Ex': Ex, 'Ey': Ey, 'Ez': Ez}


def absorp_in_each_layer(coh_tmm_data):
    """Fraction of incident power absorbed in each layer (sums to 1)."""
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
    """Compute ellipsometric parameters psi and Delta (radians)."""
    s_data = coh_tmm('s', n_list, d_list, th_0, lam_vac)
    p_data = coh_tmm('p', n_list, d_list, th_0, lam_vac)
    rs = s_data['r']
    rp = p_data['r']
    return {
        'psi': float(np.arctan(abs(rp / rs))),
        'Delta': float(np.angle(-rp / rs)),
    }


# ---------------------------------------------------------------------------
# Incoherent TMM
# ---------------------------------------------------------------------------

def _inc_group_layers(n_list, d_list, c_list):
    """Group layers into coherent stacks and incoherent layers."""
    if (d_list[0] != inf) or (d_list[-1] != inf):
        raise ValueError('d_list must start and end with inf!')
    if (c_list[0] != 'i') or (c_list[-1] != 'i'):
        raise ValueError('c_list should start and end with "i"')
    if not n_list.size == d_list.size == len(c_list):
        raise ValueError('List sizes do not match!')

    inc_index = 0
    stack_index = 0
    stack_d_list = []
    stack_n_list = []
    all_from_inc = []
    inc_from_all = []
    all_from_stack = []
    stack_from_all = []
    inc_from_stack = []
    stack_from_inc = []
    stack_in_progress = False

    for alllayer_index in range(n_list.size):
        if c_list[alllayer_index] == 'c':
            inc_from_all.append(nan)
            if not stack_in_progress:
                stack_in_progress = True
                ongoing_stack_d_list = [inf, d_list[alllayer_index]]
                ongoing_stack_n_list = [n_list[alllayer_index - 1],
                                        n_list[alllayer_index]]
                stack_from_all.append([stack_index, 1])
                all_from_stack.append([alllayer_index - 1, alllayer_index])
                inc_from_stack.append(inc_index - 1)
                within_stack_index = 1
            else:
                ongoing_stack_d_list.append(d_list[alllayer_index])
                ongoing_stack_n_list.append(n_list[alllayer_index])
                within_stack_index += 1
                stack_from_all.append([stack_index, within_stack_index])
                all_from_stack[-1].append(alllayer_index)
        elif c_list[alllayer_index] == 'i':
            stack_from_all.append(nan)
            inc_from_all.append(inc_index)
            all_from_inc.append(alllayer_index)
            if not stack_in_progress:
                stack_from_inc.append(nan)
            else:
                stack_in_progress = False
                stack_from_inc.append(stack_index)
                ongoing_stack_d_list.append(inf)
                stack_d_list.append(ongoing_stack_d_list)
                ongoing_stack_n_list.append(n_list[alllayer_index])
                stack_n_list.append(ongoing_stack_n_list)
                all_from_stack[-1].append(alllayer_index)
                stack_index += 1
            inc_index += 1
        else:
            raise ValueError("c_list entries must be 'i' or 'c'!")

    return {
        'stack_d_list': stack_d_list,
        'stack_n_list': stack_n_list,
        'all_from_inc': all_from_inc,
        'inc_from_all': inc_from_all,
        'all_from_stack': all_from_stack,
        'stack_from_all': stack_from_all,
        'inc_from_stack': inc_from_stack,
        'stack_from_inc': stack_from_inc,
        'num_stacks': len(stack_d_list),
        'num_inc_layers': len(all_from_inc),
        'num_layers': len(c_list),
    }


def inc_tmm(pol, n_list, d_list, c_list, th_0, lam_vac):
    """Incoherent or partly-incoherent transfer matrix method."""
    n_list = array(n_list, dtype=complex)
    d_list = array(d_list, dtype=float)

    group = _inc_group_layers(n_list, d_list, c_list)
    num_inc = group['num_inc_layers']
    num_stacks = group['num_stacks']

    th_list = _list_snell(n_list, th_0)

    coh_data_list = []
    coh_bdata_list = []
    for i in range(num_stacks):
        sn = group['stack_n_list'][i]
        sd = group['stack_d_list'][i]
        th_in = th_list[group['all_from_stack'][i][0]]
        coh_data_list.append(coh_tmm(pol, sn, sd, th_in, lam_vac))
        coh_bdata_list.append(coh_tmm_reverse(pol, sn, sd, th_in, lam_vac))

    P_list = zeros(num_inc)
    for inc_idx in range(1, num_inc - 1):
        i = group['all_from_inc'][inc_idx]
        P_list[inc_idx] = exp(-4 * pi * d_list[i]
                              * (n_list[i] * cos(th_list[i])).imag / lam_vac)
        if P_list[inc_idx] < 1e-30:
            P_list[inc_idx] = 1e-30

    T_list = zeros((num_inc, num_inc))
    R_list = zeros((num_inc, num_inc))
    for inc_idx in range(num_inc - 1):
        alllayer = group['all_from_inc'][inc_idx]
        next_stack = group['stack_from_inc'][inc_idx + 1]
        if isnan(next_stack):
            R_list[inc_idx, inc_idx + 1] = _interface_R(
                pol, n_list[alllayer], n_list[alllayer + 1],
                th_list[alllayer], th_list[alllayer + 1])
            T_list[inc_idx, inc_idx + 1] = _interface_T(
                pol, n_list[alllayer], n_list[alllayer + 1],
                th_list[alllayer], th_list[alllayer + 1])
            R_list[inc_idx + 1, inc_idx] = _interface_R(
                pol, n_list[alllayer + 1], n_list[alllayer],
                th_list[alllayer + 1], th_list[alllayer])
            T_list[inc_idx + 1, inc_idx] = _interface_T(
                pol, n_list[alllayer + 1], n_list[alllayer],
                th_list[alllayer + 1], th_list[alllayer])
        else:
            ns = int(next_stack)
            R_list[inc_idx, inc_idx + 1] = coh_data_list[ns]['R']
            T_list[inc_idx, inc_idx + 1] = coh_data_list[ns]['T']
            R_list[inc_idx + 1, inc_idx] = coh_bdata_list[ns]['R']
            T_list[inc_idx + 1, inc_idx] = coh_bdata_list[ns]['T']

    Ltilde = array([
        [1, -R_list[1, 0]],
        [R_list[0, 1],
         T_list[1, 0] * T_list[0, 1] - R_list[1, 0] * R_list[0, 1]]
    ]) / T_list[0, 1]

    L_list = [None]
    for i in range(1, num_inc - 1):
        L = np.dot(
            array([[1 / P_list[i], 0], [0, P_list[i]]]),
            array([
                [1, -R_list[i + 1, i]],
                [R_list[i, i + 1],
                 T_list[i + 1, i] * T_list[i, i + 1]
                 - R_list[i + 1, i] * R_list[i, i + 1]]
            ])
        ) / T_list[i, i + 1]
        L_list.append(L)
        Ltilde = np.dot(Ltilde, L)

    T_total = 1 / Ltilde[0, 0]
    R_total = Ltilde[1, 0] / Ltilde[0, 0]

    VW_list = zeros((num_inc, 2))
    VW_list[0, :] = [nan, nan]
    VW = array([[T_total], [0]])
    VW_list[-1, :] = np.transpose(VW)
    for i in range(num_inc - 2, 0, -1):
        VW = np.dot(L_list[i], VW)
        VW_list[i, :] = np.transpose(VW)

    stackFB_list = []
    for stack_idx, prev_inc_idx in enumerate(group['inc_from_stack']):
        if prev_inc_idx == 0:
            F = 1
        else:
            F = VW_list[prev_inc_idx][0] * P_list[prev_inc_idx]
        B = VW_list[prev_inc_idx + 1][1]
        stackFB_list.append([F, B])

    power_entering_list = [1]
    for i in range(1, num_inc):
        prev_stack = group['stack_from_inc'][i]
        if isnan(prev_stack):
            if i == 1:
                power_entering_list.append(
                    T_list[0, 1] - VW_list[1][1] * T_list[1, 0])
            else:
                power_entering_list.append(
                    VW_list[i - 1][0] * P_list[i - 1] * T_list[i - 1, i]
                    - VW_list[i][1] * T_list[i, i - 1])
        else:
            ps = int(prev_stack)
            power_entering_list.append(
                stackFB_list[ps][0] * coh_data_list[ps]['T']
                - stackFB_list[ps][1] * coh_bdata_list[ps]['power_entering'])

    ans = {
        'R': float(R_total), 'T': float(T_total),
        'VW_list': VW_list,
        'power_entering_list': power_entering_list,
        'coh_tmm_data_list': coh_data_list,
        'coh_tmm_bdata_list': coh_bdata_list,
        'stackFB_list': stackFB_list,
    }
    ans.update(group)
    return ans


def inc_absorp_in_each_layer(inc_data):
    """Absorption fraction in each layer for a mixed coherent/incoherent stack."""
    stack_from_inc = inc_data['stack_from_inc']
    power_entering_list = inc_data['power_entering_list']
    stackFB_list = inc_data['stackFB_list']
    absorp_list = []

    for i in range(len(power_entering_list) - 1):
        next_stack_idx = stack_from_inc[i + 1]
        if isnan(next_stack_idx):
            absorp_list.append(
                power_entering_list[i] - power_entering_list[i + 1])
        else:
            j = int(next_stack_idx)
            coh_data = inc_data['coh_tmm_data_list'][j]
            coh_bdata = inc_data['coh_tmm_bdata_list'][j]
            power_exiting = (
                stackFB_list[j][0] * coh_data['power_entering']
                - stackFB_list[j][1] * coh_bdata['T'])
            absorp_list.append(power_entering_list[i] - power_exiting)
            fwd_absorp = absorp_in_each_layer(coh_data)
            bwd_absorp = absorp_in_each_layer(coh_bdata)
            stack_absorp = (
                stackFB_list[j][0] * fwd_absorp[1:-1]
                + stackFB_list[j][1] * bwd_absorp[-2:0:-1]
            )
            absorp_list.extend(stack_absorp.tolist())

    absorp_list.append(float(inc_data['T']))
    return absorp_list
