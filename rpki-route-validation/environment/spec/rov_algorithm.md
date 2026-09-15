# Route Origin Validation (ROV) Algorithm

Based on RFC 6811 — BGP Prefix Origin Validation.

## Input

- **VRP Set**: A set of Validated ROA Payloads (VRPs), each containing:
  - `prefix`: An IP prefix (IPv4 or IPv6) in CIDR notation
  - `max_length`: Maximum prefix length authorized for this origin
  - `origin_as`: The authorized origin AS number

- **Route**: A BGP route announcement containing:
  - `prefix`: The announced IP prefix in CIDR notation
  - `origin_as`: The AS originating the route

## Definitions

A VRP **covers** a route if the VRP's prefix is an equal or less-specific prefix of the route's prefix. Formally: the route's prefix is a subnet of (or equal to) the VRP's prefix. Both must be of the same address family (IPv4 or IPv6).

## Validation Procedure

1. Collect the set of all VRPs that cover the route's prefix. Call this the **covering set**.

2. Evaluate the covering set:

   a. If ANY VRP in the covering set satisfies BOTH:
      - The route's prefix length is less than or equal to the VRP's `max_length`
      - The route's `origin_as` equals the VRP's `origin_as`
      
      Then the route's ROV result is **Valid**.

   b. If the covering set is non-empty but no VRP satisfies both conditions in (a), the route's ROV result is **Invalid**.

   c. If the covering set is empty (no VRP covers the route's prefix), the route's ROV result is **NotFound**.

## Examples

Given VRP: `{prefix: "10.0.0.0/16", max_length: 24, origin_as: 65001}`

| Route Prefix   | Route Origin | Covered? | PfxLen <= MaxLen? | Origin Match? | Result   |
|---------------|-------------|----------|-------------------|---------------|----------|
| 10.0.0.0/16   | 65001       | Yes      | 16 <= 24 Yes      | Yes           | Valid    |
| 10.0.1.0/24   | 65001       | Yes      | 24 <= 24 Yes      | Yes           | Valid    |
| 10.0.1.0/25   | 65001       | Yes      | 25 > 24 No        | Yes           | Invalid  |
| 10.0.0.0/16   | 65099       | Yes      | 16 <= 24 Yes      | No            | Invalid  |
| 172.16.0.0/16 | 65001       | No       | N/A               | N/A           | NotFound |

## Multiple VRP Handling

When multiple VRPs cover a route's prefix, the route is **Valid** if ANY covering VRP produces a Valid match. The route is **Invalid** only if the covering set is non-empty AND no VRP produces a Valid match.
