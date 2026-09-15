# MESI Cache Coherence Protocol Simulator Specification

## Overview

You must implement a cycle-accurate MESI cache coherence protocol simulator for a
multi-core system with private L1 caches connected by a snoopy bus. The simulator
processes a memory access trace and produces exact statistics about cache behavior.

## System Model

- **Cores**: N cores, each with a private L1 write-back, write-allocate cache.
- **Bus**: Snoopy bus connecting all L1 caches and main memory.
- **Memory**: Single shared main memory, always coherent (receives all writebacks).
- **No L2 cache**: Misses in L1 go directly to memory (or are supplied by another L1 on intervention).

## Cache Structure

Each L1 cache is a set-associative cache parameterized by:
- `cache_size` (bytes): total data capacity
- `associativity`: number of ways per set
- `line_size` (bytes): size of each cache line (always a power of 2)

Derived:
- `num_sets = cache_size / (associativity * line_size)`
- `offset_bits = log2(line_size)`
- `index_bits = log2(num_sets)`
- For an address `A`:
  - **Byte offset** = `A & ((1 << offset_bits) - 1)`
  - **Set index** = `(A >> offset_bits) & ((1 << index_bits) - 1)`
  - **Tag** = `A >> (offset_bits + index_bits)`

## MESI Protocol States

Each cache line is in one of four states:

| State | Meaning |
|-------|---------|
| **M** (Modified) | Line is dirty; only this cache has a valid copy. Memory is stale. |
| **E** (Exclusive) | Line is clean; only this cache has a valid copy. Memory is up to date. |
| **S** (Shared) | Line is clean; one or more caches may have valid copies. Memory is up to date. |
| **I** (Invalid) | Line is not valid in this cache. |

## State Transitions: Processor Events

When a core performs a read (PrRd) or write (PrWr) on its local cache:

| Current State | Event | Action | Next State |
|--------------|-------|--------|------------|
| I | PrRd | Issue BusRd. If any other cache has the line: next state = **S**. If no other cache has it: next state = **E**. | S or E |
| I | PrWr | Issue BusRdX. Fetch line, invalidate all other copies. | M |
| E | PrRd | Hit. No bus transaction. | E |
| E | PrWr | Hit. Silent upgrade, no bus transaction. | M |
| S | PrRd | Hit. No bus transaction. | S |
| S | PrWr | Hit. Issue BusUpgr to invalidate other sharers. | M |
| M | PrRd | Hit. No bus transaction. | M |
| M | PrWr | Hit. No bus transaction. | M |

## State Transitions: Bus Snooping

When a cache observes a bus transaction from another core:

| Current State | Snooped Bus Event | Action | Next State |
|--------------|-------------------|--------|------------|
| I | BusRd | No action. | I |
| I | BusRdX | No action. | I |
| I | BusUpgr | No action. | I |
| E | BusRd | Transition to Shared. | S |
| E | BusRdX | Invalidate. | I |
| S | BusRd | No action. | S |
| S | BusRdX | Invalidate. | I |
| S | BusUpgr | Invalidate. | I |
| M | BusRd | Flush line to memory (writeback). Transition to Shared. | S |
| M | BusRdX | Flush line to memory (writeback). Invalidate. | I |

Note: BusUpgr can only be observed when the line is in S (since BusUpgr is issued
by a core that hits in S, other caches can only have S or I for the same line).

## Replacement Policy: LRU

Each set maintains a strict LRU (Least Recently Used) ordering of its ways.

**Initialization**: LRU order is `[0, 1, 2, ..., W-1]` where index 0 is most-recently-used (MRU) and index W-1 is least-recently-used (LRU). On initialization, way 0 is MRU and way `W-1` is LRU.

**On access (hit or miss placement)**: Move the accessed way to the MRU position. All other ways shift down by one position.

**Victim selection**: When a miss requires replacement:
1. First, scan ways 0, 1, 2, ... in order. If any way has state **I** (Invalid), select the lowest-indexed Invalid way as the victim.
2. If no Invalid way exists, select the LRU way (last in the LRU ordering).

**Important**: Snooped invalidations (another core's bus transaction causing this cache's line to transition to I) do NOT change the LRU ordering. Only local processor accesses update LRU.

## Data Supply and Memory Counting

