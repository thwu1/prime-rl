# PSHA Verification Model — Format Documentation

## Overview

This directory contains a synthetic seismic source model for probabilistic seismic
hazard analysis (PSHA). The model follows conventions inspired by the USGS NSHMP-haz
project.

## Directory Layout

```
model/
  model-info.json              Model metadata
  calc-config.json             Calculation configuration (site, IMLs, exceedance model)
  sources/
    fault_alpha.json           Fault source (vertical strike-slip)
    fault_beta.json            Fault source (dipping reverse, MFD logic tree)
    grid_background.json       Background gridded seismicity (point sources)
  gmm/
    gmm-tree.json              GMM logic tree (model IDs and weights)
    gmm-coefficients.json      GMM functional form and coefficients
```

## Source File Formats

### Fault Sources

```json
{
  "name": "...",
  "type": "fault",
  "trace": [[lon1, lat1], [lon2, lat2]],
  "dip": <degrees from horizontal>,
  "dipDirection": "N"|"S"|"E"|"W",
  "upperDepth": <km, depth to top of rupture>,
  "width": <km, down-dip width>,
  "rake": <degrees>,
  "mfd": <single MFD object or array of MFD objects for logic tree>
}
```

MFD types:
- **GR** (Gutenberg-Richter): `{"type":"GR", "a":..., "b":..., "mMin":..., "mMax":..., "dMag":..., "weight":...}`
- **SINGLE** (Characteristic): `{"type":"SINGLE", "m":..., "rate":..., "weight":...}`

When `mfd` is an array, each element is a logic tree branch. Branch weights
must sum to 1.0.

### Grid (Point) Sources

```json
{
  "name": "...",
  "type": "grid",
  "sources": [
    {"lon":..., "lat":..., "depth":..., "a":..., "b":..., "mMin":..., "mMax":..., "dMag":...},
    ...
  ]
}
```

Each point source uses a Gutenberg-Richter MFD.

## Ground Motion Model Specification

### Functional Form

Both GMMs use the same functional form with different coefficients:

```
ln(Y) = c1 + c2*(M - Mref) + c3*(M - Mref)^2
        + (c4 + c5*(M - Mref)) * ln(sqrt(R^2 + c6^2))
        + c7 * ln(Vs30 / Vref)
```

Where:
- `Y` is PGA in units of **g**
- `M` is moment magnitude
- `R` is distance in **km** (see distance metrics below)
- `Vs30` is time-averaged shear-wave velocity in the top 30 m (m/s)
- `Mref` and `Vref` are reference values specified in `gmm-coefficients.json`

### Aleatory Variability (Sigma)

Total sigma (log-space standard deviation):
```
sigma_total = c8 + c9 * M
```

## Distance Metrics

- **Fault sources**: Use Joyner-Boore distance (**rJB**) — the shortest horizontal
  distance from the site to the vertical projection of the rupture plane onto the
  Earth's surface.
- **Grid point sources**: Use hypocentral distance (**rHyp**):
  `rHyp = sqrt(r_horizontal^2 + depth^2)`

### Flat-Earth Approximation for Horizontal Distances

```
dx = (lon2 - lon1) * cos(lat_site * pi/180) * 111.195   [km]
dy = (lat2 - lat1) * 111.195                             [km]
r_horizontal = sqrt(dx^2 + dy^2)
```

Use the **site latitude** as the reference for longitude scaling.

### Surface Projection for rJB

- **dip = 90°**: The surface projection is the fault trace (a line segment).
  rJB is the shortest distance from the site to this line segment.

- **dip < 90°**: The surface projection is a quadrilateral strip that extends
  from the surface trace in the dip direction by `W * cos(dip)` km, where
  `W` is the fault width. The four corners are: the two trace endpoints, and
  those endpoints offset by `W * cos(dip)` in the dip direction.
  If the site lies within or above this projection, rJB = 0.

All distances are computed in the local Cartesian frame using the flat-Earth
approximation above.

## Calculation Configuration

### Exceedance Model: TRUNCATION_UPPER_ONLY

The probability of exceeding intensity measure level `y`:

```
P(Y > y | M, R) = [Phi(n) - Phi(epsilon)] / Phi(n)    if epsilon < n
                = 0                                     if epsilon >= n
```

Where:
- `epsilon = (ln(y) - mu) / sigma` (normalized residual)
- `mu` = GMM mean prediction (ln Y)
- `sigma` = GMM total sigma
- `n` = truncation level (from `truncationLevel` in config, default 3.0)
- `Phi(x)` = standard normal CDF = `0.5 * (1 + erf(x / sqrt(2)))`

## PSHA Hazard Integral

The annual rate of exceeding intensity measure level `y` at the site:

```
lambda(Y > y) = SUM over sources:
                  SUM over MFD branches (with weight w_branch):
                    w_branch * SUM over magnitude bins:
                      rate(M_i) * SUM over GMMs (with weight w_gmm):
                        w_gmm * P(Y > y | M_i, R_source)
```

### Gutenberg-Richter MFD Discretization

The GR relation: `log10(N(M)) = a - b*M`, where N(M) is the cumulative annual
rate of events with magnitude >= M.

Incremental rate for magnitude bin centered at `M_i` (bin width `dMag`):

```
rate(M_i) = 10^(a - b*(M_i - dMag/2)) - 10^(a - b*(M_i + dMag/2))
```

Bins are centered at: `mMin, mMin + dMag, mMin + 2*dMag, ..., mMax`

### Single (Characteristic) MFD

One magnitude bin at `m` with annual rate `rate`.
