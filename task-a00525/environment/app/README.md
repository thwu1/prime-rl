# N-Queens Completion Hardness Study

Research codebase for studying computational complexity of n-Queens variants,
based on Gent, Jefferson & Nightingale (JAIR 2017).

## Project Structure

- `src/` — Core algorithms (SAT encoder, instance loading, solver interface)
- `data/` — Problem instances in QC (JSON) and EDP (custom) formats
- `experiments/` — Experiment configuration

## Known Issues

The SAT encoder in `src/sat_encoder.py` produces incorrect results for
certain instances. Comparison against `data/validation.json` can help
identify affected cases.

## Output Convention

Instance results: `/app/results/<id>_result.json`
Phase transition: `/app/results/phase_transition.json`

Result schema: `{"id": str, "satisfiable": bool, "solution": [[r,c],...] | null}`
Phase transition schema: `{"board_size": int, "results": [{"m": int, "total": int, "sat_count": int, "sat_ratio": float}], "critical_m": int}`
