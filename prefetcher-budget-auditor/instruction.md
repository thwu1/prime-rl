Build `/app/storage_pipeline.py` — a CLI tool that statically analyzes IPC-1 instruction prefetcher C++ source files to determine their hardware storage budgets against the 128 KB (131,072 bytes) competition limit.

Prefetcher source files are in `/app/prefetchers/` and ChampSim framework headers are in `/app/include/`. Competition context is in `/app/rules.txt`.

The tool must support four subcommands. Each produces JSON to stdout.

**`python3 /app/storage_pipeline.py preprocess <file.cc>`**
Resolve all reachable preprocessor macros to integer values. Exclude system/compiler macros (names starting with `_`).
Output: `{"macros": {"NAME": integer_value, ...}}`

**`python3 /app/storage_pipeline.py analyze <file.cc> <struct_name>`**
Compute the per-entry hardware storage cost (in bits) of a named C++ struct or typedef.
Output: `{"name": "...", "members": [{"name": "field", "bits": N}, ...], "bits_per_entry": N}`

**`python3 /app/storage_pipeline.py budget <file.cc>`**
Compute total hardware storage in bytes for one prefetcher file.
Output: `{"total_storage_bytes": N, "budget_limit_bytes": 131072, "within_budget": bool}`

**`python3 /app/storage_pipeline.py report`**
Budget every `.cc` file in `/app/prefetchers/`, rank by storage descending.
Output: `{"prefetchers": [{"file": "name.cc", "total_storage_bytes": N, "within_budget": bool}, ...], "ranking": ["most.cc", ..., "least.cc"]}`