"""
QEC Decoder Pipeline — DEM-to-matrices converter and syndrome decoder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

import networkx as nx
import numpy as np
import stim
from scipy.sparse import csc_matrix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_set_xor(set_list: List[List[int]]) -> FrozenSet[int]:
    """Symmetric difference (XOR) across a list of int-lists."""
    out: set = set()
    for x in set_list:
        s = set(x)
        out = (out - s) | (s - out)
    return frozenset(out)


def _dict_to_csc(
    elements: Dict[int, FrozenSet[int]], shape: Tuple[int, int]
) -> csc_matrix:
    """Build a CSC matrix from {col: frozenset_of_row_indices}."""
    nnz = sum(len(v) for v in elements.values())
    data = np.ones(nnz, dtype=np.uint8)
    row_ind = np.zeros(nnz, dtype=np.int64)
    col_ind = np.zeros(nnz, dtype=np.int64)
    i = 0
    for col, rows in elements.items():
        for row in rows:
            row_ind[i] = row
            col_ind[i] = col
            i += 1
    return csc_matrix((data, (row_ind, col_ind)), shape=shape)


# ---------------------------------------------------------------------------
# DemMatrices
# ---------------------------------------------------------------------------

@dataclass
class DemMatrices:
    check_matrix: csc_matrix
    observables_matrix: csc_matrix
    edge_check_matrix: csc_matrix
    edge_observables_matrix: csc_matrix
    hyperedge_to_edge_matrix: csc_matrix
    priors: np.ndarray


def dem_to_matrices(
    dem: stim.DetectorErrorModel,
    allow_undecomposed_hyperedges: bool = True,
) -> DemMatrices:
    """Convert a ``stim.DetectorErrorModel`` into sparse check matrices."""

    hyperedge_ids: Dict[FrozenSet[int], int] = {}
    edge_ids: Dict[FrozenSet[int], int] = {}
    hyperedge_obs_map: Dict[int, FrozenSet[int]] = {}
    edge_obs_map: Dict[int, FrozenSet[int]] = {}
    priors_dict: Dict[int, float] = {}
    hyperedge_to_edge: Dict[int, FrozenSet[int]] = {}

    def _handle_error(
        prob: float,
        detectors: List[List[int]],
        observables: List[List[int]],
    ) -> None:
        h_dets = _iter_set_xor(detectors)
        h_obs = _iter_set_xor(observables)

        if h_dets not in hyperedge_ids:
            hyperedge_ids[h_dets] = len(hyperedge_ids)
            priors_dict[hyperedge_ids[h_dets]] = 0.0
        hid = hyperedge_ids[h_dets]
        hyperedge_obs_map[hid] = h_obs
        priors_dict[hid] = priors_dict[hid] * (1 - prob) + prob * (1 - priors_dict[hid])

        eids: List[int] = []
        for i in range(len(detectors)):
            e_dets = frozenset(detectors[i])
            e_obs = frozenset(observables[i])
            if len(e_dets) > 2:
                if not allow_undecomposed_hyperedges:
                    raise ValueError(
                        "Undecomposed hyperedge found. Use decompose_errors=True."
                    )
                continue
            if e_dets not in edge_ids:
                edge_ids[e_dets] = len(edge_ids)
            eid = edge_ids[e_dets]
            eids.append(eid)
            edge_obs_map[eid] = e_obs

        if hid not in hyperedge_to_edge:
            hyperedge_to_edge[hid] = frozenset(eids)

    for instruction in dem.flattened():
        if instruction.type == "error":
            dets: List[List[int]] = [[]]
            frames: List[List[int]] = [[]]
            p = instruction.args_copy()[0]
            for t in instruction.targets_copy():
                if t.is_relative_detector_id():
                    dets[-1].append(t.val)
                elif t.is_logical_observable_id():
                    frames[-1].append(t.val)
                elif t.is_separator():
                    dets.append([])
                    frames.append([])
            _handle_error(p, dets, frames)

    check_matrix = _dict_to_csc(
        {v: k for k, v in hyperedge_ids.items()},
        shape=(dem.num_detectors, len(hyperedge_ids)),
    )
    observables_matrix = _dict_to_csc(
        hyperedge_obs_map,
        shape=(dem.num_observables, len(hyperedge_ids)),
    )
    priors = np.zeros(len(hyperedge_ids))
    for i, p in priors_dict.items():
        priors[i] = p
    edge_check_matrix = _dict_to_csc(
        {v: k for k, v in edge_ids.items()},
        shape=(dem.num_detectors, len(edge_ids)),
    )
    edge_observables_matrix = _dict_to_csc(
        edge_obs_map,
        shape=(dem.num_observables, len(edge_ids)),
    )
    hyperedge_to_edge_matrix = _dict_to_csc(
        hyperedge_to_edge,
        shape=(len(edge_ids), len(hyperedge_ids)),
    )
    return DemMatrices(
        check_matrix=check_matrix,
        observables_matrix=observables_matrix,
        edge_check_matrix=edge_check_matrix,
        edge_observables_matrix=edge_observables_matrix,
        hyperedge_to_edge_matrix=hyperedge_to_edge_matrix,
        priors=priors,
    )


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

class Decoder:
    """Syndrome decoder for quantum error correcting codes."""

    def __init__(self, dem: stim.DetectorErrorModel) -> None:
        self.num_detectors = dem.num_detectors
        self.num_observables = dem.num_observables
        self.boundary = self.num_detectors  # virtual boundary node index
        num_nodes = self.num_detectors + 1

        # ── Build detector graph from DEM edges ──────────────────────
        # adj[(u,v)] = (weight, obs_frozenset)  — minimum weight kept
        adj: Dict[Tuple[int, int], Tuple[float, FrozenSet[int]]] = {}

        for instruction in dem.flattened():
            if instruction.type != "error":
                continue
            p = instruction.args_copy()[0]
            if p <= 0.0 or p >= 1.0:
                continue
            w = math.log((1.0 - p) / p)
            if w < 0:
                w = 0.0

            # Split targets into components by separator
            groups_dets: List[List[int]] = [[]]
            groups_obs: List[List[int]] = [[]]
            for t in instruction.targets_copy():
                if t.is_separator():
                    groups_dets.append([])
                    groups_obs.append([])
                elif t.is_relative_detector_id():
                    groups_dets[-1].append(t.val)
                elif t.is_logical_observable_id():
                    groups_obs[-1].append(t.val)

            for dets, obs in zip(groups_dets, groups_obs):
                if len(dets) == 0 or len(dets) > 2:
                    continue
                if len(dets) == 1:
                    u, v = dets[0], self.boundary
                else:
                    u, v = dets[0], dets[1]
                key = (min(u, v), max(u, v))
                obs_set = frozenset(obs)
                if key not in adj or w < adj[key][0]:
                    adj[key] = (w, obs_set)

        # ── All-pairs shortest paths (Floyd-Warshall) ────────────────
        n_obs = max(self.num_observables, 1)
        self._dist = np.full((num_nodes, num_nodes), np.inf)
        self._obs = np.zeros((num_nodes, num_nodes, n_obs), dtype=np.uint8)

        for i in range(num_nodes):
            self._dist[i][i] = 0.0

        for (u, v), (w, obs_set) in adj.items():
            if w < self._dist[u][v]:
                self._dist[u][v] = w
                self._dist[v][u] = w
                obs_vec = np.zeros(n_obs, dtype=np.uint8)
                for o in obs_set:
                    if o < n_obs:
                        obs_vec[o] = 1
                self._obs[u][v] = obs_vec
                self._obs[v][u] = obs_vec

        for k in range(num_nodes):
            for i in range(num_nodes):
                d_ik = self._dist[i][k]
                if d_ik == np.inf:
                    continue
                for j in range(num_nodes):
                    new_d = d_ik + self._dist[k][j]
                    if new_d < self._dist[i][j]:
                        self._dist[i][j] = new_d
                        self._obs[i][j] = (
                            self._obs[i][k] + self._obs[k][j]
                        ) % 2

    def decode(self, syndrome: np.ndarray) -> np.ndarray:
        triggered = np.where(syndrome)[0].tolist()

        if len(triggered) == 0:
            return np.zeros(self.num_observables, dtype=np.uint8)

        # Odd count → include virtual boundary
        if len(triggered) % 2 == 1:
            triggered.append(self.boundary)

        # Complete graph on triggered nodes
        G = nx.Graph()
        for idx_i in range(len(triggered)):
            for idx_j in range(idx_i + 1, len(triggered)):
                u, v = triggered[idx_i], triggered[idx_j]
                G.add_edge(u, v, weight=self._dist[u][v])

        matching = nx.min_weight_matching(G)

        prediction = np.zeros(self.num_observables, dtype=np.uint8)
        for u, v in matching:
            prediction = (prediction + self._obs[u][v][: self.num_observables]) % 2

        return prediction

    def decode_batch(self, shots: np.ndarray) -> np.ndarray:
        predictions = np.zeros(
            (shots.shape[0], self.num_observables), dtype=np.uint8
        )
        for i in range(shots.shape[0]):
            predictions[i] = self.decode(shots[i])
        return predictions
