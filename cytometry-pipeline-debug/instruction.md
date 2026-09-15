The `/app/` directory contains an R pipeline that analyzes flow cytometry data stored in the FCS 3.0 binary format. It performs four stages: binary parsing, spillover compensation, logicle transformation, and rectangle gating. The pipeline has multiple defects that produce incorrect results across these stages; errors in earlier stages cascade into later ones.

Invoke with: `Rscript /app/pipeline.R <input.fcs> <output_dir>`

Fix all defects so each stage produces numerically correct output consistent with the FCS 3.0 specification and standard flow cytometry analysis practices. The source files are: `/app/fcs_parser.R`, `/app/compensation.R`, `/app/transforms.R`, `/app/gating.R`, `/app/pipeline.R`.

Required output files in `<output_dir>`:

**`parsed_data.csv`**: Expression matrix from the FCS DATA segment. Columns = parameters, rows = events. Values must faithfully represent the binary content per the FCS 3.0 specification's `$BYTEORD`, `$DATATYPE`, and `$PnB` keywords.

**`compensated_data.csv`**: Data after spillover compensation using the `$SPILLOVER` keyword matrix (FCS format: `n,ch1,...,chN,m11,...,mNN` stored row-by-row). Only fluorescence channels are compensated; scatter and auxiliary channels pass through unchanged.

**`transformed_data.csv`**: Data after logicle transformation of fluorescence channels (matching `FL\\d+-H`) with parameters T=262144, W=0.5, M=4.5, A=0. Non-fluorescence channels pass through unchanged. The transform must be monotonically increasing, handle the full range of compensated values including negatives, and produce output in a display range consistent with the parameterization.

**`gate_results.json`**: JSON with keys `lymphocyte_gate`, `fluorescence_gate`, `combined_gate`, each containing `count` (integer), `total` (integer), `percentage` (float). Lymphocyte gate: FSC-H in [200,800] and SSC-H in [50,500]. Fluorescence gate: FL1-H in [2.0,4.5] and FL2-H in [1.5,4.5] on the transformed scale. Combined gate: intersection of both.

**`summary.json`**: JSON with `n_events`, `n_params`, `param_names` (comma-separated), `fl_channels` (comma-separated).

Results are verified against independent computation within relative tolerance 1e-4.
