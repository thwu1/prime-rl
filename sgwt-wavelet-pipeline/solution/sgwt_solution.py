#!/usr/bin/env python3

"""
Reference SGWT pipeline implementation — no PyGSP dependency.
Fixes all 8 issues in the buggy pipeline:
  1. graph.py: degree matrix uses weight sum, not edge count
  2. graph.py: no eigenvalue clipping (combinatorial Laplacian is unbounded)
  3. kernels.py: Meyer v(x) coefficient 20, not 21
  4. kernels.py: MexicanHat lowpass exponent 4, not 2
  5. scales.py: log scales descending (scale_max to scale_min)
  6. filtering.py: Chebyshev recurrence uses minus (- twf_old)
  7. frames.py: frame bounds use sum of squares, not abs
  8. jackson.py: full implementation of Chebyshev expansion + Jackson damping
"""

import json
import numpy as np
from scipy import sparse


def load_spec(path="/app/graph_spec.json"):
    with open(path) as f:
        return json.load(f)


def build_graph(spec):
    """Build adjacency matrix W and combinatorial Laplacian L = D - W."""
    N = spec["n_nodes"]
    W = np.zeros((N, N))
    for edge in spec["edges"]:
        i, j, w = int(edge[0]), int(edge[1]), float(edge[2])
        W[i, j] = w
        W[j, i] = w
    # FIX #1: degree = sum of weights, not count of edges
    D = np.diag(W.sum(axis=1))
    L = D - W
    return W, L, N


def compute_fourier_basis(L):
    """Eigendecompose the Laplacian. Returns sorted eigenvalues and eigenvectors."""
    eigenvalues, eigenvectors = np.linalg.eigh(L)
    idx = np.argsort(eigenvalues)
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]
    # Clamp tiny negatives from numerical noise
    eigenvalues = np.maximum(eigenvalues, 0.0)
    # FIX #2: NO clipping — combinatorial Laplacian eigenvalues are unbounded
    return eigenvalues, eigenvectors


def compute_log_scales(lmin, lmax, Nscales, t1=1, t2=2):
    """Log-spaced wavelet scales from scale_max down to scale_min."""
    scale_min = t1 / lmax
    scale_max = t2 / lmin
    # FIX #5: descending order (scale_max to scale_min)
    return np.exp(np.linspace(np.log(scale_max), np.log(scale_min), Nscales))


# --------------- Meyer Wavelet Kernel ---------------

def _meyer_v(x):
    """Auxiliary polynomial v(x) = x^4 * (35 - 84x + 70x^2 - 20x^3)."""
    # FIX #3: coefficient 20, not 21
    return x**4 * (35.0 - 84.0 * x + 70.0 * x**2 - 20.0 * x**3)


def meyer_kernel(x, kernel_type):
    x = np.asarray(x, dtype=float)
    l1 = 2.0 / 3.0
    l2 = 4.0 / 3.0
    l3 = 8.0 / 3.0

    r = np.zeros_like(x)

    if kernel_type == "scaling_function":
        r1 = x < l1
        r2 = (x >= l1) & (x < l2)
        r[r1] = 1.0
        r[r2] = np.cos(np.pi / 2.0 * _meyer_v(np.abs(x[r2]) / l1 - 1.0))
    elif kernel_type == "wavelet":
        r2 = (x >= l1) & (x < l2)
        r3 = (x >= l2) & (x < l3)
        r[r2] = np.sin(np.pi / 2.0 * _meyer_v(np.abs(x[r2]) / l1 - 1.0))
        r[r3] = np.cos(np.pi / 2.0 * _meyer_v(np.abs(x[r3]) / l2 - 1.0))
    else:
        raise ValueError(f"Unknown kernel type: {kernel_type}")
    return r


# --------------- MexicanHat Kernel ---------------

def mexicanhat_lowpass(x, lmin):
    # FIX #4: exponent 4, not 2
    return 1.2 * np.exp(-1.0) * np.exp(-((x / (0.4 * lmin)) ** 4))


def mexicanhat_bandpass(x, scale):
    return scale * x * np.exp(-scale * x)


