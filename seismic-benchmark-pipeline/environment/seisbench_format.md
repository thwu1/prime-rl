# SeisBench Data Format Specification

This document describes the SeisBench dataset format and the seismic benchmark
evaluation methodology.

## Dataset Files

| File | Purpose |
|------|---------|
| `metadata.csv` | ASCII comma-separated trace-level metadata |
| `waveforms.hdf5` | Binary HDF5 file containing waveform arrays |

## HDF5 Structure

The HDF5 file contains two mandatory root-level groups:

### `data_format` group

Stores dataset-level format metadata as HDF5 datasets (not attributes):

| Key | Required | Description |
|-----|----------|-------------|
| `dimension_order` | Yes | String of dimension characters (see below) |
| `component_order` | Yes | Order of seismic components, e.g. `"ZNE"` |
| `sampling_rate` | No | Sampling rate in Hz (float) |

**Dimension characters:**

- `C` — channel (seismic component)
- `W` — width (time samples)
- `N` — trace index within a trace block (used exclusively with trace blocks)

For individual traces, use `"CW"` (channels x samples).
For trace blocks, use `"NCW"` (traces x channels x samples).

### `data` group

Contains all waveform data. Each entry under `data/` is either:
- An individual trace dataset (2D array, e.g. shape `(3, 3000)` for CW)
- A trace block dataset (3D array, e.g. shape `(50, 3, 3000)` for NCW)

## Metadata Column Naming Convention

All metadata columns follow the schema `CATEGORY_PARAMETER_UNIT`:

| Prefix | Category | Examples |
|--------|----------|----------|
| `source_` | Event/source | `source_id`, `source_origin_time`, `source_latitude_deg`, `source_longitude_deg`, `source_depth_km`, `source_magnitude`, `source_type` |
| `station_` | Recording station | `station_network_code`, `station_code`, `station_latitude_deg`, `station_longitude_deg`, `station_elevation_m` |
| `trace_` | Trace-level | `trace_name`, `trace_sampling_rate_hz`, `trace_npts`, `trace_p_arrival_sample`, `trace_s_arrival_sample`, `trace_p_status`, `trace_s_status`, `trace_snr_db`, `trace_quality` |
| `path_` | Propagation path | `path_p_travel_s`, `path_s_travel_s` |

The `trace_name` column links each metadata row to its corresponding waveform
data in the HDF5 file. For trace blocks: see below.

A `split` column indicates the data partition: `"train"`, `"dev"`, or `"test"`.

### Signal Quality Metadata

`trace_snr_db` — signal-to-noise ratio in decibels, computed on the vertical
(Z) component using the pre-P-arrival window as the noise reference and the
P-to-S-arrival window as the signal window. Defined as
10 * log10(mean(signal^2) / mean(noise^2)). Only applicable to earthquake
traces; leave empty for noise traces.

`trace_quality` — quality tier derived from `trace_snr_db`:
- `A`: SNR >= 10 dB
- `B`: 5 <= SNR < 10 dB
- `C`: SNR < 5 dB

## Component Ordering

The canonical component order for 3-component seismograms is **ZNE**
(vertical, north, east). Raw data from different instruments may use
different orderings (e.g. ENZ, ZEN). When building a dataset, all waveforms
must be normalized to the canonical ZNE ordering. This requires permuting the
component axis of each waveform according to its source component order.

## Sampling Rate

All traces in a SeisBench dataset must share a common sampling rate, recorded
in the `data_format/sampling_rate` dataset. Raw data recorded at higher
sampling rates must be decimated with proper anti-aliasing filtering to the
target rate. Pick sample indices must be adjusted proportionally when
resampling.

## Trace Blocks

For large datasets, accessing many small HDF5 datasets creates I/O bottlenecks.
The **trace block extension** packs multiple traces into a single array.

### Format

When trace blocks are used:

1. The `dimension_order` in `data_format` must include `N` (e.g. `"NCW"`)
2. The `trace_name` in metadata uses the format: `[blockname]$[index]`
   - `blockname` — name of the HDF5 dataset under `data/`
   - `index` — integer index along the N dimension
   - Example: `"block003$17"` refers to `data/block003[17, :, :]` in NCW order

### Design principles

- Adjacent metadata rows should share blocks for sequential read efficiency
- **Traces from different splits (train/dev/test) must not share a block**
- Block size is typically 50-100 traces

### Example

```
metadata.csv:
trace_name,split,...
block000$0,train,...
block000$1,train,...
block001$0,dev,...
block001$1,dev,...

waveforms.hdf5:
+-- data_format/
|   +-- dimension_order  ->  "NCW"
|   +-- component_order  ->  "ZNE"
|   +-- sampling_rate    ->  100.0
+-- data/
    +-- block000  (shape: 2 x 3 x 3000)
    +-- block001  (shape: 2 x 3 x 3000)
```

## Benchmark Evaluation Tasks

The seismic pick benchmark defines three evaluation tasks computed from model
prediction CSVs. The prediction CSVs contain per-entry `sampling_rate` values
that must be used in onset-timing computations.

### Task 1 — Earthquake Detection

Binary classification: earthquake vs. noise.

- **Threshold optimization:** Compute the full precision-recall curve over
  all unique score values in the dev set. Select the threshold that maximizes
  the F1-score. Use the `score_detection` column as the continuous score and
  `true_label` (1=earthquake, 0=noise) as ground truth.
- **Test metrics:** At the dev-optimized threshold, compute precision, recall,
  and F1-score on the test set using `score_detection > threshold` as the
  binary prediction. Compute AUC-ROC on the test set (threshold-independent).

### Task 2 — Phase Classification

Binary classification of seismic phases: P wave vs. S wave.

- **Input:** `score_p_or_s` — probability that the pick is a P phase
  (high -> P, low -> S). Binary label: P=1, S=0.
- **F1 threshold optimization:** Same precision-recall curve procedure as
  Task 1, applied to `score_p_or_s` on the dev set.
- **MCC threshold optimization:** Independently optimize the Matthews
  Correlation Coefficient threshold using 50 evenly-spaced quantile
  candidates drawn from the sorted dev `score_p_or_s` values. Select the
  candidate that maximizes MCC on the dev set. This threshold is separate
  from the F1 threshold.
- **Test metrics:** precision, recall, F1 (using F1-optimized threshold),
  and MCC (using MCC-optimized threshold), all on the test set.

### Task 3 — Onset Timing (Pick Localization)

Accuracy of predicted arrival-time samples relative to analyst picks.

For each phase (P and S separately):
1. Identify the correct prediction column for the current phase: use
   `p_sample_pred` for P-phase rows and `s_sample_pred` for S-phase rows.
2. Compute the residual in seconds:
   `residual = (predicted_sample - phase_onset) / sampling_rate`
   where `sampling_rate` is the **per-entry** value from the prediction CSV.
3. Report the following **test-set** metrics per phase:
   - `mean_s`: mean of residuals
   - `std_s`: root-mean-square of residuals, i.e. sqrt(mean(residual^2))
   - `mae_s`: mean absolute error of residuals

Note: The `std_s` metric is the root-mean-square (RMS), not the population
standard deviation. This distinction matters when the mean residual is
non-zero.
