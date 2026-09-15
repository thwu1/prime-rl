# PSHA Methodology Reference

## Probabilistic Seismic Hazard Analysis

PSHA computes the annual rate at which ground motion intensity exceeds specified
levels at a site, integrating over all contributing earthquake sources and
their epistemic uncertainties. The total exceedance rate at an intensity
measure level (IML) sums contributions from every source-magnitude-GMM
combination: the earthquake occurrence rate multiplied by the conditional
exceedance probability and the logic-tree weight.

## Intensity Measure Types

Modern PSHA computes hazard for multiple intensity measure types (IMTs)
simultaneously. PGA (peak ground acceleration) corresponds to spectral period
T = 0 s. Spectral acceleration SA(T) represents the response of a
single-degree-of-freedom oscillator at period T. Each IMT uses its own set of
ground motion model coefficients. A complete hazard assessment produces one
hazard curve per IMT.

## Distance Metrics

**Joyner-Boore distance (R_JB)** is the shortest horizontal distance from the
site to the surface projection of the fault rupture plane. For a vertical fault
(dip = 90 deg), the surface projection is the fault trace itself. For dipping
faults, the surface projection forms a polygon extending from the trace in the
down-dip direction; R_JB is zero when the site lies inside this polygon. For
point sources, use great-circle (haversine) epicentral distance.

**Rupture distance (R_RUP)** is the shortest three-dimensional distance from
the site to the fault rupture surface. Unlike R_JB, it accounts for source
depth. R_RUP can be approximated as:

    R_RUP = sqrt(R_JB^2 + Z_tor^2)

where Z_tor is the depth to the top of the rupture (upper depth for fault
sources, source depth for point sources). Each GMM in the logic tree specifies
which distance metric it requires via the `distanceType` field.

Sources beyond the maximum distance cutoff are excluded from the computation.

## Magnitude-Frequency Distributions

**Gutenberg-Richter (GR)**: Parameterized by a-value, b-value, and magnitude
range [m_min, m_max] with bin width dMag. Discretized into incremental rates:
rate(m) = 10^(a - b*(m - dMag/2)) - 10^(a - b*(m + dMag/2)) for each
magnitude bin center m from m_min to m_max.

**Single**: A fixed magnitude with a specified annual occurrence rate.

## Epistemic MFD Branching

Fault sources may carry multiple MFD elements representing epistemic
uncertainty (e.g., alternative maximum magnitude estimates). Each MFD branch
has a weight; weights for a given source sum to 1.0. Source rates are computed
independently for each branch, multiplied by the branch weight, and the
contributions summed into the total hazard.

## Ground Motion Models

Each GMM in the logic tree produces a mean and standard deviation of the natural
logarithm of ground motion intensity, conditional on magnitude, distance, and
site parameters. The functional form and coefficients are specified in the GMM
configuration file. Coefficients are period-dependent: each IMT uses a
different coefficient set from the same model.

## Sigma Decomposition

Ground motion variability sigma can be expressed as a single total value or
partitioned into inter-event (tau) and intra-event (phi) standard deviations.
When partitioned, total sigma is the root sum of squares:

    sigma = sqrt(tau^2 + phi^2)

The GMM configuration specifies `sigmaModel` as either `TOTAL` (sigma given
directly) or `PARTITIONED` (tau and phi given separately).

## Exceedance Probability

Ground motion variability is modeled as lognormal (normal in log-space),
optionally truncated at a specified number of standard deviations above the
mean. Under upper-only truncation at level n_sigma:
P(IML | M, R) = [Phi(n_sigma) - Phi(epsilon)] / Phi(n_sigma)
where epsilon = (ln(IML) - mu) / sigma and Phi is the standard normal CDF.
When epsilon >= n_sigma, the exceedance probability is zero.

## Rupture Floating

When `ruptureFloating` is `ALONG_STRIKE`, fault ruptures do not necessarily
span the entire fault trace. The subsurface rupture length for a given
magnitude is determined by the configured scaling relation. For WC94_LENGTH
(Wells & Coppersmith, 1994, all fault types):

    log10(L_km) = -3.22 + 0.69 * M

When the computed rupture length L is less than the total fault trace length,
ruptures are placed at positions spaced by `surfaceSpacing` km along the
fault trace. The number of positions is floor((fault_length - L) / spacing) + 1.
Each position receives an equal fraction of the total occurrence rate
(rate_per_position = rate / n_positions). When L >= fault trace length, the
rupture spans the entire fault as a single position with the full rate.

For each floating position, the distance (R_JB and/or R_RUP) is computed from
that specific sub-rupture geometry, and the hazard contribution is calculated
independently for each position.

## Uniform Hazard Spectrum

A UHS extracts spectral accelerations at a target return period from individual
hazard curves computed for each IMT. For each IMT's hazard curve, interpolation
(log-log on rate vs IML) yields the spectral acceleration corresponding to the
target annual rate (= 1 / return_period). The resulting pairs of (spectral
period, spectral acceleration) form the UHS.

## Deaggregation

Deaggregation identifies which magnitude-distance-epsilon combinations
dominate the hazard at a target return period. First, the target IML is found
by interpolating the hazard curve to the target annual rate. Then the total
exceedance rate at that IML is decomposed into bins of magnitude, distance
(R_JB), and epsilon. For each source-magnitude entry and each GMM, the
contribution to each epsilon bin is computed from the truncated normal
probability mass within that bin. Mean and mode values of M, R, and epsilon
summarize the distribution.

## Poisson Conversion

Annual exceedance rates convert to probabilities of exceedance over an
exposure period T (typically 50 years) using the stationary Poisson model:
P = 1 - exp(-rate * T).

## Coordinate Reference Systems

Source coordinates may use different coordinate reference systems (CRS).
WGS84 geographic coordinates (EPSG:4326) use longitude/latitude in degrees.
Projected coordinates such as UTM (e.g., EPSG:32610 for UTM Zone 10N) use
easting/northing in meters. Coordinate transformation between CRS is
required before distance computations. The PROJ library provides tools
for coordinate transformation (cs2cs utility).
