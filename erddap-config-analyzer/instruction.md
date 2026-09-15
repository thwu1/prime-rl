Build `/app/reconcile.sh` -- a pipeline that audits an ERDDAP server configuration by cross-referencing its `datasets.xml` against pre-captured OPeNDAP server metadata and a local NetCDF source file.

`/app/datasets.xml` contains ERDDAP dataset definitions including composite types (SideBySide, AggregateExistingDimension, Lon0360, LonPM180) with multi-level nesting. `/app/server_metadata/` has pre-captured `.das` (Data Attribute Structure) and `.dds` (Data Descriptor Structure) files from OPeNDAP source servers for selected leaf datasets. `/app/source_data/sample_bathy.nc` is a binary NetCDF file referenced by one local-file dataset. `/app/cf_standard_names.csv` provides CF convention standard names for validation. `/app/reference/` documents the DAS, DDS, and NCCSV formats and the required output schema.

The pipeline must produce:

**`/app/output/reconciliation.json`** conforming to `/app/reference/report_schema.md`:
- `datasets` array: for each leaf dataset with available source metadata, cross-reference source DAS/DDS (or `ncdump -h` output for local `.nc` files) against the XML configuration. Detect source-only variables, config-only variables, OPeNDAP-to-config data type mismatches, attribute value conflicts between source and XML `addAttributes`, and CF `standard_name` violations (names not in the CF table).
- `hierarchy_audit` array: for each composite dataset type, resolve effective variables through the type hierarchy (SideBySide merges from children, Aggregate takes first child, Lon wrappers delegate), verify axis compatibility across children.
- `netcdf_summary` object: dimensions, variables (with types and dimension lists), and global attributes extracted from the sample `.nc` file.

**`/app/output/datasets_nccsv/<dataset_id>.nccsv`** for each leaf dataset with DAS/DDS source metadata. Format per `/app/reference/nccsv_format.md`: global attributes first, then axis variables in dimension order, then data variables alphabetically. Each variable gets a `*DATA_TYPE*` line followed by attributes in alphabetical order. Use source variable names. Terminate with `*END_METADATA*`.

No Python NetCDF library is installed; use `ncdump` for binary NetCDF inspection. `xmlstarlet` and `jq` are also available.