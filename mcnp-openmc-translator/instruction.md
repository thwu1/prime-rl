Build a tool that translates MCNP criticality benchmark input files into OpenMC XML format, and perform statistical validation analysis on an ICSBEP benchmark dataset.

## Data

- `/app/benchmarks/` — MCNP input files for four ICSBEP benchmarks: HEU-MET-FAST-001, HEU-MET-FAST-003, PU-MET-FAST-001, HEU-SOL-THERM-001
- `/app/reference/hmf001/` — Known-correct OpenMC XML translation of HMF001 (geometry.xml, materials.xml, settings.xml)
- `/app/data/uncertainties.csv` — 487-entry ICSBEP benchmark dataset (columns: benchmark_name, case_id, keff, uncertainty)
- `/app/schemas/validation_report.schema.json` — JSON Schema specifying the required structure and semantics of the validation report

## Deliverables

**`/app/translator/mcnp_to_openmc.py`** — Python script that reads an MCNP input file (first argument) and writes equivalent OpenMC XML files (geometry.xml, materials.xml, settings.xml) to an output directory (second argument). Must correctly handle all MCNP constructs present in the four provided benchmarks.

**`/app/output/{hmf001,hmf003,pmf001,hst001}/`** — Translated OpenMC XML for each of the four benchmarks. The HMF001 output must match `/app/reference/hmf001/`.

**`/app/analysis/validation_report.json`** — Statistical analysis of the uncertainties dataset, conforming to `/app/schemas/validation_report.schema.json`.