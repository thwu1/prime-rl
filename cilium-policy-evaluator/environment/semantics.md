# Cilium Network Policy Evaluation Semantics

This document describes the exact rules for evaluating CiliumNetworkPolicy resources
against traffic flow queries. Your implementation must follow these semantics precisely.

## Policy Structure

A CiliumNetworkPolicy has this structure:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: <policy-name>
spec:
  endpointSelector:       # Which endpoints this policy applies to
    matchLabels: {}        # All labels must match (AND)
    matchExpressions: []   # All expressions must match (AND)
  ingress: []              # Allow rules for incoming traffic
  ingressDeny: []          # Deny rules for incoming traffic
  egress: []               # Allow rules for outgoing traffic
  egressDeny: []           # Deny rules for outgoing traffic
  enableDefaultDeny:       # Override default-deny behavior
    ingress: <bool>
    egress: <bool>
```

## Label Selector Matching

### matchLabels
All key-value pairs must be present in the endpoint's labels. An empty `matchLabels: {}`
matches all endpoints.

### matchExpressions
Each expression has `key`, `operator`, and optionally `values`. ALL expressions must
match (AND logic). Operators:
- `In`: label exists and value is in the values list
- `NotIn`: label doesn't exist OR value is not in the values list
- `Exists`: label key is present (any value)
- `DoesNotExist`: label key is NOT present

### Empty selector
An empty selector `{}` (no matchLabels, no matchExpressions) matches ALL endpoints.

## Bilateral Evaluation

Traffic from endpoint A to endpoint B must pass BOTH:
1. Source (A) egress policy evaluation
2. Destination (B) ingress policy evaluation

If either side denies the traffic, the overall verdict is DENIED.

## Default-Deny Behavior

When a policy selects an endpoint, it may trigger default-deny for that endpoint:

1. If `enableDefaultDeny.ingress` is explicitly set to `true`: this policy requests
   ingress default-deny for the selected endpoints.
2. If `enableDefaultDeny.ingress` is explicitly set to `false`: this policy does NOT
   request ingress default-deny.
3. If `enableDefaultDeny.ingress` is NOT specified: default-deny for ingress is
   automatically `true` if the policy has any `ingress` or `ingressDeny` rules,
   and `false` otherwise.
4. Same logic applies for egress direction with `egress`/`egressDeny` rules.

**Critical rule**: If ANY policy that selects an endpoint requests default-deny for a
direction, then default-deny is ON for that endpoint in that direction. It only takes
one policy to enable it.

When default-deny is ON for a direction:
- All traffic in that direction is denied UNLESS explicitly allowed by an allow rule
- This is the "whitelist" model

When default-deny is OFF for a direction:
- All traffic in that direction is allowed by default
- Only explicit deny rules can block traffic

## Deny vs Allow Precedence

Deny rules (ingressDeny, egressDeny) ALWAYS take precedence over allow rules.
If a deny rule matches, the traffic is denied regardless of any allow rules.

## Evaluation Order

For each direction (egress at source, ingress at destination):
1. Collect all policies that select the endpoint
2. Compute whether default-deny is enabled (see above)
3. Check all deny rules across all matching policies — if ANY deny matches, verdict is DENIED
4. If default-deny is ON, check all allow rules across all matching policies —
   if ANY allow matches, verdict is ALLOWED; otherwise DENIED
5. If default-deny is OFF, verdict is ALLOWED (unless a deny rule matched in step 3)

## Rule Matching

### Ingress Allow Rule
```yaml
ingress:
  - fromEndpoints:         # L3: source must match at least one selector
      - matchLabels: {}
    fromCIDR: []           # L3: source IP in CIDR
    fromCIDRSet: []        # L3: source IP in CIDR with exceptions
    toPorts:               # L4: destination port restriction
      - ports:
          - port: "8080"
            protocol: TCP
```

- L3 match: At least one of fromEndpoints/fromCIDR/fromCIDRSet must match the source.
  Within fromEndpoints, any one selector matching is sufficient (OR).
- L4 match: If toPorts is present, the destination port/protocol must match.
  If toPorts is absent, all ports are allowed.
- Both L3 AND L4 must match for the rule to match.

### Egress Allow Rule
```yaml
egress:
  - toEndpoints:           # L3: destination must match at least one selector
      - matchLabels: {}
    toCIDR: []             # L3: destination IP in CIDR
    toCIDRSet:             # L3: destination IP in CIDR with exceptions
      - cidr: "10.0.0.0/8"
        except:
          - "10.0.5.0/24"
    toPorts:               # L4: destination port restriction
      - ports:
          - port: "443"
            protocol: TCP
```

- Same matching logic as ingress but with toEndpoints/toCIDR/toCIDRSet for the destination.

### Deny Rules
ingressDeny and egressDeny follow the same matching structure as their allow counterparts.
Special case: a deny rule with only toPorts (no L3 selector) matches ALL sources/destinations.

### CIDRSet with Exceptions
A CIDRSet entry matches if the IP is within the `cidr` range AND NOT within any `except` range.

### Multiple Rules in a Policy
Multiple rules within a single ingress/egress list are evaluated with OR logic —
if ANY rule matches, the allow/deny applies.

### Multiple Policies on an Endpoint
Allow rules from different policies are UNIONED — if any policy allows, it counts.
Deny rules from different policies are also UNIONED — if any policy denies, it counts.
Deny always wins over allow.
