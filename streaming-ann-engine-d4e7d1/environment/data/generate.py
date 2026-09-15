#!/usr/bin/env python3
"""Generate deterministic test data for the streaming ANN search task.

Produces:
  /app/data/base.fbin       — 15 000 float32 vectors, 32 dimensions
  /app/data/queries.fbin    — 100 float32 query vectors, 32 dimensions
  /app/data/metadata.bin    — per-vector category labels + per-dimension weights
  /app/data/runbook.yaml    — streaming operations workload
  /app/data/config.json     — HNSW and evaluation parameters

"""

import json
import os

import numpy as np
import yaml


# ── Binary writers ───────────────────────────────────────────────────────

def write_fbin(filepath, data):
    """Write float32 vectors in BigANN .fbin format.

    Layout:  [uint32 num_vectors] [uint32 dim] [float32 * num_vectors * dim]
    """
    data = np.ascontiguousarray(data, dtype=np.float32)
    n, d = data.shape
    with open(filepath, "wb") as f:
        np.array([n, d], dtype="uint32").tofile(f)
        data.tofile(f)


def write_metadata(filepath, categories, weights):
    """Write per-vector metadata in a custom binary layout.

    Layout:
      uint32  num_vectors
      uint32  num_dimensions
      uint8[num_vectors]       category labels   (values 0 .. num_categories-1)
      float32[num_dimensions]  per-dimension distance weights
    """
    with open(filepath, "wb") as f:
        np.array([len(categories)], dtype="uint32").tofile(f)
        np.array([len(weights)], dtype="uint32").tofile(f)
        np.ascontiguousarray(categories, dtype="uint8").tofile(f)
        np.ascontiguousarray(weights, dtype="float32").tofile(f)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    np.random.seed(42)

    num_base = 15000
    num_queries = 100
    dims = 32
    num_categories = 5
    num_clusters = 40

    os.makedirs("/app/data", exist_ok=True)

    # --- Clustered base vectors -------------------------------------------
    centers = np.random.randn(num_clusters, dims).astype(np.float32) * 8.0
    assignments = np.random.randint(0, num_clusters, num_base)
    base = (
        centers[assignments]
        + np.random.randn(num_base, dims).astype(np.float32) * 0.5
    )
    base = base.astype(np.float32)

    # --- Query vectors (same cluster distribution) ------------------------
    q_assignments = np.random.randint(0, num_clusters, num_queries)
    queries = (
        centers[q_assignments]
        + np.random.randn(num_queries, dims).astype(np.float32) * 0.5
    )
    queries = queries.astype(np.float32)

    # --- Per-vector category labels ---------------------------------------
    categories = np.random.randint(0, num_categories, num_base).astype(np.uint8)

    # --- Per-dimension distance weights (in [0.5, 2.0]) -------------------
    weights = (0.5 + 1.5 * np.random.rand(dims)).astype(np.float32)

    write_fbin("/app/data/base.fbin", base)
    write_fbin("/app/data/queries.fbin", queries)
    write_metadata("/app/data/metadata.bin", categories, weights)

    # --- Streaming runbook ------------------------------------------------
    #
    # 16 steps: mix of insert / delete / replace / search (with category
    # filters on every search).
    #
    # State trace (active tag count):
    #   step  2:  6 000   (initial insert [0, 6000))
    #   step  5:  7 000   (delete [2000,4000) then insert [6000,9000))
    #   step  8:  6 000   (replace [0,500)->vecs[9000,9500); delete [5000,6000))
    #   step 12:  7 500   (insert [9500,12000); replace [4000,4200)->vecs[2000,2200); delete [7000,8000))
    #   step 16:  8 500   (insert [12000,13500); delete [8500,9500); replace [500,700)->vecs[3000,3200))

    runbook = {
        "streaming_bench": {
            "max_pts": 12000,
            1:  {"operation": "insert", "start": 0, "end": 6000},
            2:  {"operation": "search", "category_filter": [0, 1, 2, 3, 4]},
            3:  {"operation": "delete", "start": 2000, "end": 4000},
            4:  {"operation": "insert", "start": 6000, "end": 9000},
            5:  {"operation": "search", "category_filter": [0, 2, 4]},
            6:  {"operation": "replace",
                 "tags_start": 0, "tags_end": 500,
                 "ids_start": 9000, "ids_end": 9500},
            7:  {"operation": "delete", "start": 5000, "end": 6000},
            8:  {"operation": "search", "category_filter": [1, 3]},
            9:  {"operation": "insert", "start": 9500, "end": 12000},
            10: {"operation": "replace",
                 "tags_start": 4000, "tags_end": 4200,
                 "ids_start": 2000, "ids_end": 2200},
            11: {"operation": "delete", "start": 7000, "end": 8000},
            12: {"operation": "search", "category_filter": [0, 1, 2]},
            13: {"operation": "insert", "start": 12000, "end": 13500},
            14: {"operation": "delete", "start": 8500, "end": 9500},
            15: {"operation": "replace",
                 "tags_start": 500, "tags_end": 700,
                 "ids_start": 3000, "ids_end": 3200},
            16: {"operation": "search", "category_filter": [2, 3, 4]},
        }
    }

    with open("/app/data/runbook.yaml", "w") as f:
        yaml.dump(runbook, f, default_flow_style=False, sort_keys=True)

    # --- Config -----------------------------------------------------------
    config = {
        "hnsw": {
            "M": 16,
            "ef_construction": 200,
            "ef_search": 100,
            "max_elements": 16000,
        },
        "evaluation": {
            "min_recall_per_step": 0.7,
            "min_avg_recall": 0.8,
        },
    }

    with open("/app/data/config.json", "w") as f:
        json.dump(config, f, indent=2)


if __name__ == "__main__":
    main()
