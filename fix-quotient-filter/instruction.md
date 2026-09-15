The directory `/app/` contains the API header, hash function source, and build system for a Counting Quotient Filter (CQF) shared library — the space-efficient probabilistic data structure from Pandey et al. (SIGMOD 2017).

**Provided files:**
- `/app/cqf.h` — Complete API specification with all function signatures and documentation
- `/app/cqf_hash.h` and `/app/cqf_hash.c` — Deterministic hash function (FNV-1a + splitmix64 finalizer), already implemented
- `/app/Makefile` — Builds `libcqf.so` from `cqf.c` and `cqf_hash.c`

**Your task:** Create `/app/cqf.c` implementing every function declared in `/app/cqf.h`, then build the shared library by running `make` in `/app/`. The resulting `/app/libcqf.so` must be loadable via `ctypes` and pass the full test suite.

## CQF algorithm

A CQF hashes each item to a `(quotient, remainder)` pair. The quotient selects a *canonical slot* in a power-of-two array. Remainders are stored at or near their canonical slot.

**Runs and clusters.** A *run* is a sorted contiguous sequence of remainders sharing the same quotient. A *cluster* is a maximal contiguous sequence of non-empty slots; a cluster may span multiple runs from different quotients.

**Metadata bits.** Each slot carries two flags:
- `is_occupied[i]` — True iff quotient `i` has at least one element. This is a property of the quotient index and **never shifts** when data moves.
- `is_runend[i]` — True iff slot `i` holds the last element of some run. This is a property of the physical slot and **shifts with the data**.

**Insertion** into an existing run maintains sorted remainder order. Subsequent slots are shifted right; `is_runend` travels with the shifted data, `is_occupied` does not.

**Run-start lookup.** To find where quotient `q`'s run begins: walk left to the cluster start, count how many occupied quotients precede `q` in the cluster, then walk right from the cluster start counting run-end markers to skip past that many completed runs.

**Resize** doubles slot count by transferring the MSB of each remainder to the quotient: `new_q = (old_q << 1) | (old_r >> (old_r_bits - 1))`.

**Merge** produces a new filter with counts summed (multiset union).

**Serialization** must support lossless round-trip (format is your choice).

**Inner product:** `Σ count_a(x) · count_b(x)` over all shared elements. **Cosine similarity** derives from inner product and magnitudes.

The `cqf_t` struct is opaque — design its internal layout in your implementation.