# OPeNDAP DDS (Dataset Descriptor Structure) Format

The DDS response describes the structure of a dataset: dimensions, variable types, and array shapes.

## Structure for Gridded Data

```
Dataset {
  <type> <axis_name>[<dim_name> = <size>];
  ...
  Grid {
    Array:
      <type> <var_name>[<dim1> = <size1>][<dim2> = <size2>]...;
    Maps:
      <type> <axis1>[<dim1> = <size1>];
      <type> <axis2>[<dim2> = <size2>];
      ...
  } <var_name>;
} <dataset_name>;
```

## Key Semantics

- **Top-level entries** (before the first `Grid` block) are axis/coordinate variables. Each is 1-dimensional and named after its dimension.
- **Grid blocks** each describe one data variable:
  - `Array:` line gives the variable's name, type, and full dimension signature.
  - `Maps:` lines repeat the axis variables that the data variable depends on.
- The **dataset name** appears at the end: `} datasetName;`

## Types

Same as DAS: `Float32`, `Float64`, `Int16`, `Int32`, `Byte`, `String`.

## Type Mapping to ERDDAP Config

| DDS/DAS Type | ERDDAP dataType | NCCSV type |
|-------------|-----------------|------------|
| `Float32`   | `float`         | `float`    |
| `Float64`   | `double`        | `double`   |
| `Int16`     | `short`         | `short`    |
| `Int32`     | `int`           | `int`      |
| `Byte`      | `byte`          | `byte`     |

## Extracting Information

- **Dimensions**: from top-level axis declarations, `[dimName = size]`.
- **Axis variables**: the top-level `<type> <name>[<dim> = <size>];` entries.
- **Data variables**: from `Array:` lines inside `Grid` blocks.
- **Variable name**: appears both on the `Array:` line and after the closing `}` of each `Grid` block.
