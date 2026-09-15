
"""
Quantum Error Correction Decoding Pipeline — Solution

Converts stim DetectorErrorModel objects to sparse check matrices and decodes
syndromes using belief propagation with ordered statistics decoding via ldpc.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

import numpy as np
from scipy.sparse import csc_matrix
import stim


@dataclass
class DemMatrices:
    check_matrix: csc_matrix
    observables_matrix: csc_matrix
    edge_check_matrix: csc_matrix
    edge_observables_matrix: csc_matrix
    hyperedge_to_edge_matrix: csc_matrix
    priors: np.ndarray


def _iter_set_xor(set_list: List[FrozenSet[int]]) -> FrozenSet[int]:
    out = set()
    for s in set_list:
        out = out.symmetric_difference(s)
    return frozenset(out)


def _dict_to_csc_matrix(
    elements_dict: Dict[int, FrozenSet[int]], shape: Tuple[int, int]
) -> csc_matrix:
    nnz = sum(len(v) for v in elements_dict.values())
    if nnz == 0:
        return csc_matrix(shape, dtype=np.uint8)
    data = np.ones(nnz, dtype=np.uint8)
    row_ind = np.zeros(nnz, dtype=np.int64)
    col_ind = np.zeros(nnz, dtype=np.int64)
    i = 0
    for col, rows in elements_dict.items():
        for row in rows:
            row_ind[i] = row
            col_ind[i] = col
            i += 1
    return csc_matrix((data, (row_ind, col_ind)), shape=shape)


def detector_error_model_to_check_matrices(
    dem: stim.DetectorErrorModel,
    allow_undecomposed_hyperedges: bool = True,
) -> DemMatrices:
    hyperedge_ids: Dict[FrozenSet[int], int] = {}
    edge_ids: Dict[FrozenSet[int], int] = {}
    hyperedge_obs_map: Dict[int, FrozenSet[int]] = {}
    edge_obs_map: Dict[int, FrozenSet[int]] = {}
    priors_dict: Dict[int, float] = {}
    hyperedge_to_edge: Dict[int, FrozenSet[int]] = {}

    for instruction in dem.flattened():
        if instruction.type != "error":
            continue

        p = instruction.args_copy()[0]

        dets: List[List[int]] = [[]]
        obs: List[List[int]] = [[]]
        for t in instruction.targets_copy():
            if t.is_relative_detector_id():
                dets[-1].append(t.val)
            elif t.is_logical_observable_id():
                obs[-1].append(t.val)
            elif t.is_separator():
                dets.append([])
                obs.append([])

        hyperedge_dets = _iter_set_xor([frozenset(d) for d in dets])
        hyperedge_obs = _iter_set_xor([frozenset(o) for o in obs])

        if hyperedge_dets not in hyperedge_ids:
            hyperedge_ids[hyperedge_dets] = len(hyperedge_ids)
            priors_dict[hyperedge_ids[hyperedge_dets]] = 0.0
        hid = hyperedge_ids[hyperedge_dets]
        hyperedge_obs_map[hid] = hyperedge_obs

        priors_dict[hid] = priors_dict[hid] * (1 - p) + p * (1 - priors_dict[hid])

        eids: List[int] = []
        for i in range(len(dets)):
            e_dets = frozenset(dets[i])
            e_obs = frozenset(obs[i])
            if len(e_dets) > 2:
                if not allow_undecomposed_hyperedges:
                    raise ValueError(
                        "Undecomposed hyperedge with >2 detectors found. "
                        "Set decompose_errors=True when calling circuit.detector_error_model()."
                    )
                continue
            if e_dets not in edge_ids:
                edge_ids[e_dets] = len(edge_ids)
            eid = edge_ids[e_dets]
            eids.append(eid)
            edge_obs_map[eid] = e_obs

        if hid not in hyperedge_to_edge:
            hyperedge_to_edge[hid] = frozenset(eids)

    n_he = len(hyperedge_ids)
    n_edge = len(edge_ids)

    check_matrix = _dict_to_csc_matrix(
        {v: k for k, v in hyperedge_ids.items()},
        shape=(dem.num_detectors, n_he),
    )
    observables_matrix = _dict_to_csc_matrix(
        hyperedge_obs_map, shape=(dem.num_observables, n_he)
    )
    priors = np.zeros(n_he)
    for i, p in priors_dict.items():
        priors[i] = p
    hyperedge_to_edge_matrix = _dict_to_csc_matrix(
        hyperedge_to_edge, shape=(n_edge, n_he)
    )
    edge_check_matrix = _dict_to_csc_matrix(
        {v: k for k, v in edge_ids.items()}, shape=(dem.num_detectors, n_edge)
    )
    edge_observables_matrix = _dict_to_csc_matrix(
        edge_obs_map, shape=(dem.num_observables, n_edge)
    )
    return DemMatrices(
        check_matrix=check_matrix,
        observables_matrix=observables_matrix,
        edge_check_matrix=edge_check_matrix,
        edge_observables_matrix=edge_observables_matrix,
        hyperedge_to_edge_matrix=hyperedge_to_edge_matrix,
        priors=priors,
    )


def build_decoder(
    dem_matrices: DemMatrices,
    max_iter: int = 30,
    bp_method: str = "product_sum",
    osd_order: int = 60,
    osd_method: str = "osd_cs",
):
    channel_probs = np.clip(dem_matrices.priors, 1e-15, 1 - 1e-15)
    h_shape = dem_matrices.check_matrix.shape
    max_osd_order = h_shape[1] - h_shape[0]
    effective_osd_order = max(0, min(osd_order, max_osd_order))

    try:
        from ldpc.bposd_decoder import BpOsdDecoder

        return BpOsdDecoder(
            pcm=dem_matrices.check_matrix,
            error_channel=list(channel_probs),
            max_iter=max_iter,
            bp_method=bp_method,
            osd_order=effective_osd_order,
            osd_method=osd_method,
            input_vector_type="syndrome",
        )
    except ImportError:
        from ldpc import BpOsdDecoder

        return BpOsdDecoder(
            dem_matrices.check_matrix,
            channel_probs=list(channel_probs),
            max_iter=max_iter,
            bp_method=bp_method,
            osd_order=effective_osd_order,
            osd_method=osd_method,
        )


def decode_batch(
    decoder,
    dem_matrices: DemMatrices,
    detection_events: np.ndarray,
) -> np.ndarray:
    n_shots = detection_events.shape[0]
    n_obs = dem_matrices.observables_matrix.shape[0]
    predictions = np.zeros((n_shots, n_obs), dtype=np.uint8)

    for i in range(n_shots):
        syndrome = detection_events[i].astype(np.uint8)
        correction = decoder.decode(syndrome)
        pred = (dem_matrices.observables_matrix @ correction) % 2
        predictions[i] = np.asarray(pred).flatten().astype(np.uint8)

    return predictions
