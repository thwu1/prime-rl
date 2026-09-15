A count regression pipeline at `/app/count_pipeline.py` processes the doctor-visits dataset `/app/data/racd10.csv` (3,629 records) and produces `/app/results.json`. The pipeline has multiple errors producing incorrect output and incomplete functionality.

Debug and fix the pipeline so that `cd /app && python3 count_pipeline.py` produces a correct `/app/results.json`. The pipeline's Python dependencies are not pre-installed.

The response variable is `docvis`. Predictors are `aget` and `totchr` with an intercept appended as the last design-matrix column.

`/app/results.json` must contain the following top-level keys:

**Truncated models** -- `trunc_poisson_0`, `trunc_negbin_0`, `trunc_poisson_1`, `trunc_negbin_1`: Each contains `params` (dict: `aget`, `totchr`, `const`; NB models also include `alpha` for dispersion), `bse` (dict: `aget`, `totchr`, `const`), `llf` (float), `aic` (float), `n_obs` (int), and `conditional_mean_atmeans` (float -- the truncated conditional mean E[Y|Y>c] evaluated at the estimation-sample covariate means, where the estimation sample consists only of observations with Y > truncation). NB models use the NB2 (quadratic variance) parameterization.

**Hurdle model** -- `hurdle_pp`: A Poisson-Poisson hurdle model (Poisson for both zero and count parts). Contains `zero_params` and `count_params` (each dict: `aget`, `totchr`, `const`), `llf` (float), `predicted_mean_atmeans` (float, at full-sample covariate means), `predicted_probs_atmeans` (list of four floats: P(Y=k) for k=0,1,2,3 at the same point), and `decomposition` (dict: `zero_llf`, `count_llf`, `total_llf` where `total_llf = zero_llf + count_llf` equals the reported `llf`).

**Model comparisons** -- `lr_test_0` and `lr_test_1`: Each contains `statistic` (positive float) and `df` (int). `vuong_test_0`: Contains `statistic` (float) and `pvalue` (float), comparing the truncated Poisson and NB models at truncation=0.

All numerical values must be computed from data at runtime, not hard-coded.
