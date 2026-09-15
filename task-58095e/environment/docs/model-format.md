# Model Format Reference

## Directory Structure

The seismic source model follows the nshmp-haz directory convention:

```
model/
  calc-config.json          Configuration for hazard calculation
  active-crust/
    gmm-config.json         Ground motion model logic tree and coefficients
    fault/
      sources.xml           Fault source definitions (nshmp-haz XML)
      utm-traces.csv        Supplemental fault traces in projected CRS
    grid/
      rates.csv             Gridded background seismicity point sources
```

## calc-config.json

Calculation configuration in nshmp-haz format. Contains:

- `hazard.imts`: Array of IMT identifiers (e.g., "PGA", "SA0P2", "SA1P0")
- `hazard.customImls`: Map of IMT to array of intensity measure levels
- `hazard.exceedanceModel`: Exceedance model type
- `hazard.truncationLevel`: Sigma truncation level
- `model.ruptureFloating`: Rupture floating strategy ("OFF" or "ALONG_STRIKE")
- `model.surfaceSpacing`: Spacing (km) for floating rupture positions
- `model.ruptureScaling`: Scaling relation for rupture length ("WC94_LENGTH")
- `disagg.returnPeriod`: Return period for deaggregation (years)
- `disagg.bins`: Deaggregation bin specification with Unicode keys
  (e.g., `Δm` for magnitude bin width, `εMin`/`εMax` for epsilon range)
- `site`: Site coordinates and Vs30
- `performance.maxDistance`: Maximum source-to-site distance (km)

## Fault Sources XML

Fault sources use the nshmp-haz XML format:

```xml
<FaultSourceSet name="..." weight="1.0">
    <Source name="..." id="N">
        <IncrementalMfd type="GR|SINGLE" weight="W" ... />
        <!-- Multiple IncrementalMfd elements = epistemic branches -->
        <Geometry dip="..." rake="..." upperDepth="..." lowerDepth="...">
            <Trace>lon1,lat1,depth1 lon2,lat2,depth2 ...</Trace>
        </Geometry>
    </Source>
</FaultSourceSet>
```

- Trace coordinates: whitespace-separated `longitude,latitude,depth` tuples
- GR MFD attributes: `a`, `b`, `dMag`, `mMin`, `mMax`
- SINGLE MFD attributes: `m`, `rate`
- Geometry: `dip` (degrees from horizontal), `upperDepth` and `lowerDepth`
  (km, seismogenic depth bounds)
- A source with multiple `<IncrementalMfd>` elements represents epistemic
  branches; each branch has a `weight` attribute (weights sum to 1.0)

## UTM Fault Traces CSV

Supplemental fault data with coordinates in a projected CRS (identified by
the `crs` column). Columns include easting/northing pairs for each trace
endpoint, geometric parameters, and MFD parameters. These coordinates must
be transformed to WGS84 (EPSG:4326) before use in distance computations.

## Grid Sources CSV

Point sources for background seismicity with columns: source_id, name,
longitude, latitude, depth_km, mfd_type, and MFD parameters.
Coordinates are in WGS84 (EPSG:4326). The `depth_km` field specifies
the source depth used for rupture distance computation (Z_tor).

## GMM Configuration JSON

Ground motion model logic tree with period-dependent coefficients. Contains:

- `formula_notes`: Description of the GMM functional form
- `imt_periods`: Map from IMT identifier to spectral period in seconds
- `models`: Array of GMMs, each with:
  - `id`: Model identifier
  - `weight`: Logic tree weight (weights sum to 1.0)
  - `distanceType`: Distance metric required (`R_JB` or `R_RUP`)
  - `sigmaModel`: Sigma decomposition (`TOTAL` or `PARTITIONED`)
  - `coefficients`: Map from IMT to coefficient dictionary
    - For `TOTAL` sigma models: includes `sigma`
    - For `PARTITIONED` models: includes `tau` (inter-event) and `phi`
      (intra-event) standard deviations
    - Models using `R_RUP` may include `c_ztor` (depth-to-rupture coefficient)
