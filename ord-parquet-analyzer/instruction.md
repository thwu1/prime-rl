Build `/app/ord_analyze.py`, a CLI tool that analyzes Open Reaction Database (ORD) parquet datasets and produces a structured JSON report.

**Usage**: `python3 /app/ord_analyze.py <parquet_file> <output_json>`

The protobuf schema at `/app/reaction.proto` defines the `Reaction` message hierarchy. A sample ORD dataset at `/app/sample.parquet` demonstrates the serialization format. Examine both to understand the data layout, metadata encoding, and nested message structure.

**Output JSON schema:**

```json
{
  "dataset_name": "string",
  "dataset_description": "string",
  "num_reactions": 0,
  "validation": {
    "duplicate_reaction_ids": [],
    "orphaned_crude_refs": [{"reaction_id": "", "orphaned_ref": ""}],
    "orphaned_preparation_refs": [{"reaction_id": "", "orphaned_ref": ""}],
    "self_references": [],
    "invalid_analysis_keys": [{"reaction_id": "", "product_index": 0, "measurement_index": 0, "key": ""}]
  },
  "yields": [
    {"reaction_id": "", "yield_percent": 0.0, "temperature_celsius": null, "time_hours": null, "pressure_bar": null}
  ],
  "statistics": {
    "mean_yield": 0.0, "std_yield": 0.0, "median_yield": 0.0, "num_yields": 0,
    "yield_by_temperature_bin": {"below_0": {"mean": 0.0, "count": 0}},
    "yield_by_analysis_type": {"LCMS": {"mean": 0.0, "count": 0}}
  }
}
```

`dataset_name` and `dataset_description` come from dataset-level metadata embedded in the parquet file.

`validation` detects cross-reference integrity violations across all reactions. `duplicate_reaction_ids`: IDs appearing more than once (sorted). `orphaned_crude_refs`: crude mixture input references pointing to reaction IDs absent from the dataset. `orphaned_preparation_refs`: synthesized-compound preparation references pointing to absent IDs. `self_references`: reactions whose inputs reference their own ID (sorted). `invalid_analysis_keys`: product measurements whose analysis key has no matching entry in the parent outcome's analysis map.

`yields` contains every yield-type product measurement that has a percentage value. Each entry includes the reaction's normalized temperature setpoint (Celsius), the parent outcome's reaction time (hours), and pressure setpoint (bar). Use `null` for absent conditions. All pressure unit variants defined in the schema must be handled.

`yield_by_temperature_bin` groups yields by temperature: `below_0` (<0°C), `0_to_25` ([0,25)), `25_to_50` ([25,50)), `50_to_100` ([50,100)), `above_100` (≥100°C). Omit empty bins. Exclude yields without temperature.

`yield_by_analysis_type` groups yields by the analysis type of the analysis referenced through each measurement's analysis key. Use the protobuf enum name as key (e.g., `"LCMS"`, `"GC"`, `"WEIGHT"`). Exclude measurements whose analysis key is invalid or absent from the outcome's analysis map.

`std_yield` is population standard deviation. Round all floats to 4 decimal places.