### memory_reads (data fetched from main memory)
Incremented when a cache miss requires fetching data and **no** snooped cache had the line in **Modified** state. Specifically:
- On BusRd: if no other cache had M, memory supplies data. `memory_reads += 1`.
- On BusRdX: if no other cache had M, memory supplies data. `memory_reads += 1`.
- On BusRd/BusRdX: if another cache had M, that cache flushes (supplies data via cache-to-cache transfer). `memory_reads` is NOT incremented.

### memory_writes (data written to main memory)
Incremented when a Modified line is written back to memory:
- **Snoop flush**: A cache with a Modified line snoops BusRd or BusRdX, and flushes (writes back) the dirty data. `memory_writes += 1`.
- **Eviction writeback**: A Modified line is evicted due to replacement. `memory_writes += 1`.

### bus_transactions
Incremented for each bus transaction:
- Every cache miss generates one bus transaction (BusRd or BusRdX).
- Every BusUpgr (S-to-M upgrade on write hit) generates one bus transaction.
- Hits in E or M do NOT generate bus transactions.

### total_invalidations
Count of invalidation events across all caches. Each time a cache line transitions
to I due to a snooped BusRdX or BusUpgr, increment by 1. Evictions are NOT counted
as invalidations.

## Access Processing Order

For each access in the trace, process as follows:
1. Compute set index and tag for the accessing core's cache.
2. Search the set for a matching valid line (tag match AND state != I).
3. If **hit**: update state per processor event table. If BusUpgr needed, snoop all other caches. Update LRU.
4. If **miss**:
   a. Select victim way (prefer Invalid, then LRU).
   b. If victim is valid (not I), handle eviction: if Modified, writeback (`memory_writes += 1`). Count as eviction.
   c. Issue bus transaction (BusRd for read, BusRdX for write). Snoop all other caches.
   d. Determine new state: M for write; S if read and any other cache had the line (in any valid state); E if read and no other cache had the line.
   e. Place line in victim way with new tag and state. Update LRU.

**Snoop processing order**: When snooping, iterate through caches in order of core ID (0, 1, 2, ...) skipping the requesting core.

## Trace Format

Each line of the trace file:
```
<core_id> <R|W> <hex_address>
```
- `core_id`: integer (0-indexed)
- `R` = read, `W` = write
- `hex_address`: hexadecimal address with `0x` prefix

Lines starting with `#` or empty lines are ignored.

## Output Format

### stats.json

```json
{
  "config": {
    "num_cores": <int>,
    "cache_size": <int>,
    "associativity": <int>,
    "line_size": <int>
  },
  "per_core": [
    {
      "core_id": <int>,
      "hits": <int>,
      "misses": <int>,
      "hit_rate": <float>,
      "evictions": <int>,
      "writebacks": <int>,
      "invalidations_received": <int>,
      "upgrades": <int>
    }
  ],
  "total_hits": <int>,
  "total_misses": <int>,
  "overall_miss_rate": <float>,
  "bus_transactions": <int>,
  "total_invalidations": <int>,
  "memory_reads": <int>,
  "memory_writes": <int>
}
```

- `hit_rate` = hits / (hits + misses) for that core (0.0 if no accesses)
- `overall_miss_rate` = total_misses / (total_hits + total_misses)
- `upgrades` = number of S-to-M upgrades (BusUpgr) for that core

### min_size.json

```json
{
  "min_cache_size_bytes": <int>,
  "miss_rate_at_min": <float>,
  "miss_rate_at_half": <float>
}
```

- `min_cache_size_bytes`: smallest cache size from {512, 1024, 2048, 4096, 8192, 16384, 32768} such that overall miss rate < 0.10 (10%), using 4-way associativity and 64-byte lines.
- `miss_rate_at_min`: the overall miss rate at that size.
- `miss_rate_at_half`: the overall miss rate at half that size (must be >= 0.10). If min is 512, set to 1.0.

## Baseline Configuration

For the main simulation (producing `stats.json`), use:
- num_cores = 4
- cache_size = 2048 (2 KB per core)
- associativity = 4
- line_size = 64

## Self-Validation

A small test vector trace is provided at `/app/traces/test_vector.trace` with
configuration: 2 cores, 64-byte cache, 1-way (direct-mapped), 32-byte lines (2 sets).

Expected results for this trace:
- Core 0: hits=1, misses=3, evictions=1, writebacks=1, invalidations_received=0, upgrades=1
- Core 1: hits=0, misses=2, evictions=0, writebacks=0, invalidations_received=1, upgrades=0
- total_hits=1, total_misses=5, bus_transactions=6, total_invalidations=1
- memory_reads=5, memory_writes=1

Use these values to verify your implementation before running the full workload.
