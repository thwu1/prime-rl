# Hydrological Analysis Pipeline — Algorithm Reference

This document describes the methods the `hydrosig` package is intended to
implement. Each section corresponds to a pipeline module.

## 1. Network Processing (network.py)

NHDPlus flowline network cleaning and directed acyclic graph construction.

**Input:** `/app/data/network.csv` with NHDPlus columns: comid, tocomid,
fromnode, tonode, lengthkm, slope, totdasqkm, streamorde, divergence,
terminalfl, terminalpa, hydroseq, levelpathi, fcode.

**Cleaning steps (in order):**
1. Remove coastline features (fcode=56600)
2. Disconnect minor divergent paths (divergence=2) by nullifying fromnode
3. Derive missing tocomid from node topology (match tonode to fromnode);
   terminal segments and unmatched segments get tocomid = −comid
4. Remove terminal networks with total drainage area below threshold
5. Retain only the largest weakly connected component

Build directed graph (comid → tocomid); compute topological sort.

## 2. Baseflow Separation (baseflow.py)

Lyne & Hollick (1979) recursive digital filter for quickflow/baseflow
partitioning, with multi-pass application per Nathan & McMahon (1990).

The filter recursively extracts the high-frequency quickflow component;
baseflow is the residual (total flow minus quickflow). Edge padding
(10 samples, edge-value replication) is applied before filtering and
removed afterward. For n_passes=3: one forward pass followed by one
backward+forward pair.

Parameters: α=0.925, n_passes=3, pad_width=10.

**Physical constraint:** baseflow is non-negative and bounded by total
streamflow. After filtering, enforce baseflow ∈ [0, Q].

BFI = Σ(baseflow) / Σ(streamflow).

## 3. Recession Analysis (recession.py)

### Segment Detection
Identify recession segments as periods of **strictly** monotonically
decreasing daily streamflow lasting at least 15 consecutive days. Scan the
full hydrograph tracking decreasing runs; when flow increases or the series
ends, close the current segment if it meets the minimum length criterion.

### Master Recession Curve (MRC)
Exponential matching strip method (Tallaksen, 1995). Sort recession
segments by starting flow magnitude, **highest first**. Initialize the
composite MRC with the highest-flow segment (time axis starting at 1). For
each subsequent segment in descending start-flow order, fit a log-linear
model to the existing composite MRC, compute the time shift that aligns
the new segment's starting flow onto the fitted curve, and append the
time-shifted segment. Clamp flow values to ≥1e-10 before log
transformation for numerical safety.

### Recession Constant
K = −slope from log-linear regression (scipy linregress) on the complete
composite MRC. Requires at least 2 valid recession segments.

## 4. Hydrological Signatures (signatures.py)

### Flood Moments
- MAF: mean of annual maximum daily flows (resample year-end, max, mean)
- Variance: s² = Σ(Qᵢ − MAF)² / (n−1) over all n daily values
- CV = √s² / MAF
- CS: Fisher-Pearson adjusted coefficient of skewness

### FDC Slope
Flow duration curve slope between 33rd and 67th percentiles of
log-transformed discharge (clip minimum at 1e-3 before log).

### Seasonality Index
Walsh & Lawler (1981): for each year, compute (1/R) × Σ|mᵢ − R/12| where
R is annual total and mᵢ are monthly totals. Report the multi-year mean.
The **absolute value** of monthly deviations from the uniform expectation
is essential to the definition.

### Streamflow Elasticity
Sankarasubramanian et al. (2001): **median** of annual (dQ/dP × P/Q)
ratios computed from year-to-year differences in annual mean streamflow
and precipitation.

## 5. Flow Accumulation (accumulation.py)

Topological traversal (upstream → downstream) accumulating runoff through
the cleaned network.

For each segment:
- **Local runoff:** totdasqkm × 0.001 (uniform runoff coefficient)
- **Upstream inflow:** sum of accumulated flows from all predecessor nodes
- **Routing:** attenuate upstream inflow only (NOT local runoff) through
  the segment using kinematic wave approximation:
  - Celerity (m/s): slope^0.3 (simplified Manning)
  - Travel time (days): (lengthkm × 1000) / (celerity × 86400)
  - Attenuation: exp(−0.5 × travel_time)
  - Skip routing if slope ≤ 0 or lengthkm ≤ 0
- **Accumulated flow** = routed_upstream + local_runoff

Skip artificial terminal nodes (negative comid values).
