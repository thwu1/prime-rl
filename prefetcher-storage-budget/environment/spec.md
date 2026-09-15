# IPC-1 Instruction Prefetching Championship — Storage Budget Specification

## Background

The First Instruction Prefetching Championship (IPC-1) was held at ISCA 2020. Eight instruction prefetcher designs were submitted by research groups worldwide. Each prefetcher was implemented as a C++ file conforming to the ChampSim simulator's L1I prefetcher interface. A key constraint: every prefetcher must fit within a **128 KB hardware storage budget**.

## ChampSim L1I Cache Parameters

These constants are defined in ChampSim headers and used by the prefetchers:

| Constant | Value | Notes |
|----------|-------|-------|
| `LOG2_BLOCK_SIZE` | 6 | 64-byte cache lines |
| `LOG2_PAGE_SIZE` | 12 | 4 KB pages |
| `L1I_SET` | 64 | L1I cache sets |
| `L1I_WAY` | 8 | L1I cache associativity |
| `L1I_PQ_SIZE` | 32 | Prefetch queue entries |
| `L1I_MSHR_SIZE` | 8 | MSHRs |
| `NUM_CPUS` | 1 | Single-core evaluation |

Virtual addresses are 64 bits. Cache line addresses are 58 bits (64 - LOG2_BLOCK_SIZE). Page offsets within a cache line context use `LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE = 6` bits.

## Hardware Storage Budget

Each prefetcher is allowed **128 KB = 131,072 bytes = 1,048,576 bits** of hardware storage.

### Hardware Bits vs. C++ sizeof

The storage budget counts the number of bits needed to implement the data structures in hardware, **NOT** the C++ `sizeof`. For example:

- A 4-bit saturating counter stored in a C++ `int` costs **4 bits**, not 32.
- A 12-bit tag stored in a `uint64_t` costs **12 bits**, not 64.
- A boolean flag costs **1 bit**, not 8.
- Array dimensions from `#define` or `constexpr` values determine entry counts; per-entry bit widths are determined by the algorithm's requirements, not C++ types.

### What Counts

Storage budget includes all persistent state the prefetcher maintains between invocations of its callback functions:

- Lookup tables (set-associative or fully-associative)
- History buffers and queues
- Counters, tags, flags
- Replacement policy bits (e.g., LRU order)

### What Doesn't Count

Minor pipeline state (a few scalar registers totaling < 100 bytes) is conventionally excluded from the budget, as it would be part of the processor's existing register file.

## How Prefetchers Report Their Storage

Each prefetcher documents its storage usage differently:

- **D-JOLT** (`DJOLT_prefetcher.cc`): Contains detailed budget comments in the source code listing per-component bit counts for each data structure.
- **PIPS** (`PIPS_prefetcher.cc`): The `l1i_prefetcher_initialize()` function prints table sizes in KB, computed from `size()` methods that return total bits. The `size()` method is defined in the `LINE_HISTORY_TABLE` class.
- **FNL+MMA** (`FNLMMA_prefetcher.cc`): The `l1i_prefetcher_final_stats()` function prints per-component sizes in bytes, with explicit bit-count formulas visible in the `printf` arguments.

## Your Tasks

### Task 1: Budget Calculator

Write `/app/budget_calculator.py` that reads the three prefetcher source files from `/app/prefetchers/`, extracts their storage parameters, computes exact hardware storage budgets in bits, and outputs `/app/budgets.json`.

The JSON format:
```json
{
  "DJOLT": {
    "total_bits": <integer>,
    "under_128kb": <boolean>
  },
  "PIPS": {
    "total_bits": <integer>,
    "under_128kb": <boolean>
  },
  "FNLMMA": {
    "total_bits": <integer>,
    "under_128kb": <boolean>
  }
}
```

`total_bits` is the sum of all storage-consuming data structures as described in each prefetcher's own budget accounting (comments, `size()` methods, or `printf` formulas). `under_128kb` is `true` if `total_bits <= 1,048,576`.

### Task 2: Parameter Optimizer

The D-JOLT prefetcher uses three miss tables (long-range, short-range, extra) that share the same per-entry structure. Each table is parameterized by `(N_Sets, N_Ways, N_Vectors, VectorSize)` and also stores tag bits and LRU bits per entry.

Write `/app/optimizer.py` that finds the configuration `(lr_sets, sr_sets, extra_sets)` — all powers of 2, minimum 64 each — that **maximizes total entries** across all three miss tables under a **160 KB (1,310,720 bit)** total prefetcher budget. All table parameters besides set counts remain at their original values (N_Ways=4, N_Vectors=2, VectorSize=8). All non-table D-JOLT components (signature generators, signature queues, upper bit table, stream prefetcher tables) remain unchanged at their original sizes. Tag bits per entry = `SignatureBits - log2(N_Sets)` and must be positive.

Break ties by preferring larger `lr_sets`, then larger `sr_sets`.

Output `/app/optimal_config.json`:
```json
{
  "lr_sets": <integer>,
  "sr_sets": <integer>,
  "extra_sets": <integer>,
  "total_entries": <integer>,
  "total_bits": <integer>
}
```

Where `total_entries = (lr_sets + sr_sets + extra_sets) * N_Ways` and `total_bits` is the full prefetcher storage including all components.
