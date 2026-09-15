The `/app/nicob/` directory contains R source files extracted from the NIST Consensus Builder (NICOB), a metrological application for combining interlaboratory measurement results into consensus estimates with uncertainty quantification. The `/app/data/` directory contains measurement datasets in NICOB's native `.ncb` configuration format.

Build `/app/consensus.py` that reads every `.ncb` file in `/app/data/`, performs the complete consensus analysis that the R source code implements, and writes per-dataset results to `/app/results/{stem}.json` (where `{stem}` is the `.ncb` filename without extension).

Each JSON output must contain these keys: `consensus_dl`, `tau_squared`, `tau`, `cochran_q`, `i_squared`, `hksj_ci` (two-element list `[lower, upper]`), `consensus_lp`, and `doe` (object keyed by lab label, each entry having `value`, `U95`, `significant`).

For the opinion pool consensus: 500000 Monte Carlo samples, `numpy.random.RandomState(42)`, equal weights across labs. For the degrees of equivalence bootstrap: 10000 replicates, `numpy.random.RandomState(123)`, 95% coverage. Use only `numpy` and `scipy` for computation.