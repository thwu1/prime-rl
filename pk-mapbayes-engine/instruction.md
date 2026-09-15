Create `/app/pk_engine.py`, a pharmacokinetic simulation engine that implements the model defined in `/app/model.json` and processes NONMEM-style event data according to `/app/docs/nmtran_events.md`.

**Subcommands:**

`python3 /app/pk_engine.py simulate <input.csv> <output.csv>`
- Input: NONMEM-style CSV. Required columns: `ID,TIME,EVID,AMT,CMT,II,ADDL,SS,RATE,DV,MDV,F1,ALAG1`. Optional columns: `ETA_CL,ETA_V1,ETA_KA` (default 0), `WT` (default per model.json).
- Output: CSV with columns `ID,TIME,A1,A2,A3,CP` — one row per input record. State reflects all events processed at that time.
- Subjects (distinct IDs) are simulated independently.

`python3 /app/pk_engine.py mapbayes <input.csv> <output.json>`
- Estimates individual random effects for each subject. Observations are records where EVID=0 and MDV=0.
- The estimation objective balances fidelity to observed concentrations under the residual error model with consistency to the population distribution, both specified in `/app/model.json`.
- Output JSON: `{"individuals": [{"ID": int, "ETA_CL": float, "ETA_V1": float, "ETA_KA": float, "OFV": float, "IPRED": [float, ...]}]}`
- `OFV` is the minimized objective function value; `IPRED` contains individual predicted concentrations at observation times.

**Requirements:**
- ODE solver relative tolerance ≤ 1e-8.
- All model structure, parameters, covariate relationships, variability, and error model details are in `/app/model.json`.
- Event handling semantics are in `/app/docs/nmtran_events.md`.
