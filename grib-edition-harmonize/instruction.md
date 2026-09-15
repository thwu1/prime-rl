Five GRIB files from an upstream NWP post-processing pipeline were rejected by the automated ingestion system. The QC rejection report is at `/app/qc_report.log`. The GRIB files are in `/app/data/`. The ecCodes library (CLI tools and Python bindings) is available in the environment.

Each file contains a different conformance defect. Investigate each rejected file, diagnose the root cause, repair the data, and produce the outputs below.

## Required outputs

**`/app/output/corrected/<original_filename>`** — Corrected version of each input file. Every corrected file must satisfy: parameter metadata consistent with the physical domain of the encoded data values, grid scanning flags uniform across all messages in the file, vertical levels unique within each parameter, data representation precision adequate for the parameter's operational requirements, and level descriptors physically valid for the declared parameter. Where the defect was metadata-only, preserve the original data values exactly. Where data values require correction, the transformation must be physically justified.

**`/app/output/audit.json`** — JSON array with one entry per input file: `{"filename": "<name>", "root_cause": "<diagnosis>", "correction": "<what was fixed>"}`.

**`/app/output/integrity.json`** — JSON object keyed by filename. Each value: `{"message_count": <int>, "max_abs_diff": <float>}` representing the maximum absolute difference between original and corrected data values across all grid points and messages in that file.