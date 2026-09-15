# ASPA Path Verification Algorithm

Based on draft-ietf-sidrops-aspa-verification — Verification of AS_PATH Using ASPA Objects.

## Input

- **ASPA Set**: A set of ASPA authorization objects, each containing:
  - `customer_as`: The AS number of the customer
  - `provider_set`: List of AS numbers authorized as providers of this customer

- **Route**: A BGP route with:
  - `as_path`: Ordered list of AS numbers `[a_0, a_1, ..., a_{N-1}]` where `a_0` is the **neighbor** (most recently prepended AS) and `a_{N-1}` is the **origin** AS
  - `relationship`: The relationship of the validating router to the neighbor: `"customer"`, `"provider"`, or `"peer"`

## Hop Check Function

For a given pair of AS numbers:

```
hop_check(customer_asn, candidate_provider_asn):
    aspa = lookup ASPA record for customer_asn
    if no ASPA record exists for customer_asn:
        return NO_ATTESTATION
    if candidate_provider_asn is in aspa.provider_set:
        return PROVIDER
    return NOT_PROVIDER
```

## Path Normalization

Before verification, remove consecutive duplicate AS numbers from the AS path (AS path prepending normalization). For example: `[65005, 65002, 65002, 65002]` becomes `[65005, 65002]`.

All subsequent steps operate on the **deduplicated** path `p[0..M-1]` where `p[0]` is the neighbor and `p[M-1]` is the origin.

## Upstream Path Verification

Applied when `relationship == "customer"` (route received from a customer AS).

This verifies that the AS path represents a valley-free route. A valley-free path goes "up" through customer-to-provider hops from the origin to a peak, then "down" through provider-to-customer hops to the neighbor.

### Algorithm

```
function upstream_verify(p[0..M-1]):
    if M <= 1:
        return Valid

    has_unknown = false

    # Compute upward ramp from origin (right to left)
    u = M - 1
    for i = M-1 downto 1:
        result = hop_check(p[i], p[i-1])
        if result == PROVIDER:
            u = i - 1
        else if result == NO_ATTESTATION:
            u = i - 1
            has_unknown = true
        else:  # NOT_PROVIDER
            break

    # Compute downward ramp from neighbor (left to right)
    d = 0
    for i = 0 to M-2:
        result = hop_check(p[i], p[i+1])
        if result == PROVIDER:
            d = i + 1
        else if result == NO_ATTESTATION:
            d = i + 1
            has_unknown = true
        else:  # NOT_PROVIDER
            break

    # Check if ramps meet or overlap
    if d >= u:
        if has_unknown:
            return Unknown
        return Valid
    return Invalid
```

### Intuition

The **upward ramp** extends from the origin leftward as long as each AS considers the next AS (toward the neighbor) to be its provider. This represents the customer-to-provider ascending portion of the path.

The **downward ramp** extends from the neighbor rightward as long as each AS considers the next AS (toward the origin) to be its provider. Since `hop_check(p[i], p[i+1])` asks whether `p[i]` is a customer of `p[i+1]`, a PROVIDER result means `p[i+1]` is above `p[i]` — confirming the route descended through this hop.

If the two ramps meet or overlap (`d >= u`), the path is valley-free. The meeting point is the "peak" of the path (typically a Tier-1 AS or a peer-to-peer interconnection).

## Downstream Path Verification

Applied when `relationship == "provider"` or `relationship == "peer"` (route received from a provider or lateral peer).

For routes received from above, the entire path from origin to the neighbor should represent a single ascending customer-to-provider chain.

### Algorithm

```
function downstream_verify(p[0..M-1]):
    if M <= 1:
        return Valid

    has_unknown = false

    # Check ALL hops from origin toward neighbor
    for i = M-1 downto 1:
        result = hop_check(p[i], p[i-1])
        if result == NOT_PROVIDER:
            return Invalid
        else if result == NO_ATTESTATION:
            has_unknown = true

    if has_unknown:
        return Unknown
    return Valid
```

## Selecting the Verification Procedure

- If `relationship == "customer"`: use **Upstream Path Verification**
- If `relationship == "provider"` or `relationship == "peer"`: use **Downstream Path Verification**

## Result Values

- **Valid**: The path structure is consistent with all available ASPA data
- **Invalid**: The path contains at least one hop that explicitly violates an ASPA record
- **Unknown**: No explicit violations found, but some AS numbers lack ASPA records, preventing full verification

## Example

Given ASPAs:
- AS65001 providers: [65002]
- AS65002 providers: [65005]
- AS65005 providers: [65008]
- AS65008 providers: [] (Tier-1)

Path: [65008, 65005, 65002, 65001], received from provider (downstream verification):
- hop_check(65001, 65002): 65002 in providers(65001)=[65002] -> PROVIDER
- hop_check(65002, 65005): 65005 in providers(65002)=[65005] -> PROVIDER
- hop_check(65005, 65008): 65008 in providers(65005)=[65008] -> PROVIDER
- Result: **Valid** (clean customer-to-provider chain)
