// SPDX-License-Identifier: Apache-2.0
// Copyright Authors of Cilium
//
// Excerpted from github.com/cilium/cilium/pkg/policy/api
// EndpointSelector and label matching types.

package api

// EndpointSelector is a wrapper for k8s LabelSelector.
//
// An empty EndpointSelector (neither matchLabels nor matchExpressions set)
// selects ALL endpoints. This is used, for example, in cluster-wide policies
// that should apply to every workload.
//
// When used in a rule's endpointSelector field, it determines which
// endpoints the policy applies to.
//
// When used inside fromEndpoints or toEndpoints, it determines which
// peer endpoints match the rule. Within a list of selectors, any single
// selector matching is sufficient (OR across the list).
//
// matchLabels and matchExpressions within a single selector are ANDed:
// all conditions must hold simultaneously.
type EndpointSelector struct {
	// MatchLabels is a map of {key,value} pairs. All entries must match
	// the endpoint's labels simultaneously (AND).
	// An empty map matches all endpoints.
	MatchLabels map[string]string `json:"matchLabels,omitempty"`

	// MatchExpressions is a list of label selector requirements.
	// All requirements must be satisfied simultaneously (AND).
	MatchExpressions []LabelSelectorRequirement `json:"matchExpressions,omitempty"`
}

// LabelSelectorRequirement is a selector that contains values, a key, and
// an operator that relates the key and values.
type LabelSelectorRequirement struct {
	// Key is the label key that the selector applies to.
	Key string `json:"key"`

	// Operator represents a key's relationship to a set of values.
	// Valid operators are In, NotIn, Exists, and DoesNotExist.
	//
	// Matching semantics:
	//   In:            the label key MUST exist and its value MUST be in Values
	//   NotIn:         the label key MUST NOT exist, or its value MUST NOT be in Values
	//   Exists:        the label key MUST exist (value is irrelevant)
	//   DoesNotExist:  the label key MUST NOT exist
	Operator string `json:"operator"`

	// Values is an array of string values. If the operator is In or NotIn,
	// the values array must be non-empty. If the operator is Exists or
	// DoesNotExist, the values array must be empty.
	Values []string `json:"values,omitempty"`
}
