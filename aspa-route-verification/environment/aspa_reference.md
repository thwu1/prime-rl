# ASPA Verification Reference

## Overview

Autonomous System Provider Authorization (ASPA) is an RPKI-based mechanism for detecting route leaks in BGP. Each ASPA object binds a customer AS to its set of authorized upstream transit providers. Verifiers check AS_PATH hops against the ASPA database to determine whether a path is consistent with the valley-free routing model.

Two verification procedures exist: **upstream** (for routes received from a provider or peer) and **downstream** (for routes received from a customer).

## Hop Check

The fundamental operation evaluates whether a candidate AS is an authorized provider of a customer AS:

- If the customer has published no ASPA object: **no_attestation**
- If the candidate appears in the customer's authorized provider set: **provider**
- Otherwise: **not_provider**

## Path Preprocessing

Before verification, consecutive duplicate ASNs must be collapsed (AS_PATH prepending removal). For example, `[A, A, B, B, B, C]` becomes `[A, B, C]`.

## AS_PATH Convention

The AS_PATH is ordered `[origin, ..., neighbor]` where the origin AS is at index 0 and the neighbor (the AS that forwarded the route to the verifier) is at the last index. The verifying AS itself does not appear in the path.

## Upstream Verification

Checks that every hop in the path is a valid customer-to-provider transition:

- Paths with AS_SET segments are **Unverifiable**
- Single-AS or empty paths are **Valid**
- If any hop check yields **not_provider**: the path is **Invalid** (route leak)
- If every hop check yields **provider**: the path is **Valid**
- Otherwise (mix of provider and no_attestation): **Unknown**

## Downstream Verification

Checks that the path conforms to the valley-free model: an ascending segment of customer-to-provider hops, optionally meeting a descending segment of provider-to-customer hops.

- Paths with AS_SET are **Unverifiable**
- Paths of 2 or fewer ASes are **Valid**
- For longer paths, compute hop checks in both directions for each consecutive pair:
  - **Forward** (uphill): is the next AS a provider of the current AS?
  - **Reverse** (downhill): is the current AS a provider of the next AS?
- Determine the longest ascending ramp from the origin (consecutive forward "provider" results from the left)
- Determine the longest descending ramp toward the neighbor (consecutive reverse "provider" results from the right)
- If the ascending and descending ramps together span all hops: **Valid**
- In any gap between the ramps, if both forward and reverse checks yield **not_provider** for the same hop: **Invalid**
- Otherwise: **Unknown**

## Verification Direction

The choice of algorithm depends on the relationship between the verifying AS and the neighbor that sent the route:

- Route received from a **transit provider** of the verifier -> upstream verification
- Route received from a **settlement-free peer** -> upstream verification
- Route received from a **customer** of the verifier -> downstream verification
