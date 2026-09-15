# QARTOD Quality Control Test Specification

This document defines the quality control tests specified by the QARTOD (Quality
Assurance/Quality Control of Real-Time Oceanographic Data) project for automated
evaluation of oceanographic sensor data. Implementations must conform to the flag
convention, test algorithms, edge-case handling, and aggregation semantics below.

## Flag Convention

All tests produce integer flag arrays. The five defined flag codes are:

| Code | Label          | Meaning                                   |
|------|----------------|-------------------------------------------|
| 1    | Good           | Observation passes quality checks         |
| 2    | Not Evaluated  | Quality cannot be determined              |
| 3    | Suspect        | Observation is potentially erroneous      |
| 4    | Fail           | Observation is erroneous                  |
| 9    | Missing        | Input datum is absent or undefined        |

**Universal missing-data rule:** Any input observation that is NaN, null, or
otherwise undefined shall receive flag 9 (Missing) in every test. This
assignment takes precedence over all other flag logic.

---

## Test 1: Gross Range Test

Validates whether each observation lies within operator-defined sensor ranges.

**Parameters:**
- `fail_span` — [min, max]: absolute sensor measurement limits.
- `suspect_span` — [min, max]: expected normal operating range.

**Flagging logic:**
- Observation outside `fail_span` → **Fail (4)**.
- Observation within `fail_span` but outside `suspect_span` → **Suspect (3)**.
- Observation within both spans → **Good (1)**.

When both spans are provided, fail assessment takes precedence (i.e., a value
outside `fail_span` is always Fail regardless of `suspect_span`).

---

## Test 2: Spike Test

Identifies isolated spikes—sudden jumps followed by immediate recovery—in a
time series. Two detection methods are defined.

**Parameters:**
- `suspect_threshold` — spike magnitude triggering Suspect.
- `fail_threshold` — spike magnitude triggering Fail.
- `method` — `"average"` or `"differential"`.

### Average method

The spike statistic at index *i* (for 1 ≤ i ≤ n−2) is the absolute difference
between the observation and the arithmetic mean of its two immediate neighbors:

    S_i = |x_i − (x_{i−1} + x_{i+1}) / 2|

### Differential method

Compute the backward and forward first differences at index *i*:

    d_back  = x_i − x_{i−1}
    d_fwd   = x_{i+1} − x_i

If `d_back` and `d_fwd` have strictly opposing signs (one positive and one
negative), the observation sits at a local extremum and the spike statistic is:

    S_i = min(|d_back|, |d_fwd|)

If the signs agree, or either difference is zero (monotonic or plateau
behavior), the spike statistic is zero.

### Flagging

- S_i exceeds `fail_threshold` → **Fail (4)**.
- S_i exceeds `suspect_threshold` → **Suspect (3)**.
- Otherwise → **Good (1)**.

### Boundary and missing-data rules

- The first and last observations have no two-sided neighborhood and receive
  **Not Evaluated (2)**.
- If either neighbor of observation *i* is missing, the spike statistic is
  undefined and the observation receives **Not Evaluated (2)**.
- A missing observation itself receives **Missing (9)**.

---

## Test 3: Rate of Change Test

Flags observations where the temporal rate of change is unrealistically large.

**Parameters:**
- `threshold` — rate (observation-value units per second) above which the flag
  is Suspect.
- `fail_threshold` (optional) — rate above which the flag is Fail.

**Rate computation:** For observation index *i* (i > 0):

    R_i = |x_i − x_{i−1}| / Δt_i

where Δt_i is the elapsed time between observations *i−1* and *i*, in seconds.

The first observation (i = 0) has no predecessor; its rate is zero.

**Flagging:**
- R_i > `fail_threshold` (when provided) → **Fail (4)**.
- R_i > `threshold` → **Suspect (3)**.
- Otherwise → **Good (1)**.

---

## Test 4: Flat Line Test

Detects sensor stagnation: extended periods during which the measured value does
not change beyond a small tolerance.

**Parameters:**
- `suspect_threshold` — duration in **seconds** of constant readings to flag Suspect.
- `fail_threshold` — duration in **seconds** to flag Fail.
- `tolerance` — maximum permissible range (max − min) within a window for the
  readings to be considered "flat."

**Procedure:**

1. Determine the median sampling interval Δt (in seconds) from the timestamp
   series.
2. Convert each time-based threshold *T* to an observation count:
   `count = T / Δt` (integer division).
3. For each (count, flag_value) pair, slide a window of `count + 1` consecutive
   observations across the series. At each position, compute the window range
   (max − min). If the range is less than `tolerance`, the observation at the
   trailing edge of the window receives `flag_value`.