# --------------- Exact Filtering via GFT ---------------

def exact_analysis(eigenvalues, eigenvectors, signal, kernel_responses):
    N = len(signal)
    Nf = kernel_responses.shape[0]
    s_hat = eigenvectors.T @ signal
    result = np.zeros((N, Nf))
    for i in range(Nf):
        result[:, i] = eigenvectors @ (s_hat * kernel_responses[i])
    return result


def exact_synthesis(eigenvalues, eigenvectors, coefficients, kernel_responses):
    N = coefficients.shape[0]
    Nf = coefficients.shape[1]
    reconstructed = np.zeros(N)
    for i in range(Nf):
        s_hat = eigenvectors.T @ coefficients[:, i]
        reconstructed += eigenvectors @ (s_hat * kernel_responses[i])
    return reconstructed


# --------------- Chebyshev Approximation ---------------

def compute_cheby_coeff(kernel_func, m, lmax):
    N = m + 1
    a1 = lmax / 2.0
    a2 = lmax / 2.0
    c = np.zeros(m + 1)
    tmpN = np.arange(N)
    nodes = np.cos(np.pi * (tmpN + 0.5) / N)
    f_vals = kernel_func(a1 * nodes + a2)
    for k in range(m + 1):
        c[k] = (2.0 / N) * np.dot(f_vals, np.cos(np.pi * k * (tmpN + 0.5) / N))
    return c


def cheby_op(L_sparse, c_all, signal, lmax):
    N = L_sparse.shape[0]
    Nscales, M = c_all.shape
    a1 = lmax / 2.0
    a2 = lmax / 2.0
    twf_old = signal.copy()
    twf_cur = (L_sparse.dot(signal) - a2 * signal) / a1
    r = np.zeros((N, Nscales))
    for i in range(Nscales):
        r[:, i] = 0.5 * c_all[i, 0] * twf_old + c_all[i, 1] * twf_cur
    factor = sparse.csr_matrix(
        (2.0 / a1) * (L_sparse - a2 * sparse.eye(N))
    )
    for k in range(2, M):
        # FIX #6: minus sign in recurrence
        twf_new = factor.dot(twf_cur) - twf_old
        for i in range(Nscales):
            r[:, i] += c_all[i, k] * twf_new
        twf_old = twf_cur
        twf_cur = twf_new
    return r


# --------------- Jackson-Chebyshev Coefficients ---------------

def compute_jackson_cheby_coeff(filter_bounds, delta_lambda, m):
    """FIX #8: Full implementation of Jackson-damped Chebyshev coefficients."""
    a1 = (delta_lambda[1] - delta_lambda[0]) / 2.0
    a2 = (delta_lambda[1] + delta_lambda[0]) / 2.0

    # Map filter bounds to Chebyshev domain [-1, 1]
    fb0 = (filter_bounds[0] - a2) / a1
    fb1 = (filter_bounds[1] - a2) / a1

    # Chebyshev expansion of ideal band-pass indicator
    ch = np.zeros(m + 1)
    ch[0] = (2.0 / np.pi) * (np.arccos(fb0) - np.arccos(fb1))
    for i in range(1, m + 1):
        ch[i] = (2.0 / (np.pi * i)) * (
            np.sin(i * np.arccos(fb0)) - np.sin(i * np.arccos(fb1))
        )

    # Jackson damping factors
    jch = np.zeros(m + 1)
    alpha = np.pi / (m + 2)
    for i in range(m + 1):
        jch[i] = (1.0 / np.sin(alpha)) * (
            (1.0 - i / (m + 2)) * np.sin(alpha) * np.cos(i * alpha)
            + (1.0 / (m + 2)) * np.cos(alpha) * np.sin(i * alpha)
        )

    # Combine: element-wise product
    return ch * jch


# --------------- Main Pipeline ---------------

