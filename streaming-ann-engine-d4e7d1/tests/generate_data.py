#!/usr/bin/env python3
"""Generate deterministic test data for the streaming ANN engine task."""

import numpy as np
import os
import yaml


def write_fbin(filepath, data):
    """Write float32 vectors in BigANN .fbin format."""
    n, d = data.shape
    with open(filepath, 'wb') as f:
        np.array([n, d], dtype='uint32').tofile(f)
        data.astype('float32').tofile(f)


def main():
    np.random.seed(42)
    num_base = 10000
    num_queries = 200
    dims = 20

    os.makedirs('/app/data', exist_ok=True)

    # Generate clustered base vectors (50 clusters)
    num_clusters = 50
    centers = np.random.randn(num_clusters, dims).astype(np.float32) * 10.0
    assignments = np.random.randint(0, num_clusters, num_base)
    base = centers[assignments] + np.random.randn(num_base, dims).astype(np.float32) * 0.5
    base = base.astype(np.float32)

    # Generate query vectors from same cluster distribution
    query_assignments = np.random.randint(0, num_clusters, num_queries)
    queries = centers[query_assignments] + np.random.randn(num_queries, dims).astype(np.float32) * 0.5
    queries = queries.astype(np.float32)

    write_fbin('/app/data/base.fbin', base)
    write_fbin('/app/data/queries.fbin', queries)

    # Write runbook: 11 steps with insert, delete, replace, and 4 search checkpoints
    #
    # Step 1: insert [0, 5000)
    # Step 2: SEARCH  -> active = {0..4999}, |active| = 5000
    # Step 3: delete [1500, 3000)
    # Step 4: insert [5000, 7000)
    # Step 5: SEARCH  -> active = {0..1499, 3000..6999}, |active| = 5500
    # Step 6: replace tags [0, 500) -> ids [7000, 7500)
    # Step 7: delete [4000, 5000)
    # Step 8: SEARCH  -> active = {0..1499, 3000..3999, 5000..6999}, |active| = 4500
    #           (tags 0..499 now point to vectors 7000..7499)
    # Step 9: insert [7500, 10000)
    # Step 10: delete [5500, 6500)
    # Step 11: SEARCH -> active = {0..1499, 3000..3999, 5000..5499, 6500..6999, 7500..9999}, |active| = 5500
    runbook = {
        'streaming_test': {
            'max_pts': 8000,
            1: {'operation': 'insert', 'start': 0, 'end': 5000},
            2: {'operation': 'search'},
            3: {'operation': 'delete', 'start': 1500, 'end': 3000},
            4: {'operation': 'insert', 'start': 5000, 'end': 7000},
            5: {'operation': 'search'},
            6: {'operation': 'replace',
                'tags_start': 0, 'tags_end': 500,
                'ids_start': 7000, 'ids_end': 7500},
            7: {'operation': 'delete', 'start': 4000, 'end': 5000},
            8: {'operation': 'search'},
            9: {'operation': 'insert', 'start': 7500, 'end': 10000},
            10: {'operation': 'delete', 'start': 5500, 'end': 6500},
            11: {'operation': 'search'},
        }
    }

    with open('/app/data/runbook.yaml', 'w') as f:
        yaml.dump(runbook, f, default_flow_style=False, sort_keys=True)


if __name__ == '__main__':
    main()
