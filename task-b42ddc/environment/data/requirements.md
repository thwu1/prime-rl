# Route Filtering Policy Requirements

## Objective
Design a composite filtering policy that combines ROV (Route Origin Validation) and ASPA
(AS_PATH verification) results to classify each BGP route as ACCEPT, REJECT, or REVIEW.

## Classification Rules

### REJECT (must reject):
1. ROV result is "Invalid" (origin AS not authorized for the prefix by any trusted ROA)
2. ASPA result is "Invalid" (path violates valley-free model based on trusted ASPA data)
3. Both ROV and ASPA indicate problems (any non-Valid result in both)

### ACCEPT (safe to accept):
1. ROV result is "Valid" AND ASPA result is "Valid"
2. ROV result is "Valid" AND ASPA result is "Valid" but MaxLength creates sub-prefix vulnerability — accept but flag as "Unsafe" in risk assessment

### REVIEW (manual review needed):
1. ROV result is "NotFound" (no applicable trusted ROA) AND ASPA result is "Valid"
2. ROV result is "Valid" AND ASPA result is "Unknown" (some hops unattested)
3. ROV result is "NotFound" AND ASPA result is "Unknown"

## Risk Scoring (1-10)
Assign a risk score based on:
- ROV Invalid: +5
- ASPA Invalid: +4
- ROV NotFound: +2
- ASPA Unknown: +1
- MaxLength vulnerability exposure: +2
- Revoked certificate involvement: +3 (an untrusted ROA covering the route's prefix was signed by a revoked entity)
- Base score: 1

Cap at 10. Routes with risk >= 7 should always be REJECT regardless of other rules.

## ROV Classification Rules
- "Valid": origin_as matches a trusted ROA's ASN, and the announced prefix is covered by the ROA's prefix/maxLength
- "Invalid": a trusted ROA exists covering the prefix but with a different ASN
- "NotFound": no trusted ROA covers the announced prefix
- "Unsafe": Valid match exists but the ROA's maxLength exceeds the ROA prefix length by 4+ bits (significant sub-prefix hijack surface)

A ROA "covers" a route's prefix when the ROA's prefix is a supernet of (or equal to) the route's prefix, and the route's prefix length does not exceed the ROA's maxLength.

## ASPA Classification

Only use ASPA objects with valid (non-revoked, non-tampered) signatures.

### Hop Check
For an ordered pair of ASNs (customer, candidate):
- If customer has a trusted ASPA object and candidate is in its `authorized_providers` list: result = **ProviderPlus**
- If customer has a trusted ASPA object and candidate is NOT in its `authorized_providers` list: result = **NotProviderPlus**
- If customer has no trusted ASPA object: result = **NoAttestation**

### Path Preprocessing
Before verification, the BGP AS_PATH (which is neighbor-first, origin-last) must be:
1. Reversed so that index 0 is the origin AS and the last index is the neighbor
2. Consecutive duplicate ASNs collapsed (AS_PATH prepending removed)

### Upstream Verification (for routes with relationship = "customer")
For the preprocessed path of length N:
- If N <= 1, return Valid
- For each pair (path[i], path[i+1]) where i = 0..N-2:
  - If hop_check = NotProviderPlus: return **Invalid**
  - If hop_check = NoAttestation: mark unknown
- If any hop was NoAttestation (and none NotProviderPlus): return **Unknown**
- Otherwise: return **Valid**

### Downstream Verification (for routes with relationship = "provider" or "peer")
For the preprocessed path of length N:
- If N <= 2, return Valid

Forward scan (up-ramp extent):
  u = 0; for i = 0 to N-2: if hop_check(path[i], path[i+1]) == NotProviderPlus then break; else u = i+1

Backward scan (down-ramp extent):
  d = N-1; for j = N-1 down to 1: if hop_check(path[j], path[j-1]) == NotProviderPlus then break; else d = j-1

Valley-free check: if u+1 < d, the up-ramp and down-ramp do not cover the full path — return **Invalid**

Attestation completeness:
  For i = 0 to u-1: if hop_check(path[i], path[i+1]) == NoAttestation → return **Unknown**
  For j = N-1 down to d+1: if hop_check(path[j], path[j-1]) == NoAttestation → return **Unknown**

Return **Valid**

## Trust Determination
- Verify each RPKI object's signature using its signing entity's public key
- Objects signed by revoked entities are untrusted regardless of signature validity
- Objects with invalid signatures (tampered data) are untrusted
