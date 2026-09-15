// SPDX-License-Identifier: Apache-2.0
// Copyright Authors of Cilium
//
// Reference types for CiliumNetworkPolicy evaluation.
// Adapted from github.com/cilium/cilium/pkg/policy/api

package api

// Rule is a policy rule which must be applied to all endpoints which match the
// labels contained in the endpointSelector.
//
// Each rule is split into an ingress section which contains all rules
// applicable at ingress, and an egress section applicable at egress. For rule
// types such as L4Rule and CIDR which can be applied at both ingress and
// egress, both ingress and egress side have to either specifically allow the
// connection or one side has to be omitted.
//
// Either ingress, egress, or both can be provided. If both ingress and egress
// are omitted, the rule has no effect.
type Rule struct {
	// EndpointSelector selects all endpoints which should be subject to
	// this rule.
	EndpointSelector EndpointSelector `json:"endpointSelector,omitempty"`

	// Ingress is a list of IngressRule which are enforced at ingress.
	// If omitted or empty, this rule does not apply at ingress.
	Ingress []IngressRule `json:"ingress,omitempty"`

	// IngressDeny is a list of IngressDenyRule which are enforced at ingress.
	// Any rule inserted here will be denied regardless of the allowed ingress
	// rules in the 'ingress' field.
	// If omitted or empty, this rule does not apply at ingress.
	IngressDeny []IngressDenyRule `json:"ingressDeny,omitempty"`

	// Egress is a list of EgressRule which are enforced at egress.
	// If omitted or empty, this rule does not apply at egress.
	Egress []EgressRule `json:"egress,omitempty"`

	// EgressDeny is a list of EgressDenyRule which are enforced at egress.
	// Any rule inserted here will be denied regardless of the allowed egress
	// rules in the 'egress' field.
	// If omitted or empty, this rule does not apply at egress.
	EgressDeny []EgressDenyRule `json:"egressDeny,omitempty"`

	// EnableDefaultDeny determines whether this policy configures the
	// subject endpoint(s) to have a default deny mode. If enabled,
	// this causes all traffic not explicitly allowed by a network policy
	// to be dropped.
	//
	// If not specified, the default is true for each traffic direction
	// that has rules, and false otherwise. For example, if a policy
	// only has Ingress or IngressDeny rules, then the default for
	// ingress is true and egress is false.
	//
	// If multiple policies apply to an endpoint, that endpoint's default deny
	// will be enabled if any policy requests it.
	//
	// This is useful for creating broad-based network policies that will not
	// cause endpoints to enter default-deny mode.
	EnableDefaultDeny DefaultDenyConfig `json:"enableDefaultDeny,omitempty"`
}

// DefaultDenyConfig expresses a policy's desired default mode for the subject
// endpoints.
type DefaultDenyConfig struct {
	// Whether or not the endpoint should have a default-deny rule applied
	// to ingress traffic.
	Ingress *bool `json:"ingress,omitempty"`

	// Whether or not the endpoint should have a default-deny rule applied
	// to egress traffic.
	Egress *bool `json:"egress,omitempty"`
}

// EndpointSelector is a wrapper for k8s LabelSelector.
type EndpointSelector struct {
	// matchLabels is a map of {key,value} pairs. A single {key,value} in the
	// matchLabels map is equivalent to an element of matchExpressions, whose
	// key field is "key", the operator is "In", and the values array contains
	// only "value". All specified pairs must match for the selector to match
	// an endpoint's labels.
	MatchLabels map[string]string `json:"matchLabels,omitempty"`

	// matchExpressions is a list of label selector requirements.
	// The requirements are ANDed.
	MatchExpressions []LabelSelectorRequirement `json:"matchExpressions,omitempty"`
}

// LabelSelectorRequirement is a selector that contains values, a key, and an
// operator that relates the key and values.
type LabelSelectorRequirement struct {
	Key      string   `json:"key"`
	Operator string   `json:"operator"` // In, NotIn, Exists, DoesNotExist
	Values   []string `json:"values,omitempty"`
}

