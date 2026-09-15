The `/app/` directory contains a Java project implementing an ISDA SIMM v2.6 Interest Rate margin engine. It computes IR Delta margin, IR Curvature margin, and a combined total IR margin for portfolios of bucketed rate sensitivities. The code compiles and runs but produces incorrect delta margin values, the curvature calculator is incomplete, and the risk aggregator combines margins incorrectly.

**Build and run:**
```
javac -d /app/out /app/src/*.java
java -cp /app/out Main /app/portfolios/portfolio_1.csv
```

**Output** (stdout, single-line JSON):
```json
{"deltaBuckets":{"CCY":{"K":0.0,"S":0.0,"CR":0.0}},"deltaMargin":0.0,"curvatureBuckets":{"CCY":{"K":0.0,"sumCVR":0.0,"lambda":0.0,"margin":0.0}},"curvatureMargin":0.0,"totalMargin":0.0}
```

Bucket keys sorted alphabetically. Delta bucket fields: `K` (intra-bucket capital), `S` (weighted sensitivity sum), `CR` (concentration risk factor, >= 1.0). Curvature bucket fields: `K` (intra-bucket capital), `sumCVR` (CVR sum), `lambda` (scaling factor in [-1, 1]), `margin` (>= 0). All numeric values formatted to 6 decimal places.

**Inputs**: Portfolio CSVs with columns `RiskType,Currency,SubCurve,Tenor,Sensitivity`. RiskType is `Delta` or `Curvature`. SIMM parameters in `/app/data/`: `risk_weights.csv`, `currency_groups.csv`, `concentration_thresholds.csv`, `simm_params.csv`, and `curvature_params.csv`. Unmapped currencies default to group `HighVol`.

**Delta margin**: ISDA SIMM v2.6 IR Delta with parametric tenor correlations (theta, rho_min, min-based denominator), sub-curve correlations (phi), concentration risk scaling, and inter-bucket aggregation with gamma including S-capping fallback.

**Curvature margin**: Specified in `/app/data/ir_curvature_spec.txt`. Uses exponential CVR scenarios derived from delta risk weights and sigma, per-bucket lambda-adjusted aggregation with squared correlations and phi, and inter-bucket aggregation with gamma squared and S-capping.

**Total IR margin**: Combines delta and curvature margins using `rho_delta_curvature` from `curvature_params.csv`.

**Constraints**: Only modify `DeltaCalculator.java`, `CurvatureCalculator.java`, and `RiskAggregator.java`. Do not alter `Main.java`, `Sensitivity.java`, data files, or portfolio files.

**Success**: All five portfolios in `/app/portfolios/` produce correct values for all fields within 0.01 absolute tolerance.
