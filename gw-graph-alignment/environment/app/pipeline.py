#!/usr/bin/env python3
"""Multi-stage optimal transport pipeline.

Stages:
  1. Cost matrix computation from point cloud data
  2. Sinkhorn entropic regularized transport
  3. Gromov-Wasserstein structural alignment
  4. Wasserstein barycenter of multiple distributions
"""

import json
import os
import sys

sys.path.insert(0, '/app')

import numpy as np

from config import load_config
from costs import compute_cost_matrix
from sinkhorn import sinkhorn, sinkhorn_barycenter
from gw_solver import gromov_wasserstein


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    config = load_config('/app/config.json')

    print(f"[INFO] Parameters: reg={config['regularization']:.4f}, "
          f"max_iter={config['max_iter']}, tol={config['tol']}")

    # Stage 1: Cost matrix
    print("[INFO] Stage 1: Computing cost matrix")
    source = load_json('/app/data/source.json')
    target = load_json('/app/data/target.json')

    X = np.array(source['points'])
    Y = np.array(target['points'])
    a = np.array(source['weights'])
    b = np.array(target['weights'])

    M = compute_cost_matrix(X, Y, metric='sqeuclidean')
    print(f"[INFO] Cost matrix shape: {M.shape}, "
          f"range: [{M.min():.3f}, {M.max():.3f}]")

    # Stage 2: Sinkhorn OT
    print("[INFO] Stage 2: Sinkhorn transport")
    T_sink, sink_log = sinkhorn(a, b, M, config['regularization'],
                                max_iter=config['max_iter'],
                                tol=config['tol'], log=True)
    print(f"[INFO] Sinkhorn iterations: {sink_log['iterations']}, "
          f"cost: {sink_log['cost']:.6f}")

    # Stage 3: Gromov-Wasserstein
    print("[INFO] Stage 3: Gromov-Wasserstein alignment")
    graphs = load_json('/app/data/graphs.json')
    C1 = np.array(graphs['C1'])
    C2 = np.array(graphs['C2'])
    p = np.array(graphs['p'])
    q = np.array(graphs['q'])

    T_gw, gw_log = gromov_wasserstein(
        C1, C2, p, q,
        max_iter=config['gw_max_iter'],
        tol=config['gw_tol'], log=True)
    print(f"[INFO] GW iterations: {gw_log['iterations']}, "
          f"distance: {gw_log['gw_dist']:.6f}")

    # Stage 4: Wasserstein barycenter
    print("[INFO] Stage 4: Wasserstein barycenter")
    measures = load_json('/app/data/measures.json')
    distributions = [np.array(d) for d in measures['distributions']]
    bary_weights = np.array(measures['weights'])
    bary_M = np.array(measures['cost_matrix'])

    bary = sinkhorn_barycenter(distributions, bary_M,
                               config['regularization'],
                               weights=bary_weights,
                               max_iter=config['bary_max_iter'],
                               tol=config['bary_tol'])
    print(f"[INFO] Barycenter computed, sum={bary.sum():.4f}")

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    results = {
        'sinkhorn': {
            'transport_plan': T_sink.tolist(),
            'cost': float(sink_log['cost']),
            'iterations': sink_log['iterations']
        },
        'gromov_wasserstein': {
            'transport_plan': T_gw.tolist(),
            'gw_distance': float(gw_log['gw_dist']),
            'iterations': gw_log['iterations']
        },
        'barycenter': {
            'weights': bary.tolist()
        }
    }

    with open('/app/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("[INFO] Results written to /app/output/results.json")
    print("[INFO] Pipeline complete")


if __name__ == '__main__':
    main()
