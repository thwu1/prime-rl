A Nextflow DSL2 project at `/app/` contains an incomplete multi-path quality assessment pipeline. The project provides:

- `/app/SPEC.md` — complete processing specification and output format requirements
- `/app/main.nf` — pipeline skeleton with process input/output signatures defined but empty script bodies and an unimplemented workflow block
- `/app/nextflow.config` — execution configuration
- `/app/samplesheet.csv` — sample metadata
- `/app/data/*.tsv` — per-sample measurement data files
- `/app/reference.csv` — per-experiment reference values

Nextflow (with Java 17) and Python 3 are pre-installed.

Complete the pipeline at `/app/main.nf` so that running it from `/app/` produces `/app/results/report.json` conforming exactly to the specification in `/app/SPEC.md`.