#!/usr/bin/env python3

"""SGWT Pipeline — spectral graph wavelet analysis."""

import json
import numpy as np
from scipy import sparse

from sgwt_lib.graph import build_laplacian, compute_fourier_basis
from sgwt_lib.scales import compute_log_scales
from sgwt_lib.kernels import meyer_kernel, mexicanhat_lowpass, mexicanhat_bandpass
from sgwt_lib.filtering import (
    exact_analysis, exact_synthesis, compute_cheby_coeff, cheby_op
)
from sgwt_lib.frames import compute_frame_bounds
from sgwt_lib.jackson import compute_jackson_cheby_coeff


def main():
    with open("/app/graph_spec.json") as f:
        spec = json.load(f)

    N = spec["n_nodes"]
    signal = np.array(spec["signal"])

    # Build graph and compute Fourier basis
    L = build_laplacian(N, spec["edges"])
    eigenvalues, eigenvectors = compute_fourier_basis(L)
    lmax = float(eigenvalues[-1])

    # Log-spaced scales for MexicanHat
    lpfactor = spec["mexicanhat_lpfactor"]
    lmin = lmax / lpfactor
    mexicanhat_nf = spec["mexicanhat_nf"]
    log_scales = compute_log_scales(lmin, lmax, mexicanhat_nf - 1)

    # Meyer filterbank — dyadic scales
    meyer_nf = spec["meyer_nf"]
    meyer_scales = (4.0 / (3.0 * lmax)) * np.power(
        2.0, np.arange(meyer_nf - 2, -1, -1)
    )

    meyer_responses = np.zeros((meyer_nf, N))
    meyer_responses[0] = meyer_kernel(
        meyer_scales[0] * eigenvalues, "scaling_function"
    )
    for i in range(meyer_nf - 1):
        meyer_responses[i + 1] = meyer_kernel(
            meyer_scales[i] * eigenvalues, "wavelet"
        )

    # Exact Meyer analysis
    meyer_exact = exact_analysis(eigenvalues, eigenvectors, signal, meyer_responses)

    # Meyer frame bounds
    frame_A, frame_B = compute_frame_bounds(meyer_responses)

    # MexicanHat filterbank
    mh_responses = np.zeros((mexicanhat_nf, N))
    mh_responses[0] = mexicanhat_lowpass(eigenvalues, lmin)
    for i in range(mexicanhat_nf - 1):
        mh_responses[i + 1] = mexicanhat_bandpass(eigenvalues, log_scales[i])

    # Exact MexicanHat analysis
    mexicanhat_exact = exact_analysis(
        eigenvalues, eigenvectors, signal, mh_responses
    )

    # Chebyshev approximation for Meyer
    cheby_order = spec["chebyshev_order"]
    L_sparse = sparse.csr_matrix(L)

    meyer_cheby_coeffs = []
    for i in range(meyer_nf):
        if i == 0:
            kfn = lambda x, s=meyer_scales[0]: meyer_kernel(
                s * x, "scaling_function"
            )
        else:
            idx = i - 1
            kfn = lambda x, s=meyer_scales[idx]: meyer_kernel(s * x, "wavelet")
        c = compute_cheby_coeff(kfn, cheby_order, lmax)
        meyer_cheby_coeffs.append(c)

    c_all = np.array(meyer_cheby_coeffs)
    meyer_cheby = cheby_op(L_sparse, c_all, signal, lmax)

    cheby_max_error = float(np.max(np.abs(meyer_exact - meyer_cheby)))

    # Meyer reconstruction via analysis-synthesis
    reconstructed = exact_synthesis(
        eigenvalues, eigenvectors, meyer_exact, meyer_responses
    )
    recon_error = float(np.linalg.norm(signal - reconstructed))

    # Jackson-Chebyshev coefficients
    jackson_bounds = list(spec["jackson_filter_bounds"])
    jackson_m = spec["jackson_m"]
    jch = compute_jackson_cheby_coeff(jackson_bounds, [0.0, lmax], jackson_m)

    # Write results
    results = {
        "eigenvalues": eigenvalues.tolist(),
        "log_scales": log_scales.tolist(),
        "meyer_analysis_exact": meyer_exact.tolist(),
        "meyer_frame_bounds": [float(frame_A), float(frame_B)],
        "mexicanhat_analysis_exact": mexicanhat_exact.tolist(),
        "chebyshev_meyer_analysis": meyer_cheby.tolist(),
        "chebyshev_max_error": cheby_max_error,
        "meyer_reconstruction_error": recon_error,
        "jackson_chebyshev_coefficients": jch.tolist(),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