4. Fail-level flagging overwrites Suspect-level flagging at the same index.

**Pre-window default:** Observations whose index is less than the window count
(i.e., before the first complete window can be formed) are not flagged by this
test and default to **Good (1)**.

---

## Test 5: Climatology Test

Evaluates whether observations fall within expected value ranges for a given
time period and, optionally, depth range.

**Parameters — configuration entries:**

The test receives a list of configuration members. Each member contains:

- `tspan` — [min, max]: time bounds for applicability.
- `vspan` — [min, max]: value range defining the Good/Suspect boundary.
- `fspan` (optional) — [min, max]: value range defining the Suspect/Fail boundary.
- `zspan` (optional) — [min, max]: depth range filter.
- `period` (optional) — a datetime attribute name (e.g., `"month"`,
  `"dayofyear"`, `"week"`). When set, the time comparison extracts this
  attribute from each timestamp rather than comparing full datetime values.

**Matching:**

For each observation, determine which configuration members apply:

- If `period` is set, extract the corresponding attribute from the timestamp
  (e.g., month number) and check whether it falls within `tspan`.
- If `period` is not set, compare the full timestamp against `tspan` bounds.
- If `zspan` is provided, the observation's depth must additionally fall within
  `zspan`.

An observation that matches no configuration member remains **Not Evaluated (2)**.

**Flagging (for matched observations):**

- Outside `fspan` (if provided) → **Fail (4)**.
- Outside `vspan` but within `fspan` (or no `fspan`) → **Suspect (3)**.
- Within `vspan` → **Good (1)**.

When multiple configuration members match the same observation, the last
matching member's result takes precedence.

---

## Test 6: Attenuated Signal Test

Detects loss of sensor sensitivity by measuring whether the signal exhibits
sufficient variability.

**Parameters:**
- `suspect_threshold` — variability statistic below which the flag is Suspect.
- `fail_threshold` — variability statistic below which the flag is Fail.
- `check_type` — `"range"` (peak-to-peak range) or `"std"` (standard deviation).
- `test_period` (optional) — rolling window duration in seconds. When absent,
  the statistic is computed once over the entire non-missing series and applied
  uniformly to all observations.

**Flagging:**

- Statistic ≥ `suspect_threshold` → **Good (1)**.
- Statistic < `suspect_threshold` → **Suspect (3)**.
- Statistic < `fail_threshold` → **Fail (4)**.
- Statistic undefined (e.g., all-NaN window) → **Not Evaluated (2)**.

Note the direction: *higher* variability is Good; *lower* variability indicates
an attenuated (degraded) signal.

---

## Test 7: Density Inversion Test

Detects physically implausible density inversions in the water column (lighter
water beneath denser water, violating gravitational stability).

**Parameters:**
- `suspect_threshold` — negative threshold for the density variation statistic.
- `fail_threshold` — more-negative threshold triggering Fail.

**Density variation statistic:**

For each consecutive observation pair (i, i+1), compute:

    V_i = sign(z_{i+1} − z_i) × (ρ_{i+1} − ρ_i)

where *z* is depth and *ρ* is density. A negative V_i indicates an inversion:
density is decreasing in the direction of increasing depth.

**Flagging:**

- V_i < `fail_threshold` → observations *i* and *i+1* both receive **Fail (4)**.
- V_i < `suspect_threshold` (but ≥ fail) → both receive **Suspect (3)**.
- Otherwise → **Good (1)**.

When an observation is involved in multiple adjacent pairs, the most severe
flag assignment applies.

**Missing-data propagation:** A missing observation receives **Missing (9)**.
Additionally, the observation immediately *following* a missing observation also
receives **Missing (9)**, because the density variation across the gap cannot be
evaluated.

---

## Flag Aggregation

When multiple QC tests are applied to a single data stream, individual test
flag arrays are combined into a single aggregate flag array.

**Priority hierarchy (ascending precedence):**

    Missing (9) < Not Evaluated (2) < Good (1) < Suspect (3) < Fail (4)

At each observation index, the aggregate flag is the value with the **highest
precedence** among all contributing test results.

Notable consequence: **Good (1) has higher precedence than both Missing (9) and
Not Evaluated (2).** If one test produces Good and another produces Missing at
the same index, the aggregate is Good—the sensor is confirmed operational by at
least one test that could evaluate the datum.

Examples:
- Good + Suspect → Suspect
- Good + Missing → Good
- Fail + any combination → Fail
