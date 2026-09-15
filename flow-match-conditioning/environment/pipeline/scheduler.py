"""Noise schedule computation for flow-matching diffusion inference."""

import numpy as np


def compute_sigmas(num_steps, shift=1.0):
    """Compute the shifted sigma schedule for flow-matching denoising.

    Returns an array of sigma values from high noise to low noise.
    The shifted schedule concentrates more capacity at high noise levels:

        sigma(t) = shift * t / (1 + (shift - 1) * t)

    where t is linearly spaced from 1.0 down to 1/num_steps.
    """
    t = np.linspace(1.0, 1.0 / num_steps, num_steps)
    sigmas = t / (1.0 + (shift - 1.0) * t)
    return sigmas
