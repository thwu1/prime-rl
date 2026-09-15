# Reconciliation Report Schema

The output at `/app/output/reconciliation.json` must conform to this structure.

## Top-Level Structure

```json
{
  "datasets": [ ... ],
  "hierarchy_audit": [ ... ],
  "netcdf_summary": { ... }
}
```

## `datasets` Array

One entry per leaf dataset that has source metadata available (DAS/DDS files in `/app/server_metadata/` or a local `.nc` file for `EDDGridFromNcFiles` datasets).

```json
{
  "dataset_id": "<string>",
  "dataset_type": "<string, e.g. EDDGridFromDap>",
  "source_type": "opendap | local_file",
  "metadata_source": "<path to .das file or .nc file>",
  "config_data_variables": [
    {"source_name": "<sourceName from XML>", "destination_name": "<destinationName>", "config_type": "<dataType from XML>"}
  ],
  "source_data_variables": [
    {"name": "<variable name from source>", "type": "<config-equivalent type: float/double/short/int/byte>"}
  ],
  "discrepancies": {
    "source_only_vars": ["<data vars in source but not configured in XML>"],
    "config_only_vars": ["<data vars in XML config but not found in source>"],
    "type_mismatches": [
      {"variable": "<source_name>", "config_type": "<from XML>", "source_type": "<from DDS/ncdump, config-equivalent>"}
    ],
    "attribute_conflicts": [
      {"variable": "<source_name>", "attribute": "<attr_name>", "source_value": "<from DAS/ncdump>", "config_value": "<from XML addAttributes>"}
    ],
    "cf_violations": [
      {"variable": "<source_name>", "standard_name": "<value from source>", "reason": "not_in_cf_table"}
    ]
  }
}
```

### Field Details

- **source_only_vars / config_only_vars**: compare DATA variables only (not axis variables). Match by source variable name.
- **type_mismatches**: compare using config-equivalent types. OPeNDAP `Float32`=`float`, `Float64`=`double`, `Int16`=`short`, `Int32`=`int`, `Byte`=`byte`.
- **attribute_conflicts**: only attributes present in BOTH source (DAS or ncdump) AND XML `addAttributes` with different string values. For numeric attributes, values like `0.0` and `0` are equivalent.
- **cf_violations**: check source (DAS/ncdump) `standard_name` attributes against `/app/cf_standard_names.csv`. Report if the standard_name is not found in the CF table.
- **source_type**: `"opendap"` for datasets with DAS/DDS metadata, `"local_file"` for datasets sourced from local `.nc` files.
- For `local_file` datasets: determine which variables are axes vs data by comparing against the XML `axisVariable` entries. Variables in the `.nc` file that are not listed as `axisVariable` in XML and not listed as `dataVariable` in XML are `source_only_vars`.

## `hierarchy_audit` Array

One entry per composite dataset type (EDDGridSideBySide, EDDGridAggregateExistingDimension, EDDGridLon0360, EDDGridLonPM180). Only active top-level datasets.

```json
{
  "dataset_id": "<string>",
  "dataset_type": "<string>",
  "children": ["<direct child dataset IDs>"],
  "effective_variables": [
    {"source": "<sourceName>", "dest": "<destinationName>", "from_child": "<child_dataset_id>"}
  ],
  "axis_compatibility": {
    "compatible": true,
    "shared_axes": ["<axis source names from first child>"],
    "issues": []
  }
}
```

### Hierarchy Resolution Rules

- **EDDGridSideBySide**: Effective variables are collected from ALL children. Each entry includes `from_child` indicating which child contributed it. Axes come from the first child.
- **EDDGridAggregateExistingDimension**: Effective variables and axes come from the FIRST child only.
- **EDDGridLon0360 / EDDGridLonPM180**: Effective variables and axes are delegated entirely to the single child dataset. Resolution is recursive.
- For nested composites (e.g., Lon0360 wrapping SideBySide), resolution proceeds recursively through the full hierarchy.
- `axis_compatibility.compatible` is `true` if all children share the same set of axis source names.
- If a child dataset has no explicit variable definitions (e.g., `EDDGridFromErddap` with only a `sourceUrl`), its `effective_variables` contribution is empty.

## `netcdf_summary` Object

Summary of the local NetCDF file at `/app/source_data/sample_bathy.nc`, extracted via `ncdump -h`.

```json
{
  "file": "/app/source_data/sample_bathy.nc",
  "dimensions": {"<dim_name>": <size>, ...},
  "variables": [
    {"name": "<string>", "type": "<string>", "dimensions": ["<dim_names>"]}
  ],
  "global_attributes": {"<attr_name>": "<attr_value>", ...}
}
```

- `variables` includes ALL variables (axes and data).
- `type` uses ncdump type names: `float`, `double`, `short`, `int`, `byte`.
- `dimensions` lists dimension names for each variable in declaration order.
