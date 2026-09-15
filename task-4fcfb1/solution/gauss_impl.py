"""
Gaussian basis function rotation library.

Implements Cartesian and spherical Gaussian rotation matrices for
quantum chemistry MO coefficient transformations.

"""
import numpy as np
from math import factorial, comb
from itertools import permutations as _permutations


def cartesian_powers(l):
    """
    Generate sorted power index tuples (i, j, k) with i+j+k=l
    for Cartesian Gaussian basis functions of angular momentum l.
    Ordering: descending in i, then descending in j.
    """
    powers = []
    for i in range(l, -1, -1):
        for j in range(l - i, -1, -1):
            k = l - i - j
            powers.append((i, j, k))
    return powers


def overlap_matrix(l):
    """
    Compute the overlap matrix S between normalized Cartesian Gaussian
    functions of angular momentum l.

    S(i1,j1,k1, i2,j2,k2) =
        [(i1+i2)!(j1+j2)!(k1+k2)!] / [((i1+i2)/2)!((j1+j2)/2)!((k1+k2)/2)!]
        * sqrt[i1!j1!k1!i2!j2!k2! / (2i1)!(2j1)!(2k1)!(2i2)!(2j2)!(2k2)!]

    Element is 0 if any of i1+i2, j1+j2, k1+k2 is odd.
    """
    powers = cartesian_powers(l)
    n = len(powers)
    S = np.zeros((n, n))

    for a, (i1, j1, k1) in enumerate(powers):
        for b, (i2, j2, k2) in enumerate(powers):
            si, sj, sk = i1 + i2, j1 + j2, k1 + k2
            if si % 2 != 0 or sj % 2 != 0 or sk % 2 != 0:
                continue
            num = factorial(si) * factorial(sj) * factorial(sk)
            den = factorial(si // 2) * factorial(sj // 2) * factorial(sk // 2)
            sqrt_num = (
                factorial(i1)
                * factorial(j1)
                * factorial(k1)
                * factorial(i2)
                * factorial(j2)
                * factorial(k2)
            )
            sqrt_den = (
                factorial(2 * i1)
                * factorial(2 * j1)
                * factorial(2 * k1)
                * factorial(2 * i2)
                * factorial(2 * j2)
                * factorial(2 * k2)
            )
            S[a, b] = (num / den) * np.sqrt(sqrt_num / sqrt_den)

    return S


def _power_index_arrays(l):
    """
    Convert power tuples to sorted index arrays of length l.
    Each tuple (i, j, k) becomes a sorted list of l indices from {0,1,2}
    with i zeros, j ones, and k twos.
    """
    powers = cartesian_powers(l)
    arrays = []
    for i, j, k in powers:
        arr = tuple(sorted([0] * i + [1] * j + [2] * k))
        arrays.append(arr)
    return arrays


def _norm_weights(l):
    """Normalization weights relating unnormalized Cartesian monomials to
    normalized Gaussian basis functions.

    w_i = (2a_i)! (2b_i)! (2c_i)! / (2^l a_i! b_i! c_i!)

    These arise from the self-overlap of unnormalized Cartesian Gaussians:
    <x^a y^b z^c | x^a y^b z^c> is proportional to w_i.
    """
    powers = cartesian_powers(l)
    return np.array(
        [
            factorial(2 * a) * factorial(2 * b) * factorial(2 * c)
            / (2**l * factorial(a) * factorial(b) * factorial(c))
            for a, b, c in powers
        ],
        dtype=float,
    )


def cartesian_rotation_matrix(l, R):
    """
    Compute the N x N rotation matrix for normalized Cartesian Gaussian
    MO coefficients under a 3x3 spatial rotation R, where N = (l+1)(l+2)/2.

    Algorithm: for each pair of power index arrays p1, p2 (of length l),
    result[p2_idx, p1_idx] += product_{k} R[perm(p2)[k], p1[k]]
    summed over all unique permutations of p2.

    The raw algorithm produces the rotation in the unnormalized monomial
    basis. A similarity transform D^{-1} R_u D converts to the normalized
    Gaussian basis, where D = diag(1/sqrt(w_i)) and w_i are the
    normalization weights.
    """
    R = np.asarray(R, dtype=float)
    cg_powers = _power_index_arrays(l)
    n = len(cg_powers)
    result = np.zeros((n, n))

    for p1_idx, p1 in enumerate(cg_powers):
        for p2_idx, p2 in enumerate(cg_powers):
            seen = set()
            for perm in _permutations(p2):
                if perm in seen:
                    continue
                seen.add(perm)
                tmp = 1.0
                for k_idx in range(l):
                    tmp *= R[perm[k_idx], p1[k_idx]]
                result[p2_idx, p1_idx] += tmp

    # Convert from unnormalized monomial basis to normalized Gaussian basis
    w = _norm_weights(l)
    d = np.sqrt(w)
    result = np.diag(d) @ result @ np.diag(1.0 / d)

    return result


def _compute_solid_harmonic_coeffs(l, m):
    """
    Compute the unnormalized real solid harmonic R_{l,m} as a Cartesian
    polynomial. Returns dict mapping (i, j, k) -> coefficient where i+j+k=l.

    m > 0: C_{l,m} (cosine-like, associated with cos(m*phi))
    m = 0: C_{l,0} (zonal harmonic)
    m < 0: S_{l,|m|} (sine-like, associated with sin(|m|*phi))

    Uses the explicit formula:
    Pi_{l,m}(z, r^2) = sum_k (-1)^k (2l-2k)! / (2^l k! (l-k)! (l-2k-m)!)
                       * z^{l-2k-m} * r^{2k}

    Combined with:
    A_m(x,y) = sum_p (-1)^p C(m,2p) x^{m-2p} y^{2p}      (for C_{l,m})
    B_m(x,y) = sum_p (-1)^p C(m,2p+1) x^{m-2p-1} y^{2p+1} (for S_{l,m})
    """
    abs_m = abs(m)
    is_sine = m < 0
    result = {}

    for k in range((l - abs_m) // 2 + 1):
        pi_coeff = ((-1) ** k * factorial(2 * l - 2 * k)) / (
            2**l
            * factorial(k)
            * factorial(l - k)
            * factorial(l - 2 * k - abs_m)
        )
        z_power = l - 2 * k - abs_m

        # Expand r^{2k} = (x^2 + y^2 + z^2)^k using multinomial theorem
        for a in range(k + 1):
            for b in range(k - a + 1):
                c = k - a - b
                r2k_coeff = factorial(k) / (
                    factorial(a) * factorial(b) * factorial(c)
                )

                if abs_m == 0:
                    ix, iy, iz = 2 * a, 2 * b, 2 * c + z_power
                    key = (ix, iy, iz)
                    result[key] = result.get(key, 0.0) + pi_coeff * r2k_coeff
                elif not is_sine:
                    for p in range(abs_m // 2 + 1):
                        am_coeff = (-1) ** p * comb(abs_m, 2 * p)
                        ix = 2 * a + abs_m - 2 * p
                        iy = 2 * b + 2 * p
                        iz = 2 * c + z_power
                        key = (ix, iy, iz)
                        result[key] = (
                            result.get(key, 0.0)
                            + pi_coeff * r2k_coeff * am_coeff
                        )
                else:
                    for p in range((abs_m - 1) // 2 + 1):
                        bm_coeff = (-1) ** p * comb(abs_m, 2 * p + 1)
                        ix = 2 * a + abs_m - 2 * p - 1
                        iy = 2 * b + 2 * p + 1
                        iz = 2 * c + z_power
                        key = (ix, iy, iz)
                        result[key] = (
                            result.get(key, 0.0)
                            + pi_coeff * r2k_coeff * bm_coeff
                        )

    return result


def spherical_to_cartesian_matrix(l):
    """
    Compute the (2l+1) x N_cart transformation matrix c that maps
    Cartesian Gaussian coefficients to spherical (pure) Gaussian coefficients.

    Built from the real solid harmonics expressed as Cartesian polynomials,
    ordered by m = -l, -l+1, ..., 0, ..., l-1, l.

    The solid harmonic coefficients (in the unnormalized monomial basis) are
    first converted to the normalized Gaussian basis using the normalization
    weights, then each row is normalized so that c * S * c^T = I.
    """
    powers = cartesian_powers(l)
    n_cart = len(powers)
    n_sph = 2 * l + 1
    S = overlap_matrix(l)

    # Build unnormalized c matrix from solid harmonic coefficients
    c_unnorm = np.zeros((n_sph, n_cart))

    for row, m in enumerate(range(-l, l + 1)):
        coeffs = _compute_solid_harmonic_coeffs(l, m)
        for col, (i, j, k) in enumerate(powers):
            c_unnorm[row, col] = coeffs.get((i, j, k), 0.0)

    # Convert from unnormalized monomial basis to normalized Gaussian basis
    w = _norm_weights(l)
    c_unnorm *= np.sqrt(w)

    # Normalize each row so that c * S * c^T = I
    c = np.zeros((n_sph, n_cart))
    for i in range(n_sph):
        row = c_unnorm[i]
        norm_sq = row @ S @ row
        if norm_sq > 1e-30:
            c[i] = row / np.sqrt(norm_sq)

    return c


def spherical_rotation_matrix(l, R, c, S):
    """
    Compute the (2l+1) x (2l+1) rotation matrix for spherical Gaussian
    MO coefficients:
        D = c * S * R_cart * c^T

    This is derived from the defining relation R_cart * c^T = c^T * D,
    left-multiplied by c * S (using c * S * c^T = I).
    """
    R_cart = cartesian_rotation_matrix(l, R)
    return c @ S @ R_cart @ c.T
