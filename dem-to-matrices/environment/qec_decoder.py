
"""
Quantum Error Correction Decoding Pipeline

This module converts stim DetectorErrorModel objects to sparse check matrices
and decodes syndromes using belief propagation with ordered statistics decoding.
"""

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csc_matrix
import stim


@dataclass
class DemMatrices:
    """Sparse matrices derived from a Detector Error Model.

    Attributes
    ----------
    check_matrix : csc_matrix, shape (num_detectors, num_hyperedges)
        Which detectors each hyperedge triggers.
    observables_matrix : csc_matrix, shape (num_observables, num_hyperedges)
        Which logical observables each hyperedge flips.
    edge_check_matrix : csc_matrix, shape (num_detectors, num_edges)
        Which detectors each individual edge triggers.
    edge_observables_matrix : csc_matrix, shape (num_observables, num_edges)
        Which logical observables each individual edge flips.
    hyperedge_to_edge_matrix : csc_matrix, shape (num_edges, num_hyperedges)
        Which edges compose each hyperedge.
    priors : np.ndarray, shape (num_hyperedges,)
        Combined error probability for each hyperedge.
    """

    check_matrix: csc_matrix
    observables_matrix: csc_matrix
    edge_check_matrix: csc_matrix
    edge_observables_matrix: csc_matrix
    hyperedge_to_edge_matrix: csc_matrix
    priors: np.ndarray


def detector_error_model_to_check_matrices(
    dem: stim.DetectorErrorModel,
    allow_undecomposed_hyperedges: bool = True,
) -> DemMatrices:
    """Convert a stim DetectorErrorModel into check matrices.

    Parameters
    ----------
    dem : stim.DetectorErrorModel
        The detector error model to convert.
    allow_undecomposed_hyperedges : bool
        If True, hyperedge components with >2 detectors are skipped
        in the edge decomposition without raising an exception.

    Returns
    -------
    DemMatrices
    """
    raise NotImplementedError("Implement this function")


def build_decoder(
    dem_matrices: DemMatrices,
    max_iter: int = 30,
    bp_method: str = "product_sum",
    osd_order: int = 60,
    osd_method: str = "osd_cs",
):
    """Build a BP+OSD decoder from DemMatrices.

    Parameters
    ----------
    dem_matrices : DemMatrices
    max_iter : int
        Maximum belief propagation iterations.
    bp_method : str
        BP update method.
    osd_order : int
        OSD order.
    osd_method : str
        OSD method.

    Returns
    -------
    A configured decoder with a .decode(syndrome) method.
    """
    raise NotImplementedError("Implement this function")


def decode_batch(
    decoder,
    dem_matrices: DemMatrices,
    detection_events: np.ndarray,
) -> np.ndarray:
    """Decode detection events into predicted observable flips.

    Parameters
    ----------
    decoder : object
        A decoder from build_decoder with a .decode(syndrome) method.
    dem_matrices : DemMatrices
        The matrices used to build the decoder.
    detection_events : np.ndarray, shape (num_shots, num_detectors)
        Binary array of detection events.

    Returns
    -------
    np.ndarray, shape (num_shots, num_observables), dtype np.uint8
        Predicted observable flips per shot.
    """
    raise NotImplementedError("Implement this function")
