# IPC-1 Hardware Storage Budget Model

## Competition Overview

The First Instruction Prefetching Championship (IPC-1, ISCA 2020) evaluated instruction
cache prefetcher designs within the ChampSim simulation framework. Each prefetcher must stay
within a **128 KB (131,072 bytes)** hardware storage budget.

## Prefetcher Interface

Prefetchers implement six callback functions declared in `ooo_cpu.h`:
- `l1i_prefetcher_initialize()` — called once at startup
- `l1i_prefetcher_branch_operate(ip, branch_type, branch_target)`
- `l1i_prefetcher_cache_operate(v_addr, cache_hit, prefetch_hit)`
- `l1i_prefetcher_cycle_operate()` — called every cycle
- `l1i_prefetcher_cache_fill(v_addr, set, way, prefetch, evicted_v_addr)`
- `l1i_prefetcher_final_stats()` — called at end; some prefetchers report storage here

## Cross-File Dependencies

Prefetcher source files `#include "ooo_cpu.h"`, which includes `cache.h`, which includes
`memory_class.h` and `champsim.h`. Critical macros from these headers affect prefetcher
data structure sizing:

- `L1I_SET` (64), `L1I_WAY` (8), `L1I_PQ_SIZE` (32), `L1I_MSHR_SIZE` (8) — from `cache.h`
- `NUM_CPUS` (1), `BLOCK_SIZE` (64), `LOG2_BLOCK_SIZE` (6) — from `champsim.h`

For example, the Entangling prefetcher defines:
```c
#define L1I_TIMING_MSHR_SIZE (L1I_PQ_SIZE + L1I_MSHR_SIZE + 2)
```
This resolves to 42 only when `L1I_PQ_SIZE` and `L1I_MSHR_SIZE` from `cache.h` are available.

## Storage Accounting Rules

Storage is counted at the **bit level**, reflecting hardware implementation cost:

- Array dimensions come from `#define` macros (e.g., `#define ENTRIES (1 << 16)`)
- Bit widths per field are annotated in source comments (e.g., `uint64_t tag; // 58 bits`)
- Total storage in **bytes** = total bits / 8, using C-style integer division (truncation)
- Boolean fields (`bool valid`) count as 1 bit
- The budget counts only prefetcher-specific storage, not pipeline state

## Self-Reported Storage

Some prefetchers compute storage in `l1i_prefetcher_final_stats()` via printf statements.
These expressions reference `#define` macros and class member variables set during
initialization. Example from FNL+MMA:

```c
printf("Miss Ahead Prediction Table %d bytes\n", 72 * 4 * AHEAD.SIZEWAYNEXTMISS / 8);
```

To evaluate this, `AHEAD.SIZEWAYNEXTMISS` must be traced through:
1. `AHEAD` is an instance of class `PredictMiss`
2. `AHEAD.init(DISTAHEAD, 11)` is called in `l1i_prefetcher_initialize()`
3. The `init()` method sets `SIZEWAYNEXTMISS = 1 << (LOGSIZE + LOGMULTSIZE)` = 2048

## Conditional Compilation

ChampSim headers use conditional compilation. For example, `ooo_cpu.h` contains:
```c
#ifdef CRC2_COMPILE
#define STAT_PRINTING_PERIOD 1000000
#else
#define STAT_PRINTING_PERIOD 10000000
#endif
```
Since `champsim.h` defines `NO_CRC2_COMPILE` but not `CRC2_COMPILE`,
`STAT_PRINTING_PERIOD` resolves to 10000000 in the IPC-1 configuration.

## Struct Bit-Width Annotations

Data structures annotate member bit widths in comments following the C++ convention:
```c
typedef struct __l1i_hist_entry {
  uint64_t tag;       // L1I_HIST_TAG_BITS bits
  uint64_t time_diff; // L1I_TIME_DIFF_BITS bits
  uint32_t bb_size;   // L1I_MERGE_BBSIZE_BITS bits
} l1i_hist_entry;
```

The bit-width expression references macros that must be resolved through the
preprocessor to compute the per-entry storage cost.
