"""Generate synthetic FRF data from a 5-DOF mass-spring-damper system.

Produces accelerance-type frequency response functions from a known
chain system (left-fixed boundary) for modal analysis benchmarking.
Ground truth natural frequencies and damping ratios are computed via
state-space eigenvalue analysis; mode shapes via the undamped
generalized eigenvalue problem.
"""
import numpy as np
import os


def build_chain_matrices(masses, stiffnesses, damping_coeffs):
    """Build M, K, C matrices for a left-fixed chain system.

    Topology: ground --k0/c0-- m0 --k1/c1-- m1 -- ... -- m_{n-1}
    """
    n = len(masses)
    M = np.diag(masses)
    K = np.zeros((n, n))
    C = np.zeros((n, n))

    for i in range(n):
        K[i, i] += stiffnesses[i]
        C[i, i] += damping_coeffs[i]
        if i < n - 1:
            K[i, i] += stiffnesses[i + 1]
            K[i, i + 1] -= stiffnesses[i + 1]
            K[i + 1, i] -= stiffnesses[i + 1]
            C[i, i] += damping_coeffs[i + 1]
            C[i, i + 1] -= damping_coeffs[i + 1]
            C[i + 1, i] -= damping_coeffs[i + 1]

    return M, K, C


def compute_true_modal_params(M, K, C):
    """Compute exact natural frequencies, damping ratios, and mode shapes."""
    from scipy.linalg import eigh

    n = M.shape[0]

    # State-space eigenvalue problem for damped natural frequencies
    A_state = np.zeros((2 * n, 2 * n))
    A_state[:n, n:] = np.eye(n)
    M_inv = np.linalg.inv(M)
    A_state[n:, :n] = -M_inv @ K
    A_state[n:, n:] = -M_inv @ C

    evals = np.linalg.eig(A_state)[0]
    pos_imag = evals[np.imag(evals) > 0]
    sort_idx = np.argsort(np.imag(pos_imag))
    pos_imag = pos_imag[sort_idx]

    nat_freq = np.abs(pos_imag) / (2 * np.pi)  # Hz
    damping_ratios = -np.real(pos_imag) / np.abs(pos_imag)

    # Undamped mass-normalized mode shapes
    eigenvalues, eigenvectors = eigh(K, M)
    for i in range(n):
        modal_mass = eigenvectors[:, i].T @ M @ eigenvectors[:, i]
        eigenvectors[:, i] /= np.sqrt(abs(modal_mass))

    return nat_freq, damping_ratios, eigenvectors


def generate_receptance_frf(M, K, C, freq, excitation_dof=0):
    """Generate receptance FRF via direct matrix inversion H(w) = [K - w^2 M + jwC]^{-1}."""
    n = M.shape[0]
    omega = 2 * np.pi * freq
    frf = np.zeros((n, len(freq)), dtype=complex)

    force = np.zeros(n)
    force[excitation_dof] = 1.0

    for idx, w in enumerate(omega):
        Z = K - w ** 2 * M + 1j * w * C
        frf[:, idx] = np.linalg.solve(Z, force)

    return frf


def generate_system_data():
    """Generate and persist synthetic FRF data."""
    masses = np.array([1.0, 0.8, 0.6, 0.4, 0.2])
    stiffnesses = np.array([500e3, 1.3e6, 3.8e6, 7.8e6, 7.9e6])
    damping_coeffs = np.array([12.0, 25.0, 55.0, 90.0, 160.0])

    M, K, C = build_chain_matrices(masses, stiffnesses, damping_coeffs)
    nat_freq, damping_ratios, mode_shapes = compute_true_modal_params(M, K, C)

    f_min = 10.0
    f_max = round(nat_freq[-1] * 1.5 / 100) * 100
    freq = np.linspace(f_min, f_max, 10000)

    # Generate receptance first, then convert to accelerance
    frf_receptance = generate_receptance_frf(M, K, C, freq, excitation_dof=0)
    omega = 2 * np.pi * freq
    frf = -omega[np.newaxis, :] ** 2 * frf_receptance  # accelerance = -w^2 * receptance

    os.makedirs('/app/data', exist_ok=True)
    np.savez(
        '/app/data/frf_data.npz',
        freq=freq,
        frf=frf,
        nat_freq_true=nat_freq,
        damping_true=damping_ratios,
        mode_shapes_true=mode_shapes,
    )

    return freq, frf, nat_freq, damping_ratios, mode_shapes


if __name__ == '__main__':
    freq, frf, nat_freq, damping, modes = generate_system_data()
    print(f"Natural frequencies: {nat_freq} Hz")
    print(f"Damping ratios: {damping}")
    print(f"FRF shape: {frf.shape}")
    print(f"Frequency range: {freq[0]:.1f} - {freq[-1]:.1f} Hz")
