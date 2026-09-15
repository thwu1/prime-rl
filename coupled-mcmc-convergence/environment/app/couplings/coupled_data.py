"""Data class for returning coupled MCMC samples."""
from dataclasses import dataclass
import numpy as np

__all__ = ["CoupledData"]


@dataclass
class CoupledData:
    """Data store for coupled MCMC sampling.

    Stores samples, acceptance indicators, meeting times, and metadata
    for coupled Markov chain experiments.
    """

    x: np.ndarray
    y: np.ndarray
    x_accept: np.ndarray
    y_accept: np.ndarray
    meeting_time: np.ndarray
    lag: int
    iters: int
    dim: int
    chains: int
