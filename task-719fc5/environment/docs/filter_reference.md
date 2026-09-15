# Costmap Filter Info Server Reference

## Filter Type Codes

Each costmap filter info server has a `type` parameter that identifies the filter category. Using the wrong type causes the filter to misinterpret mask data.

| Type | Filter | Description |
|---|---|---|
| 0 | Keepout filter / Preferred lane | Binary obstacle zones — marks areas as lethal or preferred |
| 1 | Speed filter | Speed limit zones — applies velocity scaling |

## Speed Filter Computation

The speed filter computes speed limits using:

```
speed_limit = base + multiplier * filter_value
```

For **percentage-based** speed limits (the standard configuration):
- `base`: 100.0 (represents 100% of maximum speed)
- `multiplier`: -1.0 (filter values reduce speed from 100%)
- Result: filter_value=0 → 100% speed, filter_value=50 → 50% speed, filter_value=100 → 0% speed

**A positive multiplier inverts the behavior**: the robot speeds up in zones intended to slow it down, which is dangerous.

## Keepout Filter Configuration

For keepout zones:
- `type`: 0
- `base`: 0.0
- `multiplier`: 1.0

The keepout filter uses binary mask values to mark areas as lethal obstacles in the costmap.

## Filter Info Topics

Each filter info server publishes filter metadata on its `filter_info_topic`. The corresponding costmap filter plugin subscribes to this topic. The topic names must match between the filter info server and the costmap filter plugin configuration.
