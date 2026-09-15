# ERDDAP REST API and CF Conventions Reference

## Overview

ERDDAP supports two data access protocols depending on dataset type:
- **griddap** for gridded/array datasets (identified by `GRID` blocks in DDS)
- **tabledap** for tabular/in-situ datasets (identified by `Sequence` blocks in DDS)

## Griddap

### URL Structure
```
{server}/griddap/{datasetID}.{fileType}?{query}
```

### Query Syntax
Request specific variables with dimension constraints:
```
variableName[(dim1Start):stride1:(dim1Stop)][(dim2Start):stride2:(dim2Stop)]...
```

- Dimension constraints are enclosed in `[( )]` brackets
- Multiple dimensions are concatenated left to right
- **Dimension order must match the dataset's DDS declaration order**
- `stride` controls subsampling (stride of 1 = every value, stride of N = every Nth value)
- Stride is calculated as: `round(targetResolution / sourceSpacing)`, minimum 1. Use stride 1 when no target resolution is specified.

For a dimension with a single fixed value (e.g., altitude or depth level):
```
[(value)]
```

Multiple variables sharing the same dimensions repeat the full constraint set:
```
var1[(...)][(...)]...,var2[(...)][(...)]...
```

### Example
```
https://server/erddap/griddap/myDataset.csv?temperature[(2020-01-01T00:00:00Z):1:(2020-01-31T00:00:00Z)][(30.0):2:(40.0)][(200.0):2:(210.0)]
```

## Tabledap

### URL Structure
```
{server}/tabledap/{datasetID}.{fileType}?{query}
```

### Query Syntax
List requested variables, then append filter constraints:
```
var1,var2&constraint1&constraint2...
```

Constraints use comparison operators:
```
variableName>=value
variableName<=value
variableName=value
```

### Example
```
https://server/erddap/tabledap/myBuoys.csv?temperature,salinity&time>=2020-01-01T00:00:00Z&time<=2020-01-31T00:00:00Z&latitude>=30&latitude<=40&longitude>=-130&longitude<=-120
```

## Dataset Metadata Formats

### DAS (Dataset Attribute Structure)
Contains variable attributes including:
- `actual_range`: min/max values for coordinate variables
- `spacing`: uniform spacing for spatial and temporal dimensions (degrees for lat/lon, seconds for time)
- `axis`: coordinate axis identifier (T=time, X=longitude, Y=latitude, Z=vertical)
- `standard_name`: CF convention standard variable name identifying the physical quantity
- `units`: measurement units
- `ancillary_variables`: space-separated list of related quality/error variable names (CF-1.6 convention)

Global attributes (in the `NC_GLOBAL` block) include:
- `cdm_data_type`: dataset classification (Grid, TimeSeries, Trajectory, etc.)
- `geospatial_lon_min`, `geospatial_lon_max`: longitude extent of data coverage
- `geospatial_lat_min`, `geospatial_lat_max`: latitude extent of data coverage

**Note:** Table dataset DAS wraps variable attributes inside a sequence block `s { ... }`.

### DDS (Dataset Descriptor Structure)
Describes the dataset's structure:
- **Grid datasets** contain `GRID { ARRAY: ... MAPS: ... }` blocks showing variable dimensions and their ordering
- **Table datasets** contain `Sequence { ... }` blocks listing available variables and their types

## CF Conventions for Data Fusion

### standard_name Attribute
The `standard_name` attribute identifies the physical quantity a variable represents, following the CF Standard Name Table. Variables with the **same** `standard_name` across different datasets measure the same quantity. When fusing data, variables sharing a `standard_name` but using different `units` require unit conversion to a common target.

### ancillary_variables Attribute
The `ancillary_variables` attribute (CF-1.6+) is a space-separated list of variable names that provide quality, uncertainty, or status information for the parent variable. When requesting a variable that declares `ancillary_variables`, the referenced variables should be automatically included in data requests to enable quality-aware analysis. Only include ancillary variables that actually exist in the dataset's DDS structure.

### Unit Harmonization
When multiple datasets in a query share the same `standard_name` but use different units:
1. Count the frequency of each unit among participating datasets
2. Select the most common unit as the target
3. In case of a tie, prefer `degree_C` over `kelvin`
4. Compute conversion factors: `target_value = source_value * scale + offset`

Common conversions:
- Kelvin to Celsius: scale=1.0, offset=-273.15

## Longitude Conventions

Datasets use either `0-360` or `-180/180` longitude systems:
- **0-360**: `geospatial_lon_min` in NC_GLOBAL is non-negative
- **-180/180**: `geospatial_lon_min` in NC_GLOBAL is negative

When a query region is specified in a different convention than the target dataset:
- `-180/180` to `0-360`: add 360 to negative values
- `0-360` to `-180/180`: subtract 360 from values > 180

If the converted range produces start > stop, the query crosses the antimeridian and must be split into two sub-requests using the dataset's actual coordinate boundaries as split points.

## Spatial Coverage Analysis

For each query-dataset pair, compute the fraction of the query's spatial domain actually covered by the dataset:
- `latitude_fraction = overlap / query_range` where `overlap = min(query_max, ds_max) - max(query_min, ds_min)`
- Same logic for longitude (after coordinate convention conversion)
- Coverage fractions range from 0.0 (no overlap) to 1.0 (full coverage)

## Supported File Types
Common output formats: `.csv`, `.json`, `.nc`, `.htmlTable`, `.mat`
