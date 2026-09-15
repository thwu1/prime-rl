// SPDX-License-Identifier: Apache-2.0
// Copyright Authors of Cilium
//
// Excerpted from github.com/cilium/cilium/pkg/policy/api
// These types define the CiliumNetworkPolicy rule specification.

package api

import "encoding/json"

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
	EndpointSelector EndpointSelector `json:"endpointSelector,omitzero"`

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
	EnableDefaultDeny DefaultDenyConfig `json:"enableDefaultDeny,omitzero"`

	// Description is a free form string, it can be used by the creator of
	// the rule to store human readable explanation of the purpose of this
	// rule. Rules cannot be identified by comment.
	Description string `json:"description,omitempty"`
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

// IngressRule contains all rule types which can be applied at ingress,
// i.e. to incoming traffic of an endpoint matching the endpointSelector
// of the parent rule.
type IngressRule struct {
	IngressCommonRule `json:",inline"`

	// ToPorts is a list of destination ports and protocols to which
	// incoming traffic may connect. If omitted or empty, all ports are
	// allowed.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// IngressDenyRule is similar to IngressRule but for deny policies. Traffic
// matching an IngressDenyRule is unconditionally dropped.
type IngressDenyRule struct {
	IngressCommonRule `json:",inline"`

	// ToPorts is a list of destination ports and protocols which must
	// match for the deny rule to apply. A deny rule with only ToPorts
	// (no L3 selector) matches all sources.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// IngressCommonRule is a rule that can be applied at ingress.
type IngressCommonRule struct {
	// FromEndpoints is a list of endpoints identified by an
	// EndpointSelector which are allowed to communicate with the endpoint
	// subject to this rule. Any endpoint matching any one of the selectors
	// is granted access (OR semantics).
	FromEndpoints []EndpointSelector `json:"fromEndpoints,omitempty"`

	// FromCIDR is a list of IP blocks which the endpoint subject to the
	// rule is allowed to receive connections from.
	FromCIDR []string `json:"fromCIDR,omitempty"`

	// FromCIDRSet is a list of IP blocks which the endpoint subject to
	// the rule is allowed to receive connections from, with optional
	// exceptions. An IP matching the CIDR but also matching an exception
	// is excluded.
	FromCIDRSet []CIDRRule `json:"fromCIDRSet,omitempty"`
}

// EgressRule contains all rule types which can be applied at egress,
// i.e. to outgoing traffic of an endpoint matching the endpointSelector.
type EgressRule struct {
	EgressCommonRule `json:",inline"`

	// ToPorts is a list of destination ports and protocols to which
	// outgoing traffic may connect. If omitted or empty, all ports are
	// allowed.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// EgressDenyRule is similar to EgressRule but for deny policies. Traffic
// matching an EgressDenyRule is unconditionally dropped.
type EgressDenyRule struct {
	EgressCommonRule `json:",inline"`

	// ToPorts is a list of destination ports and protocols which must
	// match for the deny rule to apply. A deny rule with only ToPorts
	// (no L3 selector) matches all destinations.
	ToPorts []PortRule `json:"toPorts,omitempty"`
}

// EgressCommonRule is a rule that can be applied at egress.
type EgressCommonRule struct {
	// ToEndpoints is a list of endpoints identified by an
	// EndpointSelector to which the endpoint subject to the rule is
	// allowed to communicate. Any endpoint matching any one of the
	// selectors is permitted (OR semantics).
	ToEndpoints []EndpointSelector `json:"toEndpoints,omitempty"`

	// ToCIDR is a list of CIDRs to which the endpoint is allowed to
	// initiate connections.
	ToCIDR []string `json:"toCIDR,omitempty"`

	// ToCIDRSet is a list of CIDRs with exception lists. The endpoint
	// may connect to any IP in the CIDR unless it falls within an
	// exception sub-range.
	ToCIDRSet []CIDRRule `json:"toCIDRSet,omitempty"`
}

// CIDRRule is a rule to select peers by CIDR prefix with optional exceptions.
type CIDRRule struct {
	Cidr   string   `json:"cidr"`
	Except []string `json:"except,omitempty"`
}

// PortRule is a list of ports/protocols that apply to traffic.
type PortRule struct {
	// Ports is a list of L4 port/protocol pairs.
	Ports []PortProtocol `json:"ports,omitempty"`
}

// PortProtocol is a combination of port number and protocol.
type PortProtocol struct {
	// Port is the L4 port number (as a string).
	Port string `json:"port"`
	// Protocol is the L4 protocol (TCP, UDP, SCTP, ANY).
	Protocol string `json:"protocol,omitempty"`
}

// Placeholder for json import usage
var _ = json.Marshal
