Build `/app/streaming_search.py`: a streaming approximate nearest-neighbor search system with category-filtered queries and a weighted distance metric.

`/app/data/generate.py` produces the binary dataset files when executed. `/app/lib/` contains C source for a weighted distance computation kernel.

**CLI**:
```
python3 /app/streaming_search.py \
  --data_dir /app/data \
  --lib_dir /app/lib \
  --output_dir /app/results \
  --k 10
```

The system must:

- Parse vector data, per-vector metadata, the streaming runbook, and index configuration from `/app/data/`
- Compile and integrate the distance library from `/app/lib/` via `ctypes` — all final distance values must come from this library
- Use `hnswlib` for approximate nearest-neighbor indexing
- Process streaming runbook operations (`insert`, `delete`, `replace`, `search`) maintaining a tag-to-vector-ID mapping — after a `replace`, the tag's associated vector (and therefore its category) changes to the replacement target
- Apply per-search-step category filters: only return neighbors whose vector's category label appears in the step's filter list
- Compute distances using the weighted metric implemented by the C library, initialised with the per-dimension weights from the metadata file

**Per search step N, write**:

- `/app/results/step{N}_neighbors.ibin` — `[nq, k]` int32 array of neighbor tag IDs in BigANN binary format (8-byte header: two little-endian uint32 giving num_rows and num_cols, followed by row-major data)
- `/app/results/step{N}_distances.fbin` — `[nq, k]` float32 array of weighted distances (same header convention)
- `/app/results/summary.json` — `{"search_steps": [{"step": N, "num_active_points": <total active tag count>, "categories": <sorted filter list>}, ...]}`

**Constraints**:

- All returned tag IDs must be in the current active set **and** have categories matching the step's filter
- Distances must be non-decreasing per query row
- recall@10 >= 0.7 at every search step; average recall@10 >= 0.8 across all steps
