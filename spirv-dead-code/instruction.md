Pre-compiled SPIR-V compute shader modules are located at `/app/modules/*.spv`. Some of these modules contain dead code — computation instructions whose results are never consumed by any live path leading to an observable effect, and functions that exist but are never invoked. Build a Python toolchain that parses these raw binaries and produces a complete dead code census for each module.

Your parser must read the SPIR-V binary format directly using only the Python standard library. No third-party SPIR-V Python packages are permitted, and no calls to external processes (`subprocess`, `os.system`, `os.popen`) are allowed in the parser. The system has `spirv-dis`, `spirv-val`, and SPIR-V header packages installed — use them however you wish for reference and debugging.

## Deliverables

**`/app/spirv_parser.py`** — Exports `parse_module(path)` returning a dict with:
- `header`: dict with keys `magic` (int), `version_major` (int), `version_minor` (int), `generator` (int), `bound` (int)
- `instructions`: list of dicts, each with keys `opcode` (int), `opname` (str), `word_count` (int), `result_id` (int or None), `result_type` (int or None), `id_refs` (list of ints — all IDs referenced by this instruction, excluding the result type and result id)

**`/app/dead_code_analyzer.py`** — Exports `analyze(path)` returning a dict with:
- `dead_instruction_count` (int): total dead computation instructions after exhaustive analysis
- `dead_function_count` (int): total unreachable functions

Must also be runnable as a script that processes every `/app/modules/*.spv` file and writes per-module results to `/app/analysis_results.json`, keyed by filename (e.g., `"simple.spv"`), each value containing `dead_instruction_count` and `dead_function_count`.