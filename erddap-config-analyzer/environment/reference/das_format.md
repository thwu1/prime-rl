# OPeNDAP DAS (Dataset Attribute Structure) Format

The DAS response describes variable and global attributes for a dataset served by an OPeNDAP-compatible server (THREDDS, ERDDAP, Hyrax, etc.).

## Structure

```
Attributes {
  <variable_name> {
    <type> <attribute_name> <value>;
    ...
  }
  NC_GLOBAL {
    <type> <attribute_name> <value>;
    ...
  }
}
```

- The outer `Attributes { }` block contains one sub-block per variable, plus an optional `NC_GLOBAL` block for dataset-level attributes.
- Each attribute line has three parts: **type**, **attribute name**, and **value**, terminated by a semicolon.

## Types

| DAS Type   | Equivalent  |
|-----------|-------------|
| `String`  | text        |
| `Float32` | 32-bit IEEE float |
| `Float64` | 64-bit IEEE double |
| `Int16`   | 16-bit signed integer |
| `Int32`   | 32-bit signed integer |
| `Byte`    | 8-bit unsigned integer |

## Value Formats

- **String**: enclosed in double quotes, e.g. `"some text"`
- **Numeric scalar**: bare number, e.g. `32.0`, `-9999999.0`, `1.0E9`
- **Numeric array**: comma-separated values, e.g. `0.0, 360.0`
- Axis variables (time, latitude, longitude, altitude/depth) carry metadata like `axis`, `standard_name`, `units`, and `actual_range`.
- Data variables carry science metadata: `long_name`, `standard_name`, `units`, `_FillValue`, etc.
