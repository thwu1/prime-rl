#!/usr/bin/env python3

"""
Compute the code distance of a QEC code from its Stim detector error model.

The code distance is the minimum number of independent error mechanisms whose
combined effect flips at least one logical observable without triggering any
detector.

Algorithm:
  For each logical observable L, we build a "doubled graph" where every node
  (detector or boundary) exists in two layers (0 and 1).  Edges whose error
  mechanism flips L cross between layers; edges that do not flip L stay within
  their layer.  The minimum-weight odd-parity cycle for L equals the shortest
  path from (v, 0) to (v, 1) for any node v.  BFS from every node in layer 0
  finds this.  The overall code distance is the minimum across all observables.
"""

import sys
from collections import defaultdict, deque

import stim


# Sentinel for the implicit boundary node (errors with 0 or 1 detectors).
BOUNDARY = -1


def parse_dem(path):
    """Return a list of (frozenset[det_ids], frozenset[obs_ids]) tuples."""
    with open(path) as f:
        dem = stim.DetectorErrorModel(f.read())

    errors = []
    for instruction in dem.flattened():
        if instruction.type == "error":
            dets = set()
            obs = set()
            for t in instruction.targets_copy():
                if t.is_relative_detector_id():
                    dets.symmetric_difference_update({t.val})
                elif t.is_logical_observable_id():
                    obs.symmetric_difference_update({t.val})
                # separator targets (^) are silently skipped; the XOR
                # via symmetric_difference handles multi-chunk errors.
            if dets or obs:
                errors.append((frozenset(dets), frozenset(obs)))
    return errors


def _build_doubled_adj(errors, obs_id):
    """Build adjacency list for the doubled graph targeting *obs_id*."""
    adj = defaultdict(list)

    for dets, obs in errors:
        flips = obs_id in obs
        det_list = sorted(dets)
        n = len(det_list)

        if n == 0:
            if flips:
                adj[(BOUNDARY, 0)].append((BOUNDARY, 1))
                adj[(BOUNDARY, 1)].append((BOUNDARY, 0))
            # non-flipping boundary self-loop is useless
        elif n == 1:
            (d,) = det_list
            if flips:
                adj[(BOUNDARY, 0)].append((d, 1))
                adj[(d, 1)].append((BOUNDARY, 0))
                adj[(BOUNDARY, 1)].append((d, 0))
                adj[(d, 0)].append((BOUNDARY, 1))
            else:
                adj[(BOUNDARY, 0)].append((d, 0))
                adj[(d, 0)].append((BOUNDARY, 0))
                adj[(BOUNDARY, 1)].append((d, 1))
                adj[(d, 1)].append((BOUNDARY, 1))
        elif n == 2:
            d1, d2 = det_list
            if flips:
                adj[(d1, 0)].append((d2, 1))
                adj[(d2, 1)].append((d1, 0))
                adj[(d1, 1)].append((d2, 0))
                adj[(d2, 0)].append((d1, 1))
            else:
                adj[(d1, 0)].append((d2, 0))
                adj[(d2, 0)].append((d1, 0))
                adj[(d1, 1)].append((d2, 1))
                adj[(d2, 1)].append((d1, 1))
        # errors touching >2 detectors are non-graphlike; skip them.

    return adj


def _bfs_distance(adj, start, target):
    """BFS shortest-path distance from *start* to *target* in *adj*, or None."""
    if start == target:
        return 0
    visited = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        d = visited[node]
        for nb in adj[node]:
            if nb not in visited:
                nd = d + 1
                if nb == target:
                    return nd
                visited[nb] = nd
                queue.append(nb)
    return None


def compute_distance(errors):
    """Return the code distance, or -1 if no observable exists."""
    all_obs = set()
    for _, obs in errors:
        all_obs |= obs
    if not all_obs:
        return -1

    best = float("inf")

    for obs_id in all_obs:
        adj = _build_doubled_adj(errors, obs_id)

        # Collect all distinct original-graph nodes present in layer 0.
        nodes = {node for (node, layer) in adj if layer == 0}

        for v in nodes:
            d = _bfs_distance(adj, (v, 0), (v, 1))
            if d is not None and d < best:
                best = d
                if best == 1:
                    return 1  # can't do better

    return best if best < float("inf") else -1


def main():
    if len(sys.argv) != 2:
        print("Usage: compute_distance.py <dem_file>", file=sys.stderr)
        sys.exit(1)

    errors = parse_dem(sys.argv[1])
    print(compute_distance(errors))


if __name__ == "__main__":
    main()
