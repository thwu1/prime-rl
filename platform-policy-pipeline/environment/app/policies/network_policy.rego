package platform.network_policy

import future.keywords.in
import future.keywords.contains
import future.keywords.if

# Validates namespace NetworkPolicy configuration for multi-tenant isolation.
#
# Input format:
# {
#   "metadata": {"name": "<namespace-name>"},
#   "network_policies": [<list of NetworkPolicy spec objects>]
# }

# Violation: namespace missing a proper default-deny NetworkPolicy
violation contains msg if {
    not has_default_deny(input.network_policies)
    msg := sprintf("network_default_deny: namespace '%s' missing default-deny NetworkPolicy", [input.metadata.name])
}

has_default_deny(policies) if {
    some policy in policies
    is_default_deny(policy)
}

# A default-deny NetworkPolicy must select all pods and deny both directions
is_default_deny(policy) if {
    policy.spec.podSelector == {}
    "Ingress" in policy.spec.policyTypes
    not policy.spec.ingress
}
