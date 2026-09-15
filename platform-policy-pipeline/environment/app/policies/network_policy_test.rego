package platform.network_policy

# Test: proper default-deny with both Ingress and Egress - no violations
test_proper_default_deny {
    violations := violation with input as {
        "metadata": {"name": "team-alpha"},
        "network_policies": [
            {
                "metadata": {"name": "default-deny"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress", "Egress"]
                }
            }
        ]
    }
    count(violations) == 0
}

# Test: no network policies at all - violation expected
test_no_policies {
    violations := violation with input as {
        "metadata": {"name": "team-alpha"},
        "network_policies": []
    }
    count(violations) > 0
}

# Test: only non-default-deny policies present - violation expected
test_missing_default_deny {
    violations := violation with input as {
        "metadata": {"name": "team-alpha"},
        "network_policies": [
            {
                "metadata": {"name": "allow-web"},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "web"}},
                    "policyTypes": ["Ingress"],
                    "ingress": [{"from": [{"podSelector": {}}]}]
                }
            }
        ]
    }
    count(violations) > 0
}

# Test: ingress-only deny is NOT a valid default-deny
# A proper default-deny must deny BOTH ingress and egress traffic
test_ingress_only_not_default_deny {
    violations := violation with input as {
        "metadata": {"name": "team-beta"},
        "network_policies": [
            {
                "metadata": {"name": "deny-ingress-only"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress"]
                }
            }
        ]
    }
    count(violations) > 0
}

# Test: egress-only deny is NOT a valid default-deny either
test_egress_only_not_default_deny {
    violations := violation with input as {
        "metadata": {"name": "team-gamma"},
        "network_policies": [
            {
                "metadata": {"name": "deny-egress-only"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Egress"]
                }
            }
        ]
    }
    count(violations) > 0
}

# Test: default-deny among other policies - no violation
test_default_deny_with_other_policies {
    violations := violation with input as {
        "metadata": {"name": "team-alpha"},
        "network_policies": [
            {
                "metadata": {"name": "allow-web"},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "web"}},
                    "policyTypes": ["Ingress"],
                    "ingress": [{"from": [{"podSelector": {}}]}]
                }
            },
            {
                "metadata": {"name": "default-deny"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress", "Egress"]
                }
            }
        ]
    }
    count(violations) == 0
}
