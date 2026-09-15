# ASPA Path Verification Algorithm Specification

This document specifies the Autonomous System Provider Authorization (ASPA) based
AS_PATH verification algorithms for BGP routes, derived from
draft-ietf-sidrops-aspa-verification. These algorithms detect route leaks and
unauthorized path manipulation by validating AS_PATH segments against registered
ASPA objects.

## Data Model

- **ASPA object**: For a customer AS `C`, `ASPA(C)` is the set of ASNs that `C`
  has authorized as its providers. If `C` has no registered ASPA object,
  `ASPA(C)` is undefined.

- **AS_PATH**: An ordered sequence of ASNs as received in a BGP UPDATE message.
  Standard BGP convention: the first element is the neighbor AS (nearest to the
  verifier) and the last element is the route origin.

- **Processing path**: Before verification, the AS_PATH must be:
  1. Reversed so that index 0 is the route origin and index N-1 is the neighbor
  2. Collapsed by removing consecutive duplicate ASNs (AS_PATH prepending)
  The result is called `path` with length `N`.

## Hop Check Function

The fundamental building block is a function that checks whether a customer AS
has authorized a candidate AS as one of its providers:

```
FUNCTION hop_check(customer_asn, candidate_asn) -> {ProviderPlus, NotProviderPlus, NoAttestation}:

    IF customer_asn has no registered ASPA object:
        RETURN NoAttestation

    IF candidate_asn IN ASPA(customer_asn):
        RETURN ProviderPlus

    RETURN NotProviderPlus
```

- `ProviderPlus`: The customer explicitly authorizes this provider
- `NotProviderPlus`: The customer has an ASPA but does NOT authorize this provider
- `NoAttestation`: The customer has no ASPA object registered

## Upstream Path Verification

Applied when a route is received from a **customer** (relationship = "customer").
The entire path is expected to be a chain of customer-to-provider hops from the
origin to the neighbor.

```
FUNCTION verify_upstream(path) -> {Valid, Invalid, Unknown}:
    N := length(path)
    IF N <= 1:
        RETURN Valid

    has_unknown := false
    FOR i := 0 TO N-2:
        h := hop_check(path[i], path[i+1])
        IF h = NotProviderPlus:
            RETURN Invalid
        IF h = NoAttestation:
            has_unknown := true

    IF has_unknown:
        RETURN Unknown
    RETURN Valid
```

## Downstream Path Verification

Applied when a route is received from a **provider** or **lateral peer**
(relationship = "provider" or "peer"). The path is expected to have a
valley-free shape: an ascending segment (customer-to-provider) from the origin,
an optional single peering hop at the apex, then a descending segment
(provider-to-customer) toward the neighbor.

The algorithm scans the path from both ends to identify the up-ramp and
down-ramp, then checks whether they meet.

```
FUNCTION verify_downstream(path) -> {Valid, Invalid, Unknown}:
    N := length(path)
    IF N <= 2:
        RETURN Valid

    // --- Forward scan: up-ramp from origin ---
    // Find the furthest index reachable via ProviderPlus or NoAttestation hops
    u := 0
    FOR i := 0 TO N-2:
        IF hop_check(path[i], path[i+1]) = NotProviderPlus:
            BREAK
        u := i + 1

    // --- Reverse scan: down-ramp from neighbor ---
    // At each position j, path[j] is the customer receiving from path[j-1].
    // Check if path[j] authorizes path[j-1] as its provider.
    d := N - 1
    FOR j := N-1 DOWNTO 1:
        IF hop_check(path[j], path[j-1]) = NotProviderPlus:
            BREAK
        d := j - 1

    // --- Valley-free shape check ---
    // The up-ramp covers indices 0..u, the down-ramp covers indices d..N-1.
    // A single-hop gap (u+1 = d) is permitted for a peering apex.
    IF u + 1 < d:
        RETURN Invalid

    // --- Attestation completeness check ---
    // Scan only within each ramp for NoAttestation hops.
    FOR i := 0 TO u-1:
        IF hop_check(path[i], path[i+1]) = NoAttestation:
            RETURN Unknown
    FOR j := N-1 DOWNTO d+1:
        IF hop_check(path[j], path[j-1]) = NoAttestation:
            RETURN Unknown

    RETURN Valid
```

### Downstream Algorithm Rationale

- The **forward scan** identifies how far from the origin the path can be
  explained as ascending customer-to-provider hops. The scan continues through
  `NoAttestation` hops (since the absence of an ASPA does not disprove a valid
  relationship) but stops at `NotProviderPlus` (an explicit ASPA that rejects
  the alleged provider).

- The **reverse scan** works symmetrically from the neighbor end. Each position
  `j` is treated as a potential customer that received the route from its
  provider at position `j-1`.

- If the up-ramp and down-ramp overlap (`u >= d`) or are separated by exactly
  one hop (`u + 1 = d`), the path has a valid valley-free topology. The single
  gap represents a lateral peering relationship at the apex.

- If there is a wider gap (`u + 1 < d`), the path cannot be explained by any
  valid valley-free topology and is `Invalid`.

- When the shape is valid, any `NoAttestation` hop within either ramp means the
  full path cannot be confirmed, yielding `Unknown`.

## Verification Dispatch

For each route:
1. Process the AS_PATH (reverse, then collapse prepends)
2. Select the algorithm based on the `relationship` field:
   - `"customer"` -> `verify_upstream(path)`
   - `"provider"` or `"peer"` -> `verify_downstream(path)`
3. Record the result: one of `"Valid"`, `"Invalid"`, or `"Unknown"`
