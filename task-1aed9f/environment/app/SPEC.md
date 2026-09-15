# BGP Best-Path Selection Algorithm Specification

## Overview

When a BGP router receives multiple paths to the same destination prefix, it must select a single best path using a deterministic algorithm. This specification defines the complete selection algorithm that your engine must implement.

## Input Format

Each scenario is a JSON object with:
- `config`: Configuration flags (all boolean, default false if absent)
- `routes`: Array of candidate route objects
- `expected_best`: Index of the expected best path (for verification)

### Configuration Flags

| Flag | Default | Description |
|------|---------|-------------|
| `always_compare_med` | false | Compare MED across all paths regardless of neighbor AS |
| `deterministic_med` | false | Group paths by neighbor AS before comparison |
| `as_path_ignore` | false | Skip the AS-path length comparison step entirely |
| `compare_routerid` | false | Skip the "oldest path" step and proceed directly to router-id comparison |
| `med_missing_as_worst` | false | Treat missing MED as 4294967295 instead of 0 |
| `med_confed` | false | Compare MED for paths consisting only of confederation segments |

### Route Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `weight` | int | Weight value (0-65535). Higher is preferred. |
| `local_pref` | int/null | LOCAL_PREF attribute. Default 100 if null or absent. |
| `locally_originated` | bool | True if originated locally via network/redistribute/aggregate command |
| `local_origin_type` | string | `"network"`, `"redistribute"`, or `"aggregate"`. Only relevant when `locally_originated` is true. |
| `as_path` | array | Array of AS path segment objects (see below) |
| `origin` | string | `"igp"`, `"egp"`, or `"incomplete"` |
| `med` | int/null | Multi-Exit Discriminator. null means not set. |
| `path_source` | string | `"ebgp"`, `"ibgp"`, `"confed_ebgp"`, or `"confed_ibgp"` |
| `igp_metric` | int | IGP metric to the BGP next-hop |
| `router_id` | string | BGP router ID in dotted-decimal notation |
| `originator_id` | string/null | Originator ID set by a route reflector. null if not present. |
| `cluster_list` | array | List of cluster IDs (strings). Empty if not from a route reflector. |
| `neighbor_address` | string | IP address of the BGP peer in dotted-decimal notation |
| `is_valid` | bool | Whether this path is valid and should be considered |
| `arrival_order` | int | Relative order of arrival. Lower value = arrived earlier (older). |

### AS Path Segment Format

Each element in the `as_path` array is an object with:
- `type`: One of `"AS_SEQUENCE"`, `"AS_SET"`, `"AS_CONFED_SEQUENCE"`, `"AS_CONFED_SET"`
- `asns`: Array of integer AS numbers in that segment

Example:
```json
[
  {"type": "AS_CONFED_SEQUENCE", "asns": [65001, 65002]},
  {"type": "AS_SEQUENCE", "asns": [200, 300]},
  {"type": "AS_SET", "asns": [400, 500]}
]
```

## The Best-Path Selection Algorithm

### Preprocessing

Before comparison, filter out any routes where `is_valid` is false. If no valid routes remain, return -1.

### Standard Mode

Initialize the best path as the first valid route. Then compare the current best against each subsequent valid route. If the new route is better, it replaces the current best. Continue until all valid routes have been compared.

At each comparison, apply the following steps in order. As soon as a step produces a winner, that path is selected and remaining steps are skipped.

### Step 1: Weight (Highest Wins)

Prefer the path with the higher `weight` value.

### Step 2: Local Preference (Highest Wins)

Prefer the path with the higher `local_pref`. If `local_pref` is null or absent, treat it as 100.

### Step 3: Locally Originated

Prefer a path that was locally originated (`locally_originated` = true) over one that was learned from a peer.

If both paths are locally originated, prefer `"network"` or `"redistribute"` over `"aggregate"` (based on `local_origin_type`).

### Step 4: AS-Path Length (Shortest Wins)

**Skip this step entirely if `as_path_ignore` is true in the config.**

Prefer the path with the shorter effective AS-path length. Counting rules:

