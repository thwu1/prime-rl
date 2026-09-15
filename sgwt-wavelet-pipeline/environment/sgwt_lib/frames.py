"""Frame bounds estimation for wavelet filterbanks."""
import numpy as np


def compute_frame_bounds(kernel_responses):
    """Compute the frame bounds A and B for a filterbank.

    For a tight frame A = B, which guarantees perfect signal
    reconstruction via analysis followed by synthesis.

    Parameters
    ----------
    kernel_responses : ndarray (Nf, N)
        Filterbank kernels evaluated at the Laplacian eigenvalues.

    Returns
    -------
    A : float
        Lower frame bound.
    B : float
        Upper frame bound.
    """
    sum_val = np.sum(np.abs(kernel_responses), axis=0)
    return float(np.min(sum_val)), float(np.max(sum_val))
