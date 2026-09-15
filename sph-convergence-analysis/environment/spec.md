# SPH Regression Testing & Convergence Analysis — Algorithm Specification

## 1. Data Format

Simulation data uses the SPHinXsys XML regression format. Snapshot values are stored as **attributes** on particle elements:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<result>
    <Snapshot_Element>
        <Snapshot number_of_snapshot_for_local_result_="N" />
    </Snapshot_Element>
    <Result_Element>
        <Particle_0 snapshot_0="value" snapshot_1="value" ... snapshot_{N-1}="value" />
    </Result_Element>
</result>
```

Each file contains one time series of `N` scalar snapshots for a single observed quantity at one observer particle.

## 2. Data Organization

```
/app/data/
├── config.json              # Analysis parameters (thresholds, resolution metadata)
├── {resolution}/            # "fine", "medium", "coarse"
│   └── {quantity}/          # "Pressure", "TotalMechanicalEnergy"
│       ├── reference.xml    # Baseline reference for this resolution
│       ├── run_0.xml        # Ensemble run 0
│       ├── run_1.xml        # Ensemble run 1
│       └── ...
```

## 3. Analysis Pipeline

The analysis **must** proceed in this order — later stages depend on earlier results:

1. Parse all XML data
2. Compute DTW distances (all runs vs. their resolution's reference)
3. Detect anomalous runs from DTW distances
4. Compute ensemble statistics **excluding anomalous runs**
5. Richardson extrapolation from cleaned ensemble means at the final snapshot
6. Assemble overall assessment

## 4. Algorithm Specifications

### 4.1 Dynamic Time Warping with Sakoe-Chiba Band

Given two time series A[0..n-1] and B[0..m-1], compute the cumulative cost matrix D:

```
D[i][j] = |A[i] - B[j]| + min(D[i-1][j], D[i][j-1], D[i-1][j-1])
```

**Base cases:**
- D[0][0] = |A[0] - B[0]|
- D[i][0] = |A[i] - B[0]| + D[i-1][0]   for i > 0, if |i| <= w
- D[0][j] = |A[0] - B[j]| + D[0][j-1]   for j > 0, if |j| <= w

**Sakoe-Chiba constraint:** Only compute D[i][j] where |i - j| <= w.
Set D[i][j] = +infinity for all cells outside this band.

Band width: `w = ceil(dtw_band_fraction * max(n, m))` (read from config.json).

**Normalization:** `dtw_distance = D[n-1][m-1] / (n + m)`

A run passes DTW validation if `dtw_distance < dtw_threshold` (from config.json).

### 4.2 Anomaly Detection via Modified Z-Score

For each (resolution, quantity) combination, collect the DTW distances of all runs:
d_0, d_1, ..., d_k.

Compute:
```
median_d = median(d_0, d_1, ..., d_k)
MAD = median(|d_0 - median_d|, |d_1 - median_d|, ..., |d_k - median_d|)
modified_z_score_i = 0.6745 * (d_i - median_d) / (MAD + 1e-10)
```

A run is flagged as **anomalous** if `|modified_z_score_i| > anomaly_zscore_threshold`.

Anomaly detection is **per-quantity**: a run anomalous for Pressure but not Energy is excluded only from Pressure ensemble statistics.

### 4.3 Ensemble Convergence Analysis

For each (resolution, quantity), using only **non-anomalous** runs:

At each snapshot index t (0 to N-1):
```
ensemble_mean[t]     = (1/K) * sum(run_k[t] for k in non-anomalous runs)
ensemble_variance[t] = (1/K) * sum((run_k[t] - ensemble_mean[t])^2 for k in non-anomalous runs)
```

Temporal summaries:
```
temporal_mean_of_ensemble_mean     = (1/N) * sum(ensemble_mean[t])
temporal_mean_of_ensemble_variance = (1/N) * sum(ensemble_variance[t])
```

**Mean convergence criterion:**
```
max over t of: |ensemble_mean[t] - reference[t]| / (|reference[t]| + 1e-10)  <  convergence_threshold_mean
```

**Variance convergence criterion:**
```
max over t of: ensemble_variance[t] / (|reference[t]|^2 + 1e-10)  <  convergence_threshold_variance
```

### 4.4 Richardson Extrapolation

For each quantity, use the **ensemble mean of the final snapshot** (snapshot index N-1) at each resolution. Let:
- f_fine   = ensemble mean at fine resolution, final snapshot
- f_medium = ensemble mean at medium resolution, final snapshot
- f_coarse = ensemble mean at coarse resolution, final snapshot

With uniform refinement ratio r (from config: `refinement_ratio`):

**Convergence order:**
```
p = ln(|f_coarse - f_medium| / |f_medium - f_fine|) / ln(r)
```

**Extrapolated value:**
```
f_exact = f_fine + (f_fine - f_medium) / (r^p - 1)
```

If |f_medium - f_fine| < 1e-15, report p = NaN and f_exact = f_fine.

## 5. Output Format

Write `/app/results.json` with this exact structure:

```json
{
  "dtw_analysis": {
    "<resolution>": {
      "<quantity>": {
        "run_<i>": {
          "dtw_distance": <float>,
          "dtw_pass": <bool>
        }
      }
    }
  },
  "ensemble_convergence": {
    "<resolution>": {
      "<quantity>": {
        "temporal_mean_of_ensemble_mean": <float>,
        "temporal_mean_of_ensemble_variance": <float>,
        "mean_converged": <bool>,
        "variance_converged": <bool>
      }
    }
  },
  "richardson_extrapolation": {
    "<quantity>": {
      "convergence_order": <float>,
      "extrapolated_value": <float>,
      "values_used": {
        "fine": <float>,
        "medium": <float>,
        "coarse": <float>
      }
    }
  },
  "anomaly_detection": {
    "<resolution>": {
      "<quantity>": {
        "run_<i>": {
          "modified_z_score": <float>,
          "is_anomalous": <bool>
        }
      }
    }
  },
  "overall_assessment": {
    "all_dtw_pass": <bool>,
    "all_converged": <bool>,
    "expected_convergence_order": <float>,
    "anomalous_runs": ["<resolution>/<quantity>/run_<i>", ...]
  }
}
```

`expected_convergence_order` is the mean of convergence orders across all quantities (excluding NaN values).
