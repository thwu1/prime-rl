A national metrology institute has two measurement models whose uncertainty must be evaluated and cross-validated according to JCGM 101:2008 ("Evaluation of measurement data — Supplement 1 to the GUM — Propagation of distributions using a Monte Carlo method").

## Data Sources

**Comparison loss model** (microwave power meter calibration): Model definition and input parameters are in `/app/models/comparison_loss.json`. Three cases with varying input values are included.

**Gauge block calibration** (end-gauge mechanical comparison): Model metadata and Type B input distributions are stored in a SQLite database at `/app/calibration.db`. Raw repeated-measurement series for three of the nine inputs are also in this database — their statistical parameters must be derived from the observations. Explore the database schema to understand the data layout.

## Required Output

Write `/app/results.json` conforming to the schema in `/app/output_schema.json`. For each model/case, the output must contain:

- A GUM (first-order linearization) uncertainty analysis with estimate, combined standard uncertainty, effective degrees of freedom, and a symmetric coverage interval at the specified coverage probability.
- An adaptive Monte Carlo analysis that runs until numerically stabilized, producing estimate, standard uncertainty, shortest (minimum-width) coverage interval, and total trial count.
- A GUM-vs-MCM validation result indicating whether the GUM coverage interval endpoints agree with the MCM endpoints within the numerical tolerance.

The comparison loss case with both inputs at zero mean is a known critical scenario where GUM linearization demonstrably fails — your results must correctly reflect this.

Units for the gauge block model are nanometres throughout. The coverage probability and number of significant digits for tolerance computation are specified per model in the data sources.