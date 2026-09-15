# BGP Best-Path Selection — Reference

## Overview

When a BGP router receives multiple paths to the same destination prefix, it selects a single best path using a multi-step deterministic algorithm defined in RFC 4271 (Section 9.1.2). This document provides a partial reference. For authoritative details on MED comparison rules, confederation handling, and deterministic-MED mode, consult RFC 4271, RFC 4456 (route reflection), and RFC 5065 (confederations).

## Data Sources

Route analysis requires integrating data from three sources:

### 1. SQLite Database (`/app/bgp_rib.db`)

The primary data store for routes and queries. Use `sqlite3` to explore.

**Key tables:**

- **prefixes**: destination networks
- **routes**: candidate BGP paths with scalar attributes and a binary `extended_attrs` column
- **as_path_segments**: AS-path segments per route (ordered by `seg_order`)
- **config_profiles**: profile `id` and `name` only — the actual boolean flags are stored in the JSON policy file
- **queries**: each query asks "which route is best for a given prefix under a given config profile?"
- **pcap_routes**: identifies routes whose path attributes (`origin`, `med`, AS-path) must be extracted from the packet capture file rather than the database

AS-path segments have a `seg_type` (`AS_SEQUENCE`, `AS_SET`, `AS_CONFED_SEQUENCE`, `AS_CONFED_SET`) and `asns` stored as comma-separated integers.

Routes with no rows in `as_path_segments` either have an empty AS-path (locally originated routes) or have their AS-path data in the packet capture (check `pcap_routes`).

Routes listed in `pcap_routes` have NULL values for `origin` and `med` in the database. These values — along with AS-path segments — must be extracted from the corresponding BGP UPDATE message in the capture file.

### 2. Packet Capture (`/app/bgp_capture.pcap`)

A PCAP file containing BGP UPDATE messages from external peers. Each UPDATE message advertises one or more prefixes with path attributes (ORIGIN, AS_PATH, MULTI_EXIT_DISC/MED, NEXT_HOP).

To correlate a captured UPDATE with a database route, match the packet's source IP address (`ip.src`) against the route's `neighbor_address` field and verify the announced NLRI prefix matches the route's associated prefix.

The PCAP may contain UPDATE messages for prefixes not referenced by any query — filter appropriately.

### 3. Policy Configuration (`/app/policies/selection.json`)

A JSON document containing BGP selection profile configurations. Each profile has a numeric `id` that matches the `config_id` referenced in the `queries` table. The boolean selection flags for each profile are nested within this document structure.

## Extended Attributes BLOB Format

The `extended_attrs` column in the `routes` table encodes optional path attributes in a compact binary format:

```
Offset  Size     Field
------  ------   ----------------------------------
0       1 byte   Flags byte
                   bit 0 (0x01): originator_id present
                   bit 1 (0x02): cluster_list present

If bit 0 set:
  1       4 bytes  Originator ID — four octets of an IPv4 address
                   in network order (e.g. 5.5.5.5 → 0x05 0x05 0x05 0x05)

If bit 1 set:
  next    1 byte   N — number of cluster IDs
  next    N×4      Cluster IDs — each four octets in network order
```

If flags == 0x00 (or the column is NULL), the route has no originator_id and an empty cluster_list.

## Algorithm Steps (Summary)

Filter out routes where `is_valid` is false. If none remain, the answer is -1 (no valid path).

Compare valid routes pairwise; the first step that differentiates two paths determines the winner.

### Step 1 — Weight (highest wins)
Prefer the path with the higher `weight`.

### Step 2 — LOCAL_PREF (highest wins)
Prefer higher `local_pref`. A NULL value defaults to 100.

### Step 3 — Locally Originated
Prefer a locally originated path over a learned one. Among two locally-originated paths, prefer `network`/`redistribute` over `aggregate`.

### Step 4 — AS-Path Length (shortest wins)
Skip entirely if `as_path_ignore` is set in the config.

Counting rules:
- `AS_SEQUENCE`: each ASN counts as 1
- `AS_SET`: the entire set counts as 1, regardless of member count
- `AS_CONFED_SEQUENCE` and `AS_CONFED_SET`: do **not** count toward length

### Step 5 — Origin (lowest wins)
`igp` (0) < `egp` (1) < `incomplete` (2).

### Step 6 — MED (lowest wins, conditional)
MED comparison is only performed under specific conditions related to the neighbor AS of each path. The neighbor AS is derived from the first AS number in the first `AS_SEQUENCE` segment of the AS-path (skipping leading confederation segments). When no `AS_SEQUENCE` segment exists, the neighbor AS is undefined.

Consult RFC 4271 Section 9.1.2.2 (clause e) for the standard comparison rule and the `always_compare_med`, `med_missing_as_worst`, and `med_confed` configuration modifiers.

A NULL `med` value should be treated as 0 by default.

### Step 7 — eBGP over iBGP
Prefer true eBGP paths (`path_source` = `ebgp`). Confederation paths (`confed_ebgp`, `confed_ibgp`) are treated as internal for this comparison — they do not receive eBGP preference.

### Step 8 — IGP Metric (lowest wins)
Prefer the path with the lower `igp_metric` to the BGP next-hop.

### Step 9 — Multipath
Does not affect best-path selection. Skip.

### Steps 10–13 — Tiebreakers
These final steps resolve remaining ties using path age, router identity, route-reflector cluster depth, and peer address. The `compare_routerid` flag and the `originator_id` attribute (from route reflection, RFC 4456) affect the behavior of these steps. Consult RFC 4271 Section 9.1.2.2 for the exact ordering.

## Deterministic-MED Mode

When `deterministic_med` is set, the comparison order changes: paths are grouped by neighbor AS, the best is selected within each group, then group winners are compared. This produces results that are independent of route arrival order. The standard pairwise algorithm is used both within groups and between group winners. See vendor documentation for implementation details.

## Required Output

### Module Interface

Your `/app/bgp_analyzer.py` must expose:

```python
def select_best_path(routes: list[dict], config: dict) -> int:
    """Select the best BGP path from candidate routes.

    Args:
        routes: list of route dicts with keys:
            weight, local_pref, locally_originated, local_origin_type,
            as_path (list of {"type": str, "asns": [int]}),
            origin, med, path_source, igp_metric, router_id,
            originator_id (str or None), cluster_list (list of str),
            neighbor_address, is_valid (bool), arrival_order
        config: dict with boolean keys:
            always_compare_med, deterministic_med, as_path_ignore,
            compare_routerid, med_missing_as_worst, med_confed

    Returns:
        0-based index of the best path, or -1 if no valid paths.
    """
```

### Results File

Write `/app/results.json` mapping each query ID to the winning route ID:

```json
{"1": <route_id>, "2": <route_id>, ...}
```
