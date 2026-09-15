CPython's free-threaded build (PEP 703) replaces the GIL with a biased reference counting (BRC) protocol for thread-safe memory management. A protocol reference is at `/app/spec/brc_spec.md` and deterministic test scenarios are at `/app/scenarios/*.json`.

Build a working BRC simulator and produce `/app/results.json` with correct per-object final states for all scenarios.