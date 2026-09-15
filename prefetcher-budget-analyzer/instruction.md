Build `/app/analyze.py`: a tool that resolves C preprocessor `#define` macros from ChampSim IPC-1 instruction prefetching competition source files and computes hardware storage budgets for the prefetcher entries.

Source files are at `/app/sources/`: framework headers (`champsim.h`, `cache.h`) and three competition prefetcher implementations (`FNLMMA_prefetcher.cc`, `EIP_prefetcher.cc`, `PIPS_prefetcher.cc`) from the 1st Instruction Prefetching Championship held at ISCA 2020.

The tool must:

1. Parse all `#define` object-like macros from every `.h` and `.cc` file under `/app/sources/`, resolving cross-file references. Evaluate arithmetic and bitwise expressions with proper operator precedence, including `<<`, `>>`, `&`, `|`, `^`, `+`, `-`, `*`, `/`, parenthesized sub-expressions, and C-style type casts (e.g., `(uint64_t)`) which should be treated as no-ops. Skip function-like macros and non-numeric defines.

2. Compute the hardware storage budget for the FNLMMA prefetcher by analyzing the storage formula in its `l1i_prefetcher_final_stats()` function. Note that `AHEAD.SIZEWAYNEXTMISS` is initialized as `1 << (11 + LOGMULTSIZE)` via the `init()` call in `l1i_prefetcher_initialize()`. Use C integer division semantics.

3. Compute the hardware storage budget for the PIPS prefetcher by analyzing its `LHT_ENTRY::size()` and `LINE_HISTORY_TABLE::size()` methods, applied to both `lht` and `scc` table instances as constructed in the source.

Write output to `/app/output/analysis.json` with this structure:

```json
{
  "resolved_macros": {
    "MACRO_NAME": integer_value
  },
  "storage": {
    "FNLMMA_total_bytes": int,
    "FNLMMA_within_budget": bool,
    "PIPS_total_bits": int,
    "PIPS_total_kb": float,
    "PIPS_within_budget": bool
  }
}
```

The IPC-1 competition enforces a 128 KB hardware storage budget (131072 bytes = 1048576 bits). `PIPS_total_kb` should be `total_bits / 8192` rounded to 2 decimal places. `PIPS_within_budget` compares KB against 128.0.