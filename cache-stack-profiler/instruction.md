A cache memory performance analysis system at `/app/` processes memory access traces and produces performance statistics. It has two components: a compiled C simulation core (source at `/app/src/cache_core.c`, binary at `/app/src/cache_core`, built via the Makefile in `/app/src/`) and a Python orchestrator (`/app/cachesim.py`) that invokes the C core and implements additional analysis modes.

Running `python3 /app/cachesim.py` reads `/app/queries.json` and writes `/app/results.json`, but the output contains errors across multiple analysis modes.

Reference outputs for select configurations are provided in `/app/golden/`. Diagnose all defects, fix them, and produce correct results for every query in `/app/queries.json`. Write the output to `/app/results.json`.