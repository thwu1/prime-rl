# Cilium Policy Enforcement Reference

Adapted from Cilium documentation (cilium.io).

## Policy Enforcement Model

Cilium implements identity-based network security. Each managed endpoint is
assigned a security identity derived from its Kubernetes labels. Network
policies reference these identities to express access control rules.

### Policy Modes

An endpoint may be in one of two enforcement states for each traffic direction:

- **Default-allow**: All traffic is permitted unless explicitly denied. Active
  when no applicable policy governs that direction for the endpoint.
- **Default-deny**: All traffic is dropped unless explicitly allowed. Activated
  when policy begins governing traffic for that direction.

### Policy Selection and Scope

A `CiliumNetworkPolicy` resource targets endpoints using the `endpointSelector`
field. Only endpoints whose labels satisfy the selector are subject to that
policy's rules. Traffic involving IPs that do not correspond to any managed
endpoint is not subject to endpoint-based policy enforcement at that side.

### Directionality

Cilium enforces network policies at both communication endpoints. The egress
rules at a traffic source and the ingress rules at a traffic destination
independently contribute to the disposition of each connection. An endpoint
that has no selecting policy for a given direction is unconstrained in that
direction.

## Rule Structure

### Allow and Deny Lists

A policy may contain:
- `ingress` / `egress`: Lists of allow rules
- `ingressDeny` / `egressDeny`: Lists of deny rules

### Rule Independence

Each item in an `ingress` or `egress` array represents an independent rule.
A connection matching any single allow rule is considered allowed by that
policy (subject to deny rules and other constraints).

### L3/L4 Composition

Within a single rule:
- L3 identity selectors (`fromEndpoints`/`toEndpoints`, `fromCIDR`/`toCIDR`,
  `fromCIDRSet`/`toCIDRSet`, `fromEntities`/`toEntities`) are alternatives.
  A connection matches the L3 portion if it matches any one of these selectors.
- L4 port restrictions (`toPorts`) are additional constraints. When present,
  the connection must match both the L3 selector and the L4 port restriction.
- When no L3 selector is specified in a rule, all sources/destinations match.
- When no `toPorts` is specified, all port/protocol combinations match.

## Entity Definitions

Cilium defines the following identity entities for use in `fromEntities`/`toEntities`:

| Entity | Description |
|--------|-------------|
| `world` | IPs outside the cluster address space |
| `cluster` | IPs within the cluster address space |
| `host` | The local node's IP |
| `remote-node` | Other cluster node IPs (excluding local host) |
| `all` | Any IP |

Entity resolution depends on the cluster's network configuration (cluster CIDR,
node IP assignments). See `/app/entities.json` for this cluster's definitions.

## Default Deny Activation

The `enableDefaultDeny` field in a policy's spec controls whether that policy
causes its selected endpoints to enter default-deny mode for each direction.

See the Go type documentation in `policy_types.go` for the exact semantics
of this field, including the default behavior when it is unspecified.