def main():
    spec = load_spec()
    W, L, N = build_graph(spec)
    eigenvalues, eigenvectors = compute_fourier_basis(L)
    lmax = float(eigenvalues[-1])
    signal = np.array(spec["signal"])

    # --- Log scales ---
    lpfactor = spec["mexicanhat_lpfactor"]
    lmin = lmax / lpfactor
    mexicanhat_nf = spec["mexicanhat_nf"]
    log_scales = compute_log_scales(lmin, lmax, mexicanhat_nf - 1)

    # --- Meyer filter bank ---
    meyer_nf = spec["meyer_nf"]
    meyer_scales = (4.0 / (3.0 * lmax)) * np.power(
        2.0, np.arange(meyer_nf - 2, -1, -1)
    )

    meyer_responses = np.zeros((meyer_nf, N))
    meyer_responses[0] = meyer_kernel(meyer_scales[0] * eigenvalues, "scaling_function")
    for i in range(meyer_nf - 1):
        meyer_responses[i + 1] = meyer_kernel(
            meyer_scales[i] * eigenvalues, "wavelet"
        )

    # Exact Meyer analysis
    meyer_exact = exact_analysis(eigenvalues, eigenvectors, signal, meyer_responses)

    # FIX #7: Frame bounds use sum of SQUARES
    sum_sq = np.sum(meyer_responses**2, axis=0)
    frame_A = float(np.min(sum_sq))
    frame_B = float(np.max(sum_sq))

    # --- MexicanHat filter bank ---
    mh_responses = np.zeros((mexicanhat_nf, N))
    mh_responses[0] = mexicanhat_lowpass(eigenvalues, lmin)
    for i in range(mexicanhat_nf - 1):
        mh_responses[i + 1] = mexicanhat_bandpass(eigenvalues, log_scales[i])

    mexicanhat_exact = exact_analysis(
        eigenvalues, eigenvectors, signal, mh_responses
    )

    # --- Chebyshev approximation for Meyer ---
    cheby_order = spec["chebyshev_order"]
    L_sparse = sparse.csr_matrix(L)

    meyer_cheby_coeffs = []
    for i in range(meyer_nf):
        if i == 0:
            kfn = lambda x, s=meyer_scales[0]: meyer_kernel(s * x, "scaling_function")
        else:
            idx = i - 1
            kfn = lambda x, s=meyer_scales[idx]: meyer_kernel(s * x, "wavelet")
        c = compute_cheby_coeff(kfn, cheby_order, lmax)
        meyer_cheby_coeffs.append(c)

    c_all = np.array(meyer_cheby_coeffs)
    meyer_cheby = cheby_op(L_sparse, c_all, signal, lmax)

    cheby_max_error = float(np.max(np.abs(meyer_exact - meyer_cheby)))

    # --- Meyer reconstruction ---
    reconstructed = exact_synthesis(
        eigenvalues, eigenvectors, meyer_exact, meyer_responses
    )
    recon_error = float(np.linalg.norm(signal - reconstructed))

    # --- Jackson-Chebyshev coefficients ---
    jackson_bounds = list(spec["jackson_filter_bounds"])
    jackson_m = spec["jackson_m"]
    jch = compute_jackson_cheby_coeff(jackson_bounds, [0.0, lmax], jackson_m)

    # --- Write results ---
    results = {
        "eigenvalues": eigenvalues.tolist(),
        "log_scales": log_scales.tolist(),
        "meyer_analysis_exact": meyer_exact.tolist(),
        "meyer_frame_bounds": [frame_A, frame_B],
        "mexicanhat_analysis_exact": mexicanhat_exact.tolist(),
        "chebyshev_meyer_analysis": meyer_cheby.tolist(),
        "chebyshev_max_error": cheby_max_error,
        "meyer_reconstruction_error": recon_error,
        "jackson_chebyshev_coefficients": jch.tolist(),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("SGWT pipeline completed successfully.")
    print(f"  Eigenvalue range: [{eigenvalues[0]:.6f}, {eigenvalues[-1]:.6f}]")
    print(f"  Meyer frame bounds: A={frame_A:.10f}, B={frame_B:.10f}")
    print(f"  Chebyshev max error: {cheby_max_error:.6e}")
    print(f"  Meyer reconstruction error: {recon_error:.6e}")


if __name__ == "__main__":
    main()
