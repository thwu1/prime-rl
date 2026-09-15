A 15-node storage cluster uses Reed-Solomon erasure coding with configurable RS(k, m) — k data shards plus m parity shards, each on a distinct node. The Python framework at `/app/` provides GF(2^8) arithmetic, an RS codec, a cluster simulator, and a storage engine.

## Part 1: Binary Crash Dump Recovery

`/app/crash_dump.bin` is an undocumented binary dump from a cluster node failure containing partial shard data for one file. Reverse-engineer its format, extract surviving shards, reconstruct the original file, and write it to `/app/recovered.bin`.

## Part 2: Transition Engine

Complete the `TransitionEngine` class in `/app/transition_engine.py`. It must support:

- **Encoding**: Store files as RS(k, m) shards across cluster nodes.
- **Scheme transitions**: Migrate files between EC configurations (e.g., RS(4,2) to RS(4,4) or RS(6,3)). Same-k transitions must reuse existing data shards and only recompute parity — a naive full re-encode will fail the efficiency tests.
- **Degraded reads**: Retrieve file data when up to m nodes are unavailable.
- **Repair**: Restore full redundancy after permanent node losses.

The test suite validates correctness, data integrity, and transition efficiency.