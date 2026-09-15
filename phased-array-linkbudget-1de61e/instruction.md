The `/app/` directory contains a phased array antenna analysis pipeline. The pipeline processes scenario configurations from `/app/scenarios/` through a beamforming engine and writes JSON result files to `/app/output/`.

The beamforming engine at `/app/beamformer.py` is unimplemented. Implement the `Beamformer` class so that `python3 /app/pipeline.py --run-all` processes all scenarios and produces physically correct results.

Explore the existing codebase to understand the required interfaces, data formats, computational conventions, and output schema:

- `/app/pipeline.py` — processing flow, output field names, verification tolerances
- `/app/lib/` — utility modules for data file parsing and RF calculations
- `/app/data/` — element measurement data and inter-element characterization matrices
- `/app/scenarios/` — input configurations referencing data files
- `/app/reference/` — example expected outputs for format and value guidance

The beamformer receives scenario parameters, element S-parameter measurement data, and an inter-element characterization matrix. It must synthesize array weights with a specified sidelobe level, apply a correction using the characterization matrix, compute pattern directivities, perform impedance matching through feed-line networks, and calculate the end-to-end link budget.

The TX-side antenna impedance must be derived from the measurement data at the scenario frequency. Note that utility modules may use different unit conventions than the scenario files.

The pipeline's `--verify` mode compares outputs against reference data. Use it during development to validate your implementation.

Success criteria: `python3 /app/pipeline.py --run-all` exits 0 and produces correct output files for all scenarios.
