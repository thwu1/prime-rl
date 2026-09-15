"""
DEM-to-matrices conversion for quantum error correction decoding.

Converts a stim.DetectorErrorModel into sparse matrix representations
needed for belief propagation and other QEC decoding algorithms.
"""
from dataclasses import dataclass

import stim


@dataclass
class DemMatrices:
    """Matrix representations of a stim DetectorErrorModel.

    All matrix attributes must be scipy.sparse.csc_matrix with uint8 entries.
    Priors is a 1-D numpy float64 array.

    Attributes:
        check_matrix: Shape (num_detectors, num_hyperedges).
            Entry [d, h] is 1 iff detector d is in the support of hyperedge h.
        observables_matrix: Shape (num_observables, num_hyperedges).
            Entry [o, h] is 1 iff observable o is flipped by hyperedge h.
        edge_check_matrix: Shape (num_detectors, num_edges).
            Like check_matrix but only for individual edge components
            (each involving at most 2 detectors).
        edge_observables_matrix: Shape (num_observables, num_edges).
            Like observables_matrix but for individual edge components.
        hyperedge_to_edge_matrix: Shape (num_edges, num_hyperedges).
            Entry [e, h] is 1 iff edge e is part of the decomposition
            of hyperedge h.
        priors: numpy.ndarray of shape (num_hyperedges,).
            Prior error probability for each hyperedge.
    """
    check_matrix: object
    observables_matrix: object
    edge_check_matrix: object
    edge_observables_matrix: object
    hyperedge_to_edge_matrix: object
    priors: object


def detector_error_model_to_check_matrices(
    dem: stim.DetectorErrorModel,
    allow_undecomposed_hyperedges: bool = True,
) -> DemMatrices:
    """
    Convert a stim.DetectorErrorModel into a DemMatrices object.

    Each ``error`` instruction in the DEM defines a hyperedge whose detector
    support is the symmetric difference of detector sets across
    ``^``-separated components.  Individual components (each with at most 2
    detectors) are *edges* that form the decomposition of the hyperedge.

    Parameters
    ----------
    dem : stim.DetectorErrorModel
        A stim detector error model to convert.
    allow_undecomposed_hyperedges : bool
        If False, raise ``ValueError`` when an error component involves more
        than 2 detectors (i.e. is not decomposed into edges).  If True
        (default), such components are included as hyperedges but omitted
        from the edge decomposition.

    Returns
    -------
    DemMatrices
        Sparse matrix representations of the detector error model.
    """
    raise NotImplementedError("Implement this function")