- `AS_SEQUENCE`: Each AS number counts as 1.
- `AS_SET`: The entire set counts as **1**, regardless of how many AS numbers it contains.
- `AS_CONFED_SEQUENCE`: **Does not count** toward path length.
- `AS_CONFED_SET`: **Does not count** toward path length.

### Step 5: Origin Type (Lowest Wins)

Prefer the path with the lower origin type value:
- `"igp"` = 0 (best)
- `"egp"` = 1
- `"incomplete"` = 2 (worst)

### Step 6: MED — Multi-Exit Discriminator (Lowest Wins)

Prefer the path with the lower MED value, **but only when comparison is warranted**.

#### When to Compare MED

MED is compared when ANY of these conditions is true:
1. `always_compare_med` is enabled in the config.
2. `med_confed` is enabled AND both paths have AS paths consisting **only** of `AS_CONFED_SEQUENCE` and/or `AS_CONFED_SET` segments (no `AS_SEQUENCE` or `AS_SET` segments).
3. Both paths have the same **neighbor AS**. The neighbor AS is determined by finding the first AS number in the first `AS_SEQUENCE` segment of the AS path, after skipping any leading `AS_CONFED_SEQUENCE`/`AS_CONFED_SET` segments.

If none of these conditions apply, skip MED comparison entirely.

#### Handling Missing MED

If `med` is null (not set):
- Default behavior: treat as **0**.
- If `med_missing_as_worst` is enabled: treat as **4294967295**.

### Step 7: eBGP over iBGP

Prefer eBGP paths (`path_source` = `"ebgp"`) over iBGP paths.

**Confederation paths** (`"confed_ebgp"` and `"confed_ibgp"`) are treated as **internal** — there is no distinction between them, and they are not preferred over regular iBGP paths.

In other words: `"ebgp"` is external; everything else (`"ibgp"`, `"confed_ebgp"`, `"confed_ibgp"`) is internal.

### Step 8: IGP Metric to Next-Hop (Lowest Wins)

Prefer the path with the lower `igp_metric` value.

### Step 9: Multipath Determination

This step determines whether multiple paths should be installed for load-balancing. It does **not** affect best-path selection. Skip this step.

### Step 10: Oldest Path (External Only)

When both paths are from **external** peers (`path_source` = `"ebgp"`), prefer the path that was received first (lower `arrival_order` value).

**Skip this step if ANY of these conditions apply:**
- `compare_routerid` is enabled in the config.
- Both paths have the same effective router ID (after originator-id substitution per Step 11).

### Step 11: Router ID (Lowest Wins)

Prefer the path from the router with the lower router ID.

**Important:** If a path has an `originator_id` (set by a route reflector), use the `originator_id` instead of the `router_id` for comparison.

### Step 12: Cluster List Length (Shortest Wins)

If the effective router IDs (from Step 11) are equal, prefer the path with the shorter `cluster_list`.

### Step 13: Neighbor Address (Lowest Wins)

Prefer the path from the peer with the lower `neighbor_address`.

IP addresses are compared numerically (e.g., 10.0.0.1 < 10.0.0.2 < 10.0.1.0).

## Deterministic MED Mode

When `deterministic_med` is enabled in the config, the algorithm changes:

1. **Group** all valid routes by their neighbor AS (the first AS in the first `AS_SEQUENCE` segment, skipping confederation segments). Routes with no `AS_SEQUENCE` segment (neighbor AS = null) form their own group.

2. **Within each group**, select the best path using the standard algorithm described above. Since all routes in a group have the same neighbor AS, MED comparison naturally occurs at Step 6.

3. **Compare group winners** using the standard algorithm. Since winners are from different groups (different neighbor ASes), MED will only be compared if `always_compare_med` is enabled.

This ensures that the result is deterministic regardless of the order in which routes are received, which is not guaranteed in standard mode when routes from different neighbor ASes are interleaved.

## Required Interface

Your implementation must be in `/app/bgp_bestpath.py` and must provide:

```python
def select_best_path(scenario: dict) -> int:
    """Select the best BGP path from candidate routes.

    Args:
        scenario: dict with 'config' and 'routes' keys as described above.

    Returns:
        0-based index of the best path in the routes list,
        or -1 if no valid paths exist.
    """
```
