#!/usr/bin/env python3
"""Streaming ANN search — reference solution.

Uses hnswlib for approximate nearest-neighbor indexing, ctypes for the
weighted-distance C library, and category-based post-filtering.

"""

import argparse
import ctypes
import glob
import json
import os
import struct
import subprocess

import numpy as np
import yaml
import hnswlib


# ── Binary I/O ──────────────────────────────────────────────────────────

def read_fbin(filepath):
    with open(filepath, "rb") as f:
        n, d = struct.unpack("<II", f.read(8))
        data = np.frombuffer(f.read(n * d * 4), dtype=np.float32).reshape(n, d)
    return data.copy()


def write_fbin(filepath, data):
    data = np.ascontiguousarray(data, dtype=np.float32)
    n, d = data.shape
    with open(filepath, "wb") as f:
        f.write(struct.pack("<II", n, d))
        data.tofile(f)


def write_ibin(filepath, data):
    data = np.ascontiguousarray(data, dtype=np.int32)
    n, d = data.shape
    with open(filepath, "wb") as f:
        f.write(struct.pack("<II", n, d))
        data.tofile(f)


def read_metadata(filepath):
    with open(filepath, "rb") as f:
        num_vecs = struct.unpack("<I", f.read(4))[0]
        num_dims = struct.unpack("<I", f.read(4))[0]
        categories = np.frombuffer(f.read(num_vecs), dtype=np.uint8).copy()
        weights = np.frombuffer(f.read(num_dims * 4), dtype=np.float32).copy()
    return categories, weights


# ── C library interface ─────────────────────────────────────────────────

class WDistLib:
    """Thin ctypes wrapper around libwdist.so."""

    def __init__(self, lib_path, weights):
        self.lib = ctypes.CDLL(lib_path)

        # wdist_create
        self.lib.wdist_create.restype = ctypes.c_void_p
        self.lib.wdist_create.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.c_int,
        ]
        # wdist_distance
        self.lib.wdist_distance.restype = ctypes.c_float
        self.lib.wdist_distance.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        # wdist_batch
        self.lib.wdist_batch.restype = None
        self.lib.wdist_batch.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_float),
        ]
        # wdist_destroy
        self.lib.wdist_destroy.restype = None
        self.lib.wdist_destroy.argtypes = [ctypes.c_void_p]

        w = np.ascontiguousarray(weights, dtype=np.float32)
        self.ctx = self.lib.wdist_create(
            w.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(weights),
        )
        self.dim = len(weights)

    def batch_distances(self, query, vectors):
        n = vectors.shape[0]
        q = np.ascontiguousarray(query, dtype=np.float32)
        v = np.ascontiguousarray(vectors, dtype=np.float32)
        out = np.empty(n, dtype=np.float32)
        self.lib.wdist_batch(
            self.ctx,
            q.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            n,
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        )
        return out

    def __del__(self):
        if hasattr(self, "ctx") and self.ctx:
            self.lib.wdist_destroy(self.ctx)
            self.ctx = None


# ── Helpers ─────────────────────────────────────────────────────────────

