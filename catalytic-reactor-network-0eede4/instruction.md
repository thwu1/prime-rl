The `/app/` directory contains a multi-component catalytic reactor simulation pipeline. Multiple defects across its Python code, SQL schema, shell scripts, and build configuration prevent it from operating correctly.

Fix all components so the validation test suite passes.

## Components

- `catreactor.py` — CLI dispatching `rate`, `arrhenius`, `network` subcommands via `reactor/` package
- `reactor/kinetics.py` — LHHW surface-reaction rate evaluation
- `reactor/solver.py` — PFR and CSTR design equation solvers
- `reactor/network.py` — Reactor network stage processing (series, parallel, recycle)
- `reactor/dbutil.py` — SQLite queries for species thermodynamic properties
- `schema.sql` — DDL/DML populating the species properties database (`properties.db`)
- `batch_run.sh` — Batch rate calculator using `jq` for JSON transformation
- `Makefile` — Pipeline orchestration: `init` (database from schema), `batch` (batch processing), `clean`

## CLI: `python3 /app/catreactor.py <subcommand> <input.json> <output.json>`

### `rate`

Evaluates steady-state LHHW rate. **Direct mode**: input has `species` dict (name to `{"K": float, "C": float}`). **Lookup mode**: input has `"source": "database"` and `species_names` list; properties loaded from `properties.db`. Both modes require `mechanism_type` (`"unimolecular"` | `"bimolecular"`), `reactants`, `k_sr`.

Output: `{"rate": float}`

### `arrhenius`

Input: `temperatures` (K), `rate_constants`, `R` (gas constant).

Output: `{"activation_energy": float, "pre_exponential_factor": float, "r_squared": float}`

### `network`

Input: `kinetics` (`order`, `rate_constant`, `epsilon_A`), `feed` (`C_A0`, `volumetric_flow_rate`), `stages` (list with `type`: `"single"`, `"parallel"`, `"recycle"`).

Output: `{"stages": [...], "outlet": {"C_A": float, "X_A": float}}`

## Requirements

- Numerical results accurate to 4+ significant figures.
- Recycle stages converge to steady state (tolerance 1e-10 or better).
- Gas-phase reactors (`epsilon_A != 0`) use variable-density design equations.
- `make -C /app init` creates a correct `properties.db` from `schema.sql`.
- `make -C /app batch` runs the complete batch pipeline.
- `batch_run.sh` processes all cases from `datasets/batch_cases.json` and produces valid aggregated JSON output.
