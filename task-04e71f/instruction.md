Build a cross-validation pipeline for the SMT-COMP Model Validation Track that combines a custom SMT-LIB 2 model evaluator with the Z3 theorem prover.

## Deliverables

### `/app/validate_model.py`

Custom model validator. Usage: `python3 /app/validate_model.py <benchmark.smt2> <model.smt2>` — prints exactly `VALID` or `INVALID` on the first line; exit code 0 in both cases.

Required theory support:

- **QF_LIA / QF_NIA**: Integer arithmetic (`+`, `-`, `*`, `div`, `mod`, `abs`), comparisons (`<`, `<=`, `>`, `>=`, `=`, `distinct`), Boolean connectives (`and`, `or`, `not`, `=>`, `xor`), `ite`, nested `let` bindings. `div`/`mod` use SMT-LIB Euclidean semantics.
- **QF_BV**: Fixed-width bitvectors — modular arithmetic (`bvadd`, `bvsub`, `bvmul`), bitwise ops (`bvand`, `bvor`, `bvxor`, `bvnot`), shifts (`bvshl`, `bvlshr`, `bvashr`), unsigned comparisons (`bvult`, `bvule`, `bvugt`, `bvuge`), signed two's-complement comparisons (`bvslt`, `bvsle`, `bvsgt`, `bvsge`), `concat`, indexed `extract`, literals in all three forms: `(_ bvN W)`, `#xHH...`, `#bBB...`
- **QF_AUFLIA**: Arrays with `select`, `store`, and `(as const (Array K V))` model representation
- **QF_UFLIA**: Uninterpreted function models via `define-fun` with parameters

Model format: `(model ...)` wrapper containing `define-fun` for constants/functions and `refine-fun` for partial theory function refinements (e.g., `div`/`mod` at zero). Within a `refine-fun` body, calls to the refined function name dispatch to the original theory semantics, not the refinement itself.

### `/app/z3_solve.py`

Z3-based solver frontend. Usage: `python3 /app/z3_solve.py <benchmark.smt2> [output_model.smt2]` — prints `sat`, `unsat`, or `unknown` to stdout. When the result is `sat` and an output path is provided, writes a model file in `(model (define-fun ...) ...)` format that `validate_model.py` can parse.

Must use the Z3 SMT solver's Python API (`z3-solver` pip package). Z3 model output must be converted to SMT-COMP format: `define-fun` for constants, `ite`-chain bodies for function interpretations, `const`/`store` representation for arrays, `(- N)` for negative integers.

### `/app/pipeline.sh`

Cross-validation orchestrator. For each benchmark in `/app/benchmarks/` with its paired model in `/app/models/` (`caseNN_*.smt2` ↔ `modelNN_*.smt2`):
- Validate the provided model with `validate_model.py`
- Solve the benchmark with `z3_solve.py` and generate a Z3 model
- If Z3 returns `sat`, validate the Z3-generated model with `validate_model.py`
- Write all results to `/app/results.json`

**results.json schema** — keys are benchmark base names (no extension):
```json
{
  "case01_lia_valid": {"provided_model_valid": true, "z3_result": "sat", "z3_model_valid": true},
  "case08_uflia": {"provided_model_valid": false, "z3_result": "unsat", "z3_model_valid": null}
}
```