Build a compiler pass sequence optimizer that exploits synergy relationships between LLVM optimization passes to minimize LLVM IR instruction count for a set of benchmark programs.

## Environment

- `/app/benchmarks/*.ll` — Five LLVM IR benchmark programs (compiled from C with `-O0`, no `optnone` attribute)
- `/app/synergy_pairs.json` — Synergy score data for pairs of LLVM optimization passes. Each entry has `{"a": "<pass>", "b": "<pass>", "score": <int>}` where higher score indicates stronger synergy when pass `a` is followed by pass `b`
- `/app/instcount.py` — Helper module for counting LLVM IR instructions (importable: `from instcount import get_instruction_count`)

## Task

Create `/app/optimizer.py` that reads the synergy data, builds a directed graph of pass relationships, and implements a search algorithm (e.g., genetic algorithm, beam search) to find pass sequences that minimize instruction count for each benchmark. The optimizer must produce `/app/results.json` with this structure:

```json
{
  "benchmarks": {
    "<name>": {
      "original_count": 123,
      "oz_count": 45,
      "optimized_count": 42,
      "pass_sequence": "instcombine,gvn,simplifycfg,dse,adce"
    }
  }
}
```

where `<name>` matches the `.ll` filename without extension, `original_count` is the unoptimized instruction count, `oz_count` is the count after `opt -Oz`, `optimized_count` is the count after applying your custom pass sequence, and `pass_sequence` is a comma-separated list of LLVM new pass manager passes.

All instruction counts must be accurate and reproducible. Pass sequences must adapt per benchmark (not identical across all). The optimized counts must improve on the unoptimized originals and be competitive with `-Oz`.