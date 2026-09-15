"""Modal analysis module: LSCF pole identification, stabilization, LSFD, MAC, normal modes."""


import numpy as np
from scipy.linalg import toeplitz
from scipy.optimize import least_squares


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _irfft_adjusted_lower_limit(x, low_lim, indices):
    """IRFFT with adjusted lower-limit summation bounds."""
    nf = 2 * (x.shape[1] - 1)
    a = np.fft.irfft(x, n=nf)[:, indices] * nf
    b = np.fft.irfft(x[:, :low_lim], n=nf)[:, indices] * nf
    return a - b


def _complex_freq_to_freq_and_damp(sr):
    """Convert complex poles to natural frequency [Hz] and damping ratio."""
    sr = np.asarray(sr, dtype=complex)
    fr = np.sign(np.imag(sr)) * np.abs(sr)
    fr[fr == 0] = -1e-10
    xir = -sr.real / fr
    fr /= (2 * np.pi)
    return fr, xir


def _redundant_values(omega, xi, prec=1e-3):
    """Remove duplicate frequencies within *prec* absolute tolerance."""
    N = len(omega)
    keep = np.ones(N, dtype=bool)
    for i in range(1, N):
        for j in range(i):
            if keep[j] and abs(omega[i] - omega[j]) < prec:
                keep[i] = False
                break
    return omega[keep].reshape(-1, 1), xi[keep].reshape(-1, 1)


def _stabilization(all_poles, nmax, err_fn=0.001, err_xi=0.05):
    """Build stabilization matrices comparing consecutive polynomial orders."""
    fn_temp = np.zeros((2 * nmax, nmax))
    xi_temp = np.zeros((2 * nmax, nmax))
    test_fn = np.zeros((2 * nmax, nmax), dtype=int)
    test_xi = np.zeros((2 * nmax, nmax), dtype=int)

    for nr in range(nmax):
        fn, xi = _complex_freq_to_freq_and_damp(all_poles[nr])
        fn, xi = _redundant_values(fn, xi)
        n_p = min(len(fn), 2 * nmax)

        fn_temp[:n_p, nr] = fn[:n_p, 0]
        xi_temp[:n_p, nr] = xi[:n_p, 0]

        if nr >= 1:
            prev_fn = fn_temp[:, nr - 1].copy()
            prev_xi = xi_temp[:, nr - 1].copy()
            prev_fn[prev_fn == 0] = 1e-10
            prev_xi[prev_xi == 0] = 1e-10
            for i in range(n_p):
                if np.any(np.abs((fn_temp[i, nr] - prev_fn) / prev_fn) < err_fn):
                    test_fn[i, nr] = 1
                if np.any(np.abs((xi_temp[i, nr] - prev_xi) / prev_xi) < err_xi):
                    test_xi[i, nr] = 1

    return fn_temp, xi_temp, test_fn, test_xi


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def identify_poles(frf, freq, lower, upper, pol_order_high):
    """Identify system poles via LSCF at ascending polynomial orders."""
    frf = np.asarray(frf, dtype=complex).copy()
    freq = np.asarray(freq, dtype=float).copy()
    if frf.ndim == 1:
        frf = frf[np.newaxis, :]

    # Truncate at upper frequency limit
    cutoff = np.argmin(np.abs(freq - upper))
    frf = frf[:, :cutoff]
    freq = freq[:cutoff]

    # Zero-pad to start from 0 Hz (Z-domain projection)
    if freq[0] != 0:
        df = freq[1] - freq[0]
        f0 = np.arange(0, freq[0], df)
        freq = np.hstack((f0, freq))
        frf = np.column_stack((np.zeros((frf.shape[0], len(f0)), dtype=complex), frf))

    lower_ind = np.argmin(np.abs(freq - lower))
    dt = 1.0 / (2 * freq[-1])

    n = pol_order_high * 2
    nf = 2 * (frf.shape[1] - 1)
    nr = frf.shape[0]

    idx_s = np.arange(-n, n + 1)
    idx_t = np.arange(n + 1)

    sk = -_irfft_adjusted_lower_limit(frf, lower_ind, idx_s)
    t = _irfft_adjusted_lower_limit(frf.real ** 2 + frf.imag ** 2, lower_ind, idx_t)
    r = -(np.fft.irfft(np.ones(lower_ind), n=nf))[idx_t] * nf
    r[0] += nf

    S = [toeplitz(sk[i, n:], sk[i, : n + 1][::-1]) for i in range(nr)]
    T = toeplitz(np.sum(t[:, : n + 1], axis=0))
    R = toeplitz(r)

    all_poles, pole_freq, pole_xi = [], [], []

    for j in range(2, n + 1, 2):
        sz = j + 1
        Rinv = np.linalg.inv(R[:sz, :sz])
        D = T[:sz, :sz].copy()
        for i in range(nr):
            Sn = S[i][:sz, :sz]
            D -= Sn.T @ Rinv @ Sn

        coeffs = np.linalg.solve(-D[:j, :j], D[:j, j])
        z_roots = np.roots(np.append(coeffs, 1)[::-1])
        poles = -np.log(z_roots) / dt

        fp, xp = _complex_freq_to_freq_and_damp(poles)
        all_poles.append(poles)
        pole_freq.append(fp)
        pole_xi.append(xp)

    return {'all_poles': all_poles, 'pole_freq': pole_freq, 'pole_xi': pole_xi}


def select_stable_poles(all_poles, pole_freq, pole_xi, approx_nat_freq, f_window=50):
    """Select the most stable pole near each approximate natural frequency."""
    nmax = len(all_poles)
    fn_temp, xi_temp, test_fn, test_xi = _stabilization(all_poles, nmax)

    b = np.argwhere((test_fn > 0) & (test_xi > 0) & (xi_temp > 0))
    mask = np.zeros_like(fn_temp)
    if len(b) > 0:
        mask[b[:, 0], b[:, 1]] = 1
    f_stable = fn_temp * mask
    xi_stable = xi_temp * mask
    f_stable[np.isnan(f_stable)] = 0
    xi_stable[np.isnan(xi_stable)] = 0

    nf_out, nxi_out, sp_out = [], [], []
    f_windows = [f_window // i for i in range(2, 100) if f_window // i > 3] + [2]

    for fr0 in approx_nat_freq:
        fr = float(fr0)
        for fw in f_windows:
            cand = f_stable[(f_stable > (fr - fw)) & (f_stable < (fr + fw))]
            if len(cand) > 0:
                try:
                    sol = least_squares(lambda x: cand.flatten() - x[0], x0=[fr])
                    fr = sol.x[0]
                except Exception:
                    pass

        flat = np.argmin(np.abs(f_stable - fr))
        idx = np.unravel_index(flat, f_stable.shape)
        order = idx[1]

        fn_s = fn_temp[idx]
        xi_s = xi_temp[idx]
        pole_re = -xi_s * 2 * np.pi * fn_s + 1j * 2 * np.pi * fn_s * np.sqrt(max(0, 1 - xi_s ** 2))
        actual = np.argmin(np.abs(all_poles[order] - pole_re))

        nf_out.append(f_stable[idx])
        nxi_out.append(xi_stable[idx])
        sp_out.append(all_poles[order][actual])

    return {
        'nat_freq': np.array(nf_out),
        'nat_xi': np.array(nxi_out),
        'selected_poles': np.array(sp_out),
    }


def identify_modal_constants(poles, frf, freq, frf_type='receptance'):
    """Estimate complex modal constants via LSFD and reconstruct the FRF."""
    frf_t = np.asarray(frf, dtype=complex).T          # (nf, nloc)
    freq = np.asarray(freq, dtype=float)
    poles = np.asarray(poles, dtype=complex)

    omega = 2 * np.pi * freq[:, None]                  # (nf, 1)
    sr = poles.real                                     # (np,)
    si = poles.imag                                     # (np,)

    # Build participation sub-matrices for each FRF type
    if frf_type == 'receptance':
        p11 = -(sr) / (sr ** 2 + (-si + omega) ** 2) - (sr) / (sr ** 2 + (si + omega) ** 2)
        p12 = (-si + omega) / (sr ** 2 + (-si + omega) ** 2) - (si + omega) / (sr ** 2 + (si + omega) ** 2)
        p21 = (si - omega) / (sr ** 2 + (-si + omega) ** 2) - (si + omega) / (sr ** 2 + (si + omega) ** 2)
        p22 = -(sr) / (sr ** 2 + (-si + omega) ** 2) + (sr) / (sr ** 2 + (si + omega) ** 2)
        p1L = np.kron(np.array([1, 0]), -1 / omega ** 2)
        p2L = np.kron(np.array([0, 1]), -1 / omega ** 2)
        p1U = np.kron(np.array([1, 0]), np.ones_like(omega))
        p2U = np.kron(np.array([0, 1]), np.ones_like(omega))
    elif frf_type == 'mobility':
        p11 = (-si * omega + omega ** 2) / (sr ** 2 + (-si + omega) ** 2) + (si * omega + omega ** 2) / (sr ** 2 + (si + omega) ** 2)
        p12 = (sr * omega) / (sr ** 2 + (-si + omega) ** 2) - (sr * omega) / (sr ** 2 + (si + omega) ** 2)
        p21 = -(sr * omega) / (sr ** 2 + (-si + omega) ** 2) - (sr * omega) / (sr ** 2 + (si + omega) ** 2)
        p22 = (-si * omega + omega ** 2) / (sr ** 2 + (-si + omega) ** 2) - (si * omega + omega ** 2) / (sr ** 2 + (si + omega) ** 2)
        p1L = np.kron(np.array([1, 0]), 1 / omega)
        p2L = np.kron(np.array([0, 1]), -1 / omega)
        p1U = np.kron(np.array([1, 0]), -omega)
        p2U = np.kron(np.array([0, 1]), omega)
    elif frf_type == 'accelerance':
        p11 = (sr * omega ** 2) / (sr ** 2 + (-si + omega) ** 2) + (sr * omega ** 2) / (sr ** 2 + (si + omega) ** 2)
        p12 = (si * omega ** 2 - omega ** 3) / (sr ** 2 + (-si + omega) ** 2) + (si * omega ** 2 + omega ** 3) / (sr ** 2 + (si + omega) ** 2)
        p21 = (-si * omega ** 2 + omega ** 3) / (sr ** 2 + (-si + omega) ** 2) + (si * omega ** 2 + omega ** 3) / (sr ** 2 + (si + omega) ** 2)
        p22 = (sr * omega ** 2) / (sr ** 2 + (-si + omega) ** 2) - (sr * omega ** 2) / (sr ** 2 + (si + omega) ** 2)
        p1L = np.kron(np.array([1, 0]), np.ones_like(omega))
        p2L = np.kron(np.array([0, 1]), np.ones_like(omega))
        p1U = np.kron(np.array([1, 0]), -omega ** 2)
        p2U = np.kron(np.array([0, 1]), -omega ** 2)
    else:
        raise ValueError(f"Unknown frf_type '{frf_type}'")

    P = np.block([[p11, p12, p1L, p1U],
                  [p21, p22, p2L, p2U]])
    Y = np.block([[frf_t.real], [frf_t.imag]])

    A_ = np.linalg.lstsq(P, Y, rcond=None)[0].T       # (nloc, 2*np+4)

    n_poles = len(poles)
    Ar, Ai = np.split(A_[:, : 2 * n_poles], 2, axis=1)
    A = Ar + 1j * Ai                                   # (nloc, np)

    LR = A_[:, -4] + 1j * A_[:, -3]
    UR = A_[:, -2] + 1j * A_[:, -1]

    FRF_ = np.einsum('fp,op->fo', P, A_)               # (2*nf, nloc)
    Fr, Fi = np.split(FRF_, 2, axis=0)
    FRF_rec = (Fr + 1j * Fi).T                          # (nloc, nf)

    return {
        'modal_constants': A,
        'reconstructed_frf': FRF_rec,
        'LR': LR,
        'UR': UR,
    }


def mac(phi_X, phi_A):
    """Modal Assurance Criterion between two (possibly complex) mode shape sets."""
    phi_X = np.asarray(phi_X, dtype=complex)
    phi_A = np.asarray(phi_A, dtype=complex)
    if phi_X.ndim == 1:
        phi_X = phi_X[:, np.newaxis]
    if phi_A.ndim == 1:
        phi_A = phi_A[:, np.newaxis]

    nX = phi_X.shape[1]
    nA = phi_A.shape[1]
    M = np.zeros((nX, nA))
    for i in range(nX):
        for j in range(nA):
            num = np.abs(np.conj(phi_X[:, i]) @ phi_A[:, j]) ** 2
            den = np.real(np.conj(phi_X[:, i]) @ phi_X[:, i]) * np.real(np.conj(phi_A[:, j]) @ phi_A[:, j])
            M[i, j] = num / den if den > 0 else 0.0

    if M.shape == (1, 1):
        return M[0, 0]
    return M


def complex_to_normal_mode(mode):
    """Rotate complex mode shapes to maximise the real-part norm (normal modes)."""
    mode = np.asarray(mode, dtype=complex)
    if mode.ndim == 1:
        mode = mode[:, np.newaxis]

    n_loc, n_modes = mode.shape
    normal = np.zeros((n_loc, n_modes))

    for k in range(n_modes):
        m = mode[:, k].copy()
        m /= np.linalg.norm(m)
        U = np.outer(m.real, m.real) + np.outer(m.imag, m.imag)
        vals, vecs = np.linalg.eigh(U)
        normal[:, k] = vecs[:, np.argmax(vals)]

    return normal