// IngressRule contains all rule types which can be applied at ingress.
// Any rule in the list is considered an independent rule and rules are ORed.
// The L3 selectors within a single rule are also ORed, while L3 and L4 are ANDed.
type IngressRule struct {
	// FromEndpoints limits the peers that incoming traffic can originate from.
	// Absent or empty allows from all endpoints that have labels matching
	// the endpoint selector.
	FromEndpoints []EndpointSelector `json:"fromEndpoints,omitempty"`

	// FromCIDR limits incoming traffic from a list of CIDRs.
	FromCIDR []string `json:"fromCIDR,omitempty"`

	// FromCIDRSet limits incoming traffic from a list of CIDRs with exceptions.
	FromCIDRSet []CIDRRule `json:"fromCIDRSet,omitempty"`

	// FromEntities limits incoming traffic from predefined entity groups.
	FromEntities []string `json:"fromEntities,omitempty"`

	// ToPorts restricts the L4 ports to which incoming traffic is allowed.
	// If omitted or empty, all ports are allowed.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// IngressDenyRule contains all rule types which can be denied at ingress.
// Deny rules take precedence over allow rules.
type IngressDenyRule struct {
	FromEndpoints []EndpointSelector `json:"fromEndpoints,omitempty"`
	FromCIDR      []string           `json:"fromCIDR,omitempty"`
	FromCIDRSet   []CIDRRule         `json:"fromCIDRSet,omitempty"`
	FromEntities  []string           `json:"fromEntities,omitempty"`
	ToPorts       []PortRule         `json:"toPorts,omitempty"`
}

// EgressRule contains all rule types which can be applied at egress.
type EgressRule struct {
	// ToEndpoints limits the peers that outgoing traffic can be sent to.
	ToEndpoints []EndpointSelector `json:"toEndpoints,omitempty"`

	// ToCIDR limits outgoing traffic to a list of CIDRs.
	ToCIDR []string `json:"toCIDR,omitempty"`

	// ToCIDRSet limits outgoing traffic to a list of CIDRs with exceptions.
	ToCIDRSet []CIDRRule `json:"toCIDRSet,omitempty"`

	// ToEntities limits outgoing traffic to predefined entity groups.
	ToEntities []string `json:"toEntities,omitempty"`

	// ToPorts restricts the L4 ports to which outgoing traffic is allowed.
	// If omitted or empty, all ports are allowed.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// EgressDenyRule contains all rule types which can be denied at egress.
// Deny rules take precedence over allow rules.
type EgressDenyRule struct {
	ToEndpoints []EndpointSelector `json:"toEndpoints,omitempty"`
	ToCIDR      []string           `json:"toCIDR,omitempty"`
	ToCIDRSet   []CIDRRule         `json:"toCIDRSet,omitempty"`
	ToEntities  []string           `json:"toEntities,omitempty"`
	ToPorts     []PortRule         `json:"toPorts,omitempty"`
}

// CIDRRule is a rule to select peers based on CIDR with optional exceptions.
type CIDRRule struct {
	// CIDR is a network prefix in standard CIDR notation (e.g., "10.0.0.0/8").
	Cidr string `json:"cidr"`

	// ExceptCIDRs is a list of CIDRs to exclude from the main CIDR.
	// Traffic matching these exception CIDRs is NOT matched by this rule.
	ExceptCIDRs []string `json:"except,omitempty"`
}

// PortRule is a list of port/protocol pairs with optional layer 7 rules.
type PortRule struct {
	// Ports is a list of L4 port/protocol pairs.
	Ports []PortProtocol `json:"ports,omitempty"`
}

// PortProtocol specifies an L4 port with an optional protocol.
type PortProtocol struct {
	// Port is the L4 port number (as a string).
	Port string `json:"port"`

	// Protocol is the L4 protocol. Defaults to "TCP" if not specified.
	Protocol string `json:"protocol,omitempty"`
}
