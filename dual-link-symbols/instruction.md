In `/app/` you have `legacy_app`, a stripped ELF binary that depends on `libprocessor.so.2` — a discontinued data processing library. The original v2 library is no longer available, so the application cannot currently run.

Available in `/app/`:
- `libprocessor_v2.h` — the original v2 API header
- `libprocessor_v5/` — complete source code for the current v5 replacement library (API-incompatible with v2)
- `test_data.csv` — input data that `legacy_app` processes

**Objective**: Without modifying `legacy_app`, make it run successfully and produce correct output at `/app/output.txt`.

Additionally, produce `/app/compatibility_assessment.json` — a structured analysis of the v2-to-v5 API differences. This file must conform to the schema specified below.

## `compatibility_assessment.json` Schema

The JSON file must be a single object with the following top-level keys:

### `mappings` (required, array)

An array of objects, minimum 5 entries. Each object documents the relationship between one v2 API function and its v5 counterpart. Required fields per entry:

| Field | Type | Description |
|-------|------|-------------|
| `v2_function` | string | Name of the v2 API function |
| `v2_signature` | string | Full C function signature from the v2 header |
| `v5_function` | string | Name of the corresponding v5 function |
| `v5_signature` | string | Full C function signature from the v5 header |
| `change_type` | string | Classification of the change (e.g. `"renamed"`, `"renamed_and_signature_changed"`, `"renamed_and_semantics_changed"`) |
| `details` | string | Description of what changed between versions |
| `complexity` | string | One of: `"trivial"`, `"low"`, `"moderate"`, `"high"` |

### `struct_changes` (required, array)

An array of objects, minimum 2 entries. Each object documents a field-level difference between the v2 and v5 record structures. Required fields per entry:

| Field | Type | Description |
|-------|------|-------------|
| `field` | string | Name of the struct field |
| `change` | string | Type of change (e.g. `"position_moved"`, `"type_or_size_changed"`, `"added_in_v5"`) |
| `impact` | string | Description of the impact on binary compatibility |

### Risk assessment (required, one of the following top-level keys)

Exactly one of these keys must be present as a top-level string field: `overall_risk`, `risk`, `risk_assessment`, `overall_assessment`, or `risk_level`. Its value should summarize the overall compatibility risk (e.g. `"low"`, `"moderate"`, `"high"`).