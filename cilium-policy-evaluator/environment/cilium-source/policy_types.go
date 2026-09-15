// SPDX-License-Identifier: Apache-2.0
// Copyright Authors of Cilium
//
// Excerpted from github.com/cilium/cilium/pkg/k8s/apis/cilium.io/v2
// Top-level CRD types for Cilium network policies.

package v2

import api "github.com/cilium/cilium/pkg/policy/api"

// CiliumNetworkPolicy is a Kubernetes third-party resource with an extended
// version of NetworkPolicy. It is namespace-scoped: the endpointSelector
// only matches endpoints within the same namespace as the policy.
//
// +genclient
// +k8s:deepcopy-gen:interfaces=k8s.io/apimachinery/pkg/runtime.Object
type CiliumNetworkPolicy struct {
	// Spec is the desired Cilium specific rule specification.
	Spec *api.Rule `json:"spec,omitempty"`

	// Specs is a list of desired Cilium specific rule specifications.
	Specs api.Rules `json:"specs,omitempty"`
}

// CiliumClusterwideNetworkPolicy is similar to CiliumNetworkPolicy but
// is cluster-scoped instead of namespace-scoped. The endpointSelector
// applies across all namespaces in the cluster. Rules from cluster-wide
// policies are merged with namespace-scoped policies during evaluation —
// both types contribute to the same endpoint's resolved policy using
// identical semantics.
//
// +genclient
// +genclient:nonNamespaced
// +k8s:deepcopy-gen:interfaces=k8s.io/apimachinery/pkg/runtime.Object
type CiliumClusterwideNetworkPolicy struct {
	// Spec is the desired Cilium specific rule specification.
	Spec *api.Rule `json:"spec,omitempty"`

	// Specs is a list of desired Cilium specific rule specifications.
	Specs api.Rules `json:"specs,omitempty"`
}

// Both CiliumNetworkPolicy and CiliumClusterwideNetworkPolicy embed the
// same api.Rule type. During policy resolution, the Cilium agent collects
// all policies (both kinds) whose endpointSelector matches a given endpoint
// and evaluates them uniformly.
//
// Traffic between two endpoints is subject to policy evaluation at both
// the source and destination. The source endpoint's egress policies and
// the destination endpoint's ingress policies must each independently
// permit the connection for it to be allowed.
