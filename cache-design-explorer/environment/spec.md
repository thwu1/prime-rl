# Cache Simulator Specification

## Binary Usage

```
./cachesim <trace_file> <capacity> <block_size> <associativity>
```

Example:
```
./cachesim traces/trace_ref.txt 64 32 1
```

Output is one `key value` pair per line.

## Cache Parameters
- **Capacity (C)**: Total cache size in bytes. Always a power of 2.
- **Block size (B)**: Size of each cache line in bytes. Always a power of 2.
- **Associativity (A)**: Number of ways per set. Always a power of 2.
- **Number of sets**: S = C / (B * A).

## Address Format
All addresses are 32-bit unsigned integers.
- **Offset bits**: log2(B) least significant bits.
- **Index bits**: next log2(S) bits. (0 bits when S = 1, i.e., fully associative.)
- **Tag bits**: remaining most significant bits. Tag = addr >> (offset_bits + index_bits).

## Replacement Policy
**True LRU** (Least Recently Used). On a miss when all ways in a set are occupied, evict the line that was least recently accessed (either read or written). On a hit, update the accessed line's timestamp to be the most recently used. When selecting among invalid (empty) lines on a miss, fill them in order of way index (lowest first).

## Write Policy
**Write-back, write-allocate**:
- **Store hit**: mark the cache line dirty; do not write to main memory.
- **Store miss**: bring the block from memory into the cache (counting as bus_to_cache traffic), then mark it dirty.
- **Eviction of a dirty line**: count as one writeback (the dirty block is written to memory).
- **Load hit or load miss**: never marks a line dirty.

## Statistics
The simulator must track and report these fields:

| Field | Definition |
|---|---|
| `hits` | Number of accesses that found a matching valid line |
| `misses` | Number of accesses that did not find a match (= total - hits) |
| `writebacks` | Number of dirty lines evicted |
| `hit_rate` | hits / (hits + misses) * 100, rounded to 2 decimal places |
| `miss_rate` | misses / (hits + misses) * 100, rounded to 2 decimal places |
| `n_stores` | Number of store (write) operations in the trace |
| `bus_to_cache` | misses * B (bytes fetched from memory on misses) |
| `cache_to_bus_wb` | writebacks * B (bytes written back under write-back policy) |
| `total_traffic_wb` | bus_to_cache + cache_to_bus_wb |
| `cache_to_bus_wt` | n_stores * 4 (hypothetical write-through traffic: each store writes one 4-byte word to memory) |
| `total_traffic_wt` | bus_to_cache + cache_to_bus_wt |

Note: the write-through statistics (`cache_to_bus_wt`, `total_traffic_wt`) are *hypothetical* — the simulator always operates in write-back mode for hit/miss/eviction decisions, but also computes what the traffic *would be* if it were write-through.

## Trace File Format
Each line: `<op> <hex_addr>` where `<op>` is `r` (load) or `w` (store), and `<hex_addr>` is an 8-digit lowercase hexadecimal address (no `0x` prefix). Example:
```
r 1ce026e0
w 026d7680
r 1ce024d0
```

## Reference Test

Use this to validate your simulator before answering the questions.

**Trace**: `traces/trace_ref.txt`
**Config**: C=64, B=32, A=1

**Expected output**:

| Field | Value |
|---|---|
| hits | 2 |
| misses | 4 |
| writebacks | 1 |
| hit_rate | 33.33 |
| miss_rate | 66.67 |
| n_stores | 1 |
| bus_to_cache | 128 |
| cache_to_bus_wb | 32 |
| total_traffic_wb | 160 |
| cache_to_bus_wt | 4 |
| total_traffic_wt | 132 |

Detailed trace walkthrough (C=64, B=32, A=1 gives 2 sets, offset=5 bits, index=1 bit, tag=addr>>6):

