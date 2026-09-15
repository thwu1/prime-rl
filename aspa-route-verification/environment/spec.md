# ASPA Path Verification — Algorithm Specification

## 1. Overview

Autonomous System Provider Authorization (ASPA) is an RPKI-based mechanism for
detecting route leaks in BGP. An ASPA object binds a *customer* AS to the set
of its authorized *upstream transit providers*. By checking each hop in an
AS\_PATH against the ASPA database, a verifier can determine whether the path
is consistent with the expected valley-free routing model.

This specification defines two verification algorithms: **upstream** and
**downstream**. Both operate on a collapsed (prepend-free) AS\_PATH and an ASPA
database.

## 2. Data Model

### 2.1 ASPA Database

The ASPA database is a mapping:

    ASPA_DB : ASN → Set[ASN]

If `ASPA_DB[X]` exists, it is the set of ASNs authorized as upstream providers
of AS X.  If `X ∉ ASPA_DB`, then AS X has not published an ASPA object.

Note: An AS with an empty provider set (`ASPA_DB[X] = {}`) is valid — it
indicates a Tier-1 AS that has no transit providers.

### 2.2 AS\_PATH Representation

An AS\_PATH is an ordered sequence `[AS_0, AS_1, ..., AS_{N-1}]` where:
- `AS_0` is the **origin** AS (the AS that originated the route)
- `AS_{N-1}` is the **neighbor** AS (the last AS before the verifier)

A route may additionally carry a flag `has_as_set` indicating that the
original AS\_PATH contained an AS\_SET segment.

## 3. Preprocessing: Collapse Prepends

Before verification, consecutive duplicate ASNs in the path MUST be collapsed
into a single occurrence:

    collapse([A, A, B, B, B, C]) = [A, B, C]

This handles AS\_PATH prepending, where an AS artificially lengthens a path by
repeating its own ASN.

## 4. Hop Check Function

The fundamental building block of both algorithms is the **hop check**, which
determines whether a candidate AS is an authorized provider of a given
customer AS:

    hop_check(ASPA_DB, customer_as, candidate_provider_as) → HopResult

    where HopResult ∈ { "provider", "not_provider", "no_attestation" }

**Rules:**

1. If `customer_as ∉ ASPA_DB`: return `"no_attestation"`
2. If `candidate_provider_as ∈ ASPA_DB[customer_as]`: return `"provider"`
3. Otherwise: return `"not_provider"`

## 5. Upstream Path Verification

Upstream verification checks whether every hop in the AS\_PATH represents a
valid customer-to-provider relationship. It is used when a route is received
from a provider or route server.

    upstream_verify(ASPA_DB, route) → VerifyResult

    where VerifyResult ∈ { "Valid", "Invalid", "Unknown", "Unverifiable" }

**Algorithm:**

1. If `route.has_as_set` is true: return `"Unverifiable"`
2. Let `P = collapse(route.as_path)`
3. Let `N = |P|`
4. If `N ≤ 1`: return `"Valid"`
5. For `i = 0` to `N − 2`:
   - Let `check[i] = hop_check(ASPA_DB, P[i], P[i+1])`
6. If any `check[i] = "not_provider"`: return `"Invalid"`
7. If all `check[i] = "provider"`: return `"Valid"`
8. Return `"Unknown"`

**Interpretation:**
- Step 6: If any hop is provably NOT a customer→provider relationship, the path
  contains a route leak.
- Step 7: If every hop is a confirmed customer→provider relationship, the path
  is fully validated.
- Step 8: Some hops lack ASPA data, so the path cannot be fully confirmed or
  denied.

## 6. Downstream Path Verification

Downstream verification checks whether the AS\_PATH is consistent with the
*valley-free* routing model. A valley-free path consists of:
- An ascending segment (zero or more customer→provider hops) from the origin
- Optionally, a single lateral peer link at the apex
- A descending segment (zero or more provider→customer hops) toward the neighbor

It is used when a route is received from a customer or lateral peer.

    downstream_verify(ASPA_DB, route) → VerifyResult

**Algorithm:**

1. If `route.has_as_set` is true: return `"Unverifiable"`
2. Let `P = collapse(route.as_path)`
3. Let `N = |P|`
4. If `N ≤ 1`: return `"Valid"`
5. If `N = 2`: return `"Valid"`
6. For `i = 0` to `N − 2`, compute two arrays:
   - `fwd[i] = hop_check(ASPA_DB, P[i], P[i+1])`
     *(checks if `P[i+1]` is an authorized provider of `P[i]` — uphill direction)*
   - `bwd[i] = hop_check(ASPA_DB, P[i+1], P[i])`
     *(checks if `P[i]` is an authorized provider of `P[i+1]` — downhill direction)*
7. Compute the **up-ramp length** `u`:
   - `u = 0`
   - While `u < N − 1` and `fwd[u] = "provider"`: increment `u`
8. Compute the **down-ramp length** `d`:
   - `d = 0`
   - While `d < N − 1` and `bwd[N − 2 − d] = "provider"`: increment `d`
9. If `u + d ≥ N − 1`: return `"Valid"`
   *(The ascending and descending ramps cover the entire path, possibly
   overlapping at the apex.)*
10. **Gap analysis** — for each index `i` from `u` to `N − 2 − d` (inclusive):
    - If `fwd[i] = "not_provider"` AND `bwd[i] = "not_provider"`:
      return `"Invalid"`
      *(This hop can be explained neither as uphill nor downhill — confirmed
      route leak.)*
11. Return `"Unknown"`

**Interpretation:**
- Steps 7–8: Find the longest provably-valid ascending segment from the left
  and descending segment from the right.
- Step 9: If these segments cover all hops, the path is valley-free.
- Step 10: In the uncovered "gap" between the ramps, each hop is checked in
  both directions. If neither direction can explain the hop, the path is
  provably invalid.
- Step 11: The gap contains hops that cannot be confirmed (due to missing ASPA
  data) but also cannot be proven invalid.

## 7. Output Format

For each route, produce a result object containing:
- `id`: the route identifier (string)
- `result`: one of `"Valid"`, `"Invalid"`, `"Unknown"`, `"Unverifiable"` (string)

Write the results as a JSON object:

```json
{
  "results": [
    {"id": "R01", "result": "Valid"},
    ...
  ]
}
```

The results MUST appear in the same order as the input routes.
