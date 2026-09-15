Two custom data structures are provided at `/app/`: `OrderedSet` (`/app/orderedset.py`) and `SortedMapping` (`/app/sortedmap.py`). Operation modules `/app/setops.py` and `/app/mapops.py` implement algorithms over these types with PEP 316 contracts intended for symbolic verification via CrossHair. Optimized variants exist at `/app/setops_v2.py` and `/app/mapops_v2.py`.

CrossHair (`crosshair-tool`) is installed but cannot symbolically analyze the custom types without a plugin.

Audit this codebase for formal verification readiness and bring it to a fully verifiable state:

**Design** a CrossHair plugin at `/app/ch_plugin.py` that registers both `OrderedSet` and `SortedMapping` for symbolic analysis, using `crosshair.register_type` with `crosshair.SymbolicFactory`-based constructor callbacks.

**Evaluate** every function in `/app/setops.py` and `/app/mapops.py` against its documented semantics. Judge each function's specification quality and implementation correctness. You must distinguish between: implementation bugs (code contradicts documented behavior), logically incorrect contracts (postconditions that reject valid outputs), specifications too weak to expose underlying implementation flaws (postconditions that fail to catch bugs the verifier should find), and functions with no postconditions at all. Fix all defects so every function has at least one correct `post:` condition and produces correct results for all inputs.

**Compare** the optimized variants in `/app/setops_v2.py` and `/app/mapops_v2.py` against their reference counterparts. Identify and fix any semantic divergences so each optimized function produces identical output to the reference for all inputs.

**Produce a defect classification report** at `/app/defect_report.json` documenting your audit findings. The report must be a JSON object with a `"defects"` array. Each entry must contain:
- `"module"`: filename without extension (e.g., `"setops"`, `"mapops"`, `"setops_v2"`, `"mapops_v2"`)
- `"function"`: function name
- `"category"`: exactly one of `"implementation_bug"`, `"contract_error"`, `"weak_specification"`, `"missing_specification"`

List every defect with its correct category. Do not flag functions that are already correct. A function with compound defects (e.g., a weak specification masking an implementation bug) may appear in multiple entries with different categories.