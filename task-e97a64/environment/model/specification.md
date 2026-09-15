# PSHA Calculation Specification

This document defines the exact algorithms for the probabilistic seismic hazard
analysis (PSHA) calculation.

## Gutenberg-Richter MFD Discretization

For parameters (a, b, mMin, mMax, dMag):
- Magnitude bins centered at: mMin, mMin+dMag, mMin+2*dMag, ..., mMax
- Incremental annual rate at magnitude bin m:
  rate(m) = 10^(a - b*(m - dMag/2)) - 10^(a - b*(m + dMag/2))

## Distance Calculation (Flat-Earth)

- dx_km = (lon2 - lon1) * 111.0 * cos(mean_latitude_radians)
- dy_km = (lat2 - lat1) * 111.0
- R_km = sqrt(dx^2 + dy^2)

For point sources: R_jb = horizontal distance from site to source location.
For fault sources: R_jb = minimum distance from site to the rupture's surface
projection segment (the portion of the fault trace that is rupturing).

Minimum R_jb clamp: max(R_jb, 0.1) to avoid log(0) in GMM.

## Ground Motion Model

    ln(PGA) = c0 + c1*(M-6) + c2*(M-6)^2 + c3*ln(sqrt(R_jb^2 + h^2))
              + c_site*ln(min(Vs30, 760)/760)

Coefficients and sigma are defined per GMM branch in gmm.json.

## Exceedance Probability (Upper-Only Truncation)

Given GMM mean mu and standard deviation sigma at (M, R_jb, Vs30):

    epsilon = (ln(IML) - mu) / sigma

    P(exceed IML) = [Phi(n) - Phi(epsilon)] / Phi(n)     if epsilon < n
                  = 0                                      if epsilon >= n

where Phi = standard normal CDF, n = truncation level (3.0).

## Fault Floating Ruptures

For a fault with total trace length L_total and a rupture at magnitude M:

1. Compute rupture length: L_rup = 10^(-3.22 + 0.69*M) km  [Wells & Coppersmith 1994]

2. If L_rup >= L_total:
   - Single rupture position covering the full fault
   - R_jb = minimum distance from site to full fault trace
   - Rate contribution = rate(m)

3. If L_rup < L_total:
   - N_positions = ceil((L_total - L_rup) / surfaceSpacing_km) + 1
   - Positions uniformly distributed along the fault:
     offset_i = i * (L_total - L_rup) / (N_positions - 1)  for i = 0, 1, ..., N_positions-1
   - Each rupture segment spans from offset_i to offset_i + L_rup along the trace
   - Rate per position = rate(m) / N_positions
   - R_jb computed independently for each rupture segment

## Coordinate Transformation for Fault Geometry

Convert fault trace endpoints and site to local Cartesian (km) using a
reference point at the trace midpoint:

    x = (lon - ref_lon) * 111.0 * cos(ref_lat_radians)
    y = (lat - ref_lat) * 111.0

All distance computations (trace length, segment distances) use these
Cartesian coordinates.

## Hazard Integral

The annual rate of exceedance at intensity measure level IML for a site:

    lambda(IML) = sum over all sources:
                    sum over GMM branches (weight w_gmm):
                      sum over Mmax branches (weight w_mmax):
                        sum over magnitude bins:
                          w_gmm * w_mmax * rate(m) * P(exceed IML | m, R_jb)

For point sources: no Mmax branches (weight = 1.0), single R_jb per source.
For fault sources: sum also over floating rupture positions (rate divided by N_positions).

## Hazard Curve Interpolation for Return Periods

To find PGA at return period T years:
1. Target annual rate: lambda_target = 1/T
2. Interpolate in log-log space (log(lambda) vs log(IML)) between
   the two IMLs that bracket lambda_target on the hazard curve.

## Deaggregation

At the target IML corresponding to the configured return period:

1. Recompute each (M, R_jb) contribution at the target IML:
   contribution = w_gmm * w_mmax * rate(m) * P(exceed target_IML | m, R_jb)

2. Bin contributions into (M, R) matrix using configured bin parameters.
   - M bin index: floor((M - mMin) / deltaM)
   - R bin index: floor((R_jb - rMin) / deltaR)
   - Bin center: mMin + (index + 0.5) * deltaM, rMin + (index + 0.5) * deltaR

3. Summary statistics:
   - mean_M = sum(M_center * contribution) / sum(contribution)
   - mean_R = sum(R_center * contribution) / sum(contribution)
   - mode_M, mode_R = center of the (M, R) bin with maximum total contribution
