An ASAM OpenDRIVE road network is at `/app/network.xodr`. An ASAM OpenSCENARIO scenario referencing this network is at `/app/scenario.xosc`. The scenario positions vehicle entities on the road using road-relative coordinates; some positions reference roads or lanes that do not exist in the network.

Produce three deliverables:

## 1. Quality Checker Report — `/app/qc_report.json`

Validate `/app/network.xodr` for ASAM conformance using the `asam-qc-opendrive` checker bundle (available on PyPI). Write a JSON summary:

```json
{
  "checkers_run": <int>,
  "checkers_passed": <int>,
  "issues_found": <int>,
  "checker_details": [
    {"checker_id": "<string>", "status": "<string>", "issues": <int>}
  ]
}
```

## 2. Entity Position Analysis — `/app/entity_positions.json`

Extract each scenario entity's initial position from the `.xosc` file, resolving any `ParameterDeclaration` variable substitutions used in position attributes. For entities with valid road/lane references, convert to Cartesian (x, y, z). For invalid references, report the error. Entity positions correspond to the lane center at the given s-coordinate.

```json
{
  "entities": {
    "<name>": {
      "road_id": <int>, "lane_id": <int>, "s": <float>,
      "valid": <bool>,
      "x": <float or null>, "y": <float or null>, "z": <float or null>,
      "error": <string or null>
    }
  },
  "cross_ref_errors": ["<description>", ...]
}
```

## 3. Geometry Query Engine — `/app/odr_eval.py`

```
python3 /app/odr_eval.py <xodr_path> <queries_json> <results_json>
```

Reads a JSON list of query objects from the queries file, writes a JSON list of results. Query types:

| type | params | output |
|------|--------|--------|
| `ref_point` | `road_id`, `s` | `x`, `y` |
| `heading` | `road_id`, `s` | `hdg` |
| `elevation` | `road_id`, `s` | `z` |
| `lane_width` | `road_id`, `s`, `lane_id` | `width` |
| `lane_edge` | `road_id`, `s`, `lane_id` | `x`, `y` |

Accuracy: coordinates within 0.01 m, headings within 0.001 rad, widths/elevations within 0.001 m.