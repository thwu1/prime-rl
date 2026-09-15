The directory `/app/` contains a broken actuarial valuation pipeline for computing net premium reserves on a portfolio of term life insurance policies. The pipeline uses GNU Make to orchestrate: XML data loading into SQLite, then reserve computation.

Components:

- `/app/data/` — SOA XTbML XML files (mortality tables and improvement scales, plus unrelated decoy files)
- `/app/config.json` — Portfolio configuration referencing tables by SOA `TableIdentity`
- `/app/Makefile` — Pipeline orchestration
- `/app/schema.sql` — SQLite database DDL
- `/app/load_data.py` — XML-to-SQLite data loader
- `/app/compute_reserves.py` — Reserve computation engine reading from SQLite

Running `make pipeline` should produce:

1. `/app/mortality.db` — SQLite database with mortality rates and improvement factors extracted from XTbML files
2. `/app/results.json` — Actuarial reserve valuations

Currently the pipeline fails or produces incorrect results due to bugs across multiple components (Makefile, SQL schema, data loader, computation engine). Fix all issues so that `make pipeline` completes successfully and writes correct outputs.

Required `/app/mortality.db` tables: `table_metadata`, `select_rates`, `ultimate_rates`, `improvement_factors` — each correctly populated from the XML source data.

Required `/app/results.json` schema:

```json
{
  "<valuation_id>": {
    "projected_qx": [<float>, ...],
    "annuity_due": <float>,
    "insurance_pv": <float>,
    "annual_premium": <float>,
    "reserve": <float>,
    "reserve_up": <float>,
    "reserve_down": <float>
  },
  ...
  "total_reserve": <float>,
  "total_reserve_up": <float>,
  "total_reserve_down": <float>
}
```

- `projected_qx`: one generationally-projected mortality rate per remaining policy year from the valuation date.
- `annual_premium`: net level annual premium computed at original policy issue for the full term.
- `reserve`: prospective net premium reserve at the valuation date.
- `reserve_up` / `reserve_down`: reserves recomputed with the interest rate shifted by ± `stress_bps` basis points (1 bp = 0.0001).
- Totals: sum of `face_amount × reserve*` across all valuations.

All floating-point values must be accurate to a relative tolerance of 1e-6.