def compile_library(lib_dir):
    """Compile wdist.c into a shared library if not already present."""
    so_path = os.path.join(lib_dir, "libwdist.so")
    c_path = os.path.join(lib_dir, "wdist.c")
    if not os.path.exists(so_path):
        subprocess.check_call(
            ["gcc", "-shared", "-fPIC", "-O2", "-o", so_path, c_path],
        )
    return so_path


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True)
    parser.add_argument("--lib_dir", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    # Load data
    base = read_fbin(os.path.join(args.data_dir, "base.fbin"))
    queries = read_fbin(os.path.join(args.data_dir, "queries.fbin"))
    categories, weights = read_metadata(
        os.path.join(args.data_dir, "metadata.bin"),
    )

    with open(os.path.join(args.data_dir, "runbook.yaml")) as f:
        runbook = yaml.safe_load(f)
    with open(os.path.join(args.data_dir, "config.json")) as f:
        config = json.load(f)

    dataset_name = list(runbook.keys())[0]
    entries = runbook[dataset_name]

    # Compile & load C distance library
    so_path = compile_library(args.lib_dir)
    wdist = WDistLib(so_path, weights)

    # HNSW parameters from config
    hcfg = config["hnsw"]
    M = hcfg["M"]
    ef_construction = hcfg["ef_construction"]
    ef_search = hcfg["ef_search"]

    num_dims = base.shape[1]
    k = args.k

    # Pre-compute sqrt-weight-transformed vectors for HNSW.
    # Standard L2 on transformed vectors == weighted L2 on originals.
    sqrt_w = np.sqrt(weights).astype(np.float32)
    base_t = base * sqrt_w[np.newaxis, :]
    queries_t = queries * sqrt_w[np.newaxis, :]

    os.makedirs(args.output_dir, exist_ok=True)

    # Streaming state
    tag_to_id = {}
    search_results = []

    step_nums = sorted(sn for sn in entries.keys() if isinstance(sn, int))

    for step_num in step_nums:
        entry = entries[step_num]
        op = entry["operation"]

        if op == "insert":
            for i in range(entry["start"], entry["end"]):
                tag_to_id[i] = i

        elif op == "delete":
            for i in range(entry["start"], entry["end"]):
                tag_to_id.pop(i, None)

        elif op == "replace":
            for i in range(entry["tags_end"] - entry["tags_start"]):
                tag = entry["tags_start"] + i
                vec_id = entry["ids_start"] + i
                tag_to_id[tag] = vec_id

        elif op == "search":
            cat_filter = set(entry.get("category_filter", list(range(5))))
            active_tags = list(tag_to_id.keys())

            # Filter to tags whose vector category matches the filter
            filtered_tags = []
            filtered_vecs_t = []
            for t in sorted(active_tags):
                vid = tag_to_id[t]
                if categories[vid] in cat_filter:
                    filtered_tags.append(t)
                    filtered_vecs_t.append(base_t[vid])

            nq = queries.shape[0]
            result_tags = np.full((nq, k), -1, dtype=np.int32)
            result_dists = np.full((nq, k), np.inf, dtype=np.float32)

            if filtered_tags:
                fvecs = np.array(filtered_vecs_t, dtype=np.float32)
                n_filtered = len(filtered_tags)

                # Build HNSW on filtered vectors
                index = hnswlib.Index(space="l2", dim=num_dims)
                index.init_index(
                    max_elements=n_filtered,
                    M=M,
                    ef_construction=ef_construction,
                )
                index.set_ef(max(ef_search, k * 5))
                index.add_items(fvecs, filtered_tags)

                for qi in range(nq):
                    search_k = min(k * 3, n_filtered)
                    cand_labels, _ = index.knn_query(
                        queries_t[qi : qi + 1], k=search_k,
                    )
                    cand_labels = [int(x) for x in cand_labels[0]]

                    # Rerank with exact weighted distances via C library
                    cand_vecs = base[[tag_to_id[t] for t in cand_labels]]
                    exact_d = wdist.batch_distances(queries[qi], cand_vecs)

                    order = np.argsort(exact_d)
                    top = min(k, len(order))
                    for ri in range(top):
                        result_tags[qi, ri] = cand_labels[order[ri]]
                        result_dists[qi, ri] = exact_d[order[ri]]

            write_ibin(
                os.path.join(args.output_dir,
                             f"step{step_num}_neighbors.ibin"),
                result_tags,
            )
            write_fbin(
                os.path.join(args.output_dir,
                             f"step{step_num}_distances.fbin"),
                result_dists,
            )
            search_results.append({
                "step": step_num,
                "num_active_points": len(active_tags),
                "categories": sorted(cat_filter),
            })

    with open(os.path.join(args.output_dir, "summary.json"), "w") as f:
        json.dump({"search_steps": search_results}, f, indent=2)


if __name__ == "__main__":
    main()
