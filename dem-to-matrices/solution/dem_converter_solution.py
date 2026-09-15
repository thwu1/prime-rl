
"""
DEM (Detector Error Model) to Check Matrices Converter — Solution

Parses DEM text format and converts to sparse check matrices for QEC decoders.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple
import re

import numpy as np
from scipy.sparse import csc_matrix


@dataclass
class DemMatrices:
    check_matrix: csc_matrix
    observables_matrix: csc_matrix
    edge_check_matrix: csc_matrix
    edge_observables_matrix: csc_matrix
    hyperedge_to_edge_matrix: csc_matrix
    priors: np.ndarray


def _iter_set_xor(set_list: List[List[int]]) -> FrozenSet[int]:
    """Compute symmetric difference (XOR) across a list of integer lists."""
    out = set()
    for x in set_list:
        s = set(x)
        out = (out - s) | (s - out)
    return frozenset(out)


def _dict_to_csc_matrix(
    elements_dict: Dict[int, FrozenSet[int]], shape: Tuple[int, int]
) -> csc_matrix:
    """Build a CSC matrix from {column_index: frozenset_of_row_indices}."""
    nnz = sum(len(v) for v in elements_dict.values())
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


def _parse_error_line(line: str):
    """Parse one error instruction.
    Returns (probability, detectors_list, observables_list) or None."""
    m = re.match(r"error\(([\d.eE+\-]+)\)\s+(.*)", line.strip())
    if not m:
        return None
    prob = float(m.group(1))
    targets_str = m.group(2).strip()

    components = targets_str.split("^")
    detectors: List[List[int]] = []
    observables: List[List[int]] = []
    for component in components:
        tokens = component.strip().split()
        dets: List[int] = []
        obs: List[int] = []
        for token in tokens:
            if token.startswith("D"):
                dets.append(int(token[1:]))
            elif token.startswith("L"):
                obs.append(int(token[1:]))
        detectors.append(dets)
        observables.append(obs)
    return prob, detectors, observables


def _flatten_dem_text(dem_text: str) -> List[str]:
    """Flatten DEM text by expanding repeat blocks. Returns list of error lines."""
    result: List[str] = []
    chars = dem_text.strip()
    pos = 0

    while pos < len(chars):
        # skip whitespace
        while pos < len(chars) and chars[pos] in " \t\n\r":
            pos += 1
        if pos >= len(chars):
            break

        if chars[pos:].startswith("repeat"):
            # parse: repeat <N> { <body> }
            pos += 6
            while pos < len(chars) and chars[pos] in " \t":
                pos += 1
            n_start = pos
            while pos < len(chars) and chars[pos].isdigit():
                pos += 1
            n = int(chars[n_start:pos])
            # skip to opening brace
            while pos < len(chars) and chars[pos] != "{":
                pos += 1
            pos += 1  # skip '{'
            # find matching '}'
            depth = 1
            body_start = pos
            while pos < len(chars) and depth > 0:
                if chars[pos] == "{":
                    depth += 1
                elif chars[pos] == "}":
                    depth -= 1
                pos += 1
            body = chars[body_start : pos - 1]
            body_lines = _flatten_dem_text(body)
            for _ in range(n):
                result.extend(body_lines)
        else:
            # read a single line
            line_start = pos
            while pos < len(chars) and chars[pos] != "\n":
                pos += 1
            line = chars[line_start:pos].strip()
            if line.startswith("error"):
                result.append(line)
            # skip other instruction types (detector, logical_observable, etc.)
            if pos < len(chars):
                pos += 1

    return result


def dem_text_to_check_matrices(dem_text: str) -> DemMatrices:
    """Convert DEM text into check matrices."""
    error_lines = _flatten_dem_text(dem_text)

    hyperedge_ids: Dict[FrozenSet[int], int] = {}
    edge_ids: Dict[FrozenSet[int], int] = {}
    hyperedge_obs_map: Dict[int, FrozenSet[int]] = {}
    edge_obs_map: Dict[int, FrozenSet[int]] = {}
    priors_dict: Dict[int, float] = {}
    hyperedge_to_edge: Dict[int, FrozenSet[int]] = {}

    max_detector = -1
    max_observable = -1

    for line in error_lines:
        parsed = _parse_error_line(line)
        if parsed is None:
            continue
        prob, detectors, observables = parsed

        # track dimension bounds
        for dets in detectors:
            for d in dets:
                if d > max_detector:
                    max_detector = d
        for obs in observables:
            for o in obs:
                if o > max_observable:
                    max_observable = o

        # compute hyperedge signature via symmetric difference
        hyperedge_dets = _iter_set_xor(detectors)
        hyperedge_obs = _iter_set_xor(observables)

        # assign or retrieve hyperedge ID
        if hyperedge_dets not in hyperedge_ids:
            hyperedge_ids[hyperedge_dets] = len(hyperedge_ids)
            priors_dict[hyperedge_ids[hyperedge_dets]] = 0.0
        hid = hyperedge_ids[hyperedge_dets]
        hyperedge_obs_map[hid] = hyperedge_obs

        # accumulate probability (independent channel combination)
        p_old = priors_dict[hid]
        priors_dict[hid] = p_old * (1 - prob) + prob * (1 - p_old)

        # decompose into edges
        eids: List[int] = []
        for i in range(len(detectors)):
            e_dets = frozenset(detectors[i])
            e_obs = frozenset(observables[i])

            if len(e_dets) > 2:
                # skip undecomposable edge components
                continue

            if e_dets not in edge_ids:
                edge_ids[e_dets] = len(edge_ids)
            eid = edge_ids[e_dets]
            eids.append(eid)
            edge_obs_map[eid] = e_obs

        # record edge decomposition (first occurrence only)
        if hid not in hyperedge_to_edge:
            hyperedge_to_edge[hid] = frozenset(eids)

    num_detectors = max_detector + 1 if max_detector >= 0 else 0
    num_observables = max_observable + 1 if max_observable >= 0 else 0
    num_hyperedges = len(hyperedge_ids)
    num_edges = len(edge_ids)

    check_matrix = _dict_to_csc_matrix(
        {v: k for k, v in hyperedge_ids.items()},
        shape=(num_detectors, num_hyperedges),
    )
    observables_matrix = _dict_to_csc_matrix(
        hyperedge_obs_map, shape=(num_observables, num_hyperedges)
    )
    priors = np.zeros(num_hyperedges)
    for i, p in priors_dict.items():
        priors[i] = p
    hyperedge_to_edge_matrix = _dict_to_csc_matrix(
        hyperedge_to_edge, shape=(num_edges, num_hyperedges)
    )
    edge_check_matrix = _dict_to_csc_matrix(
        {v: k for k, v in edge_ids.items()}, shape=(num_detectors, num_edges)
    )
    edge_observables_matrix = _dict_to_csc_matrix(
        edge_obs_map, shape=(num_observables, num_edges)
    )
    return DemMatrices(
        check_matrix=check_matrix,
        observables_matrix=observables_matrix,
        edge_check_matrix=edge_check_matrix,
        edge_observables_matrix=edge_observables_matrix,
        hyperedge_to_edge_matrix=hyperedge_to_edge_matrix,
        priors=priors,
    )