1. `r 00000000` — index=0, tag=0. Miss (empty). Install in set 0. misses=1.
2. `r 00000020` — index=1, tag=0. Miss (empty). Install in set 1. misses=2.
3. `r 00000000` — index=0, tag=0. Hit (tag match). Update LRU timestamp. hits=1.
4. `w 00000000` — index=0, tag=0. Hit, set dirty. Update LRU timestamp. hits=2.
5. `r 00000040` — index=0, tag=1. Miss. Evict set 0 (tag=0, dirty=true) -> writeback. Install tag=1. misses=3, writebacks=1.
6. `r 00000000` — index=0, tag=0. Miss. Evict set 0 (tag=1, dirty=false) -> no writeback. Install tag=0. misses=4.

## Questions

### Q1
Simulate `traces/trace_a.txt` with C=512, B=32, A=1.
Report all statistics fields (except miss_rate).

### Q2
Simulate `traces/trace_b.txt` with C=4096, B=64, A=4.
Report all statistics fields (except miss_rate).

### Q3
Simulate `traces/trace_c.txt` with C=2048, B=32, and A in {1, 2, 4, 8}.
For each associativity, report `miss_rate` and `total_traffic_wb`.
Report which associativity gives the lowest `miss_rate`.

### Q4
Compute AMAT (Average Memory Access Time) for `traces/trace_a.txt` with these configs:

| Index | C | B | A |
|---|---|---|---|
| 0 | 256 | 16 | 1 |
| 1 | 512 | 32 | 1 |
| 2 | 512 | 32 | 2 |
| 3 | 1024 | 32 | 2 |
| 4 | 1024 | 64 | 4 |

AMAT = hit_time + miss_rate_fraction * miss_penalty

where hit_time = 1 cycle, miss_penalty = 100 cycles, miss_rate_fraction = misses / (hits + misses).
Round AMAT to 2 decimal places.
Report the index (0-4) of the config with the lowest AMAT.

### Q5
Search for the configuration that minimizes `total_traffic_wb` on `traces/trace_b.txt`.

Search space:
- C in {512, 1024, 2048, 4096}
- B in {16, 32, 64}
- A in {1, 2, 4}

All 36 combinations are valid (smallest S = 512/(64*4) = 2 >= 1).
Report the winning (C, B, A) and its `total_traffic_wb`.
Tie-breaking: prefer smaller C, then smaller B, then smaller A.

## Output Format

Write `answers.json` with this exact structure:

```json
{
  "q1": {
    "hits": 0, "misses": 0, "writebacks": 0,
    "hit_rate": 0.0, "n_stores": 0,
    "bus_to_cache": 0, "cache_to_bus_wb": 0, "total_traffic_wb": 0,
    "cache_to_bus_wt": 0, "total_traffic_wt": 0
  },
  "q2": {
    "hits": 0, "misses": 0, "writebacks": 0,
    "hit_rate": 0.0, "n_stores": 0,
    "bus_to_cache": 0, "cache_to_bus_wb": 0, "total_traffic_wb": 0,
    "cache_to_bus_wt": 0, "total_traffic_wt": 0
  },
  "q3": {
    "results": {
      "1": {"miss_rate": 0.0, "total_traffic_wb": 0},
      "2": {"miss_rate": 0.0, "total_traffic_wb": 0},
      "4": {"miss_rate": 0.0, "total_traffic_wb": 0},
      "8": {"miss_rate": 0.0, "total_traffic_wb": 0}
    },
    "best_associativity": 0
  },
  "q4": {
    "configs": [
      {"amat": 0.0}, {"amat": 0.0}, {"amat": 0.0},
      {"amat": 0.0}, {"amat": 0.0}
    ],
    "best_config_index": 0
  },
  "q5": {
    "best_config": {"capacity": 0, "block_size": 0, "associativity": 0},
    "min_traffic": 0
  }
}
```

All `hits`, `misses`, `writebacks`, `n_stores`, traffic values, and `min_traffic` are integers.
`hit_rate`, `miss_rate`, and `amat` are floats rounded to 2 decimal places.
`best_associativity` and `best_config_index` are integers.
