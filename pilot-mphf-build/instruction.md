A **minimal perfect hash function** (MPHF) maps a known set of *n* distinct 64-bit keys bijectively to {0, 1, …, n−1} using a compact auxiliary data structure — without storing the keys themselves. State-of-the-art MPHFs achieve 2–4 bits per key of auxiliary space.

## Starting Point

- `/app/mphf.h` — **Read-only** C header declaring the full API your implementation must satisfy. Study it carefully — it defines all required function signatures including decomposed statistics accessors.
- `/app/naive_mphf.c` — A naive open-addressing implementation consuming ~312 bits/key. It demonstrates the API contract but fails the space requirement by two orders of magnitude. Do not modify it; write `/app/mphf.c` instead.
- `/app/Makefile` — Builds `libmphf.so` from `mphf.c` and `mphf.h`.
- `/app/data/` — Test key datasets: `random_1k.txt`, `random_200k.txt`, `random_1m.txt`, `sequential_10k.txt`, `adversarial_20k.txt`. Regenerate with `python3 /app/generate_keys.py` if needed.

## Deliverables

1. **`/app/mphf.c`** — C source implementing every function declared in `/app/mphf.h`.
2. **`/app/libmphf.so`** — Shared library built via `make` in `/app`.
3. **`/app/mphf_tool.py`** — Python 3 CLI with three subcommands:
   - `build <keyfile> <output.mph> [--alpha <float>] [--lambda <float>]` — Reads uint64 keys (one per line), constructs the MPHF (defaults: alpha=0.98, lambda=3.0), serializes to binary file.
   - `query <mphf_file> <keyfile>` — Loads MPHF, prints one hash value per key per line.
   - `info <mphf_file>` — Prints exactly four `key=value` lines: `total_bits_per_key`, `pilots_bits_per_key`, `remap_bits_per_key`, `remap_fraction`, computed from the decomposed statistics API declared in `mphf.h`.

## Success Criteria

- **Bijectivity**: All keys map to distinct values covering exactly {0, …, n−1} for every provided dataset, including adversarial keys with structured bit patterns.
- **Space**: `total_bits_per_key` must be in [1.5, 4.0] with default parameters.
- **Scale**: Construction of 1,000,000 random keys must complete within 120 seconds.
- **Determinism**: Repeated queries on the same MPHF instance always return the same values.
- **Serialization**: Build → save → load → query must produce identical results.
- **Parameter sensitivity**: Lower `--alpha` must produce measurably higher `remap_fraction`. `--lambda` must be accepted and influence construction.
- **Decomposed reporting**: The `info` command must correctly attribute space to the internal components exposed by the C API.