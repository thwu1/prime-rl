Implement `/app/wasm_profiler.py` — a Python tool that transforms compiled WebAssembly binary modules to add comprehensive per-function execution profiling, operating directly on the `.wasm` binary format (no text-format round-tripping).

**Usage:** `python3 /app/wasm_profiler.py <input.wasm> <output.wasm>`

The tool must read an input `.wasm` binary and produce a valid instrumented binary with the following properties:

**Per-function counter globals.** For each of the N originally-defined (non-imported) functions, append a mutable i32 global initialized to 0 to the global section. Each defined function body must begin with a prologue that increments its dedicated counter global on entry. Counter globals are appended after any existing defined globals, ordered by function definition index.

**Reporter function.** Synthesize and append a new exported function `__get_call_count` with type signature `(param i32) (result i32)`. Given a 0-based defined-function index, it returns that function's counter value by dispatching through the counter globals. For out-of-range indices (and when N=0), it must return 0. If a matching function type already exists in the type section, reuse it rather than creating a duplicate; otherwise append a new type entry.

**Metadata global.** Append an immutable i32 global `__num_functions` initialized to N (original defined-function count, excluding the reporter) and export it.

**Invariants.** Existing module functionality, exports, and semantics must be fully preserved. All section-ordering constraints must be maintained. The output must pass `wasm-validate`. Index spaces (function indices, global indices, type indices) must correctly account for imports vs. definitions — the global index space is `[imported globals | defined globals | counter globals | __num_functions]` and the function index space is `[imported functions | defined functions | __get_call_count]`.

Several sample WASM modules of varying structural complexity are provided in `/app/modules/` (with corresponding `.wat` sources). Use `wabt` tools (`wasm-objdump`, `wasm2wat`, `wasm-validate`, `wat2wasm`) to analyze their binary layouts and identify the structural variations your implementation must handle.