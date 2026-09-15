Protein structure files and lab documentation have been deposited in `/app/data/`. Some documentation may contain errors — verify all claims against the actual file contents before relying on them.

An analysis protocol specification is also provided in `/app/data/analysis_protocol.json`. It defines the required output schema for the analysis, including all field names, expected types, dimensions, and computational definitions for derived quantities.

Write a Python script at `/app/ensemble_analysis.py` that investigates all structure files in `/app/data/`, identifies which one is the NMR ensemble, performs a comprehensive conformational ensemble analysis following the protocol specification, and writes the complete results to `/app/results.json`.

Run the script so that `/app/results.json` exists when complete.