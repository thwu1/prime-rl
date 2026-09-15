package platform.pod_policy

import data.lib.k8s

# ============================================================
# Image Governance Tests
# ============================================================

# Allowed registry - no violations expected
test_allowed_registry {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) == 0
}

# Disallowed registry - violation expected
test_disallowed_registry {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "evil.io/malware:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) > 0
}

# Global infrastructure registry allowed
test_infra_registry_allowed {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "sidecar",
                    "image": "gcr.io/acme-infra/envoy:v1.28",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) == 0
}

# Production namespace WITHOUT digest - must produce digest violation
test_prod_no_digest {
    violations := violation with input as {
        "metadata": {"namespace": "alpha-prod", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) > 0
}

# Production namespace WITH digest - no digest violation expected
test_prod_with_digest {
    violations := violation with input as {
        "metadata": {"namespace": "alpha-prod", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp@sha256:a3ed95caeb02ffe68cdd9fd84406680ae93d633cb16422d00e8a7c22955b46d4",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) == 0
}

# Non-production namespace without digest - no violation (digest only enforced in prod)
test_non_prod_no_digest {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ]
        }
    }
    count(violations) == 0
}

# Init containers from disallowed registries must be caught
test_init_container_disallowed_registry {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ],
            "initContainers": [
                {"name": "init-setup", "image": "evil.io/init-hack:v2.0"}
            ]
        }
    }
    count(violations) > 0
}

# Init containers from allowed registries - no violations
test_init_container_allowed_registry {
    violations := violation with input as {
        "metadata": {"namespace": "gamma-staging", "name": "test-pod"},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "gcr.io/acme-prod/myapp:v1.0",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "256Mi"},
                        "limits": {"cpu": "1000m", "memory": "512Mi"}
                    }
                }
            ],
            "initContainers": [
                {"name": "init-setup", "image": "gcr.io/acme-infra/init-tools:v1.0"}
            ]
        }
    }
    count(violations) == 0
}

# ============================================================
# Resource Enforcement Tests
# ============================================================

# Bronze tier within limits - no violations
test_bronze_within_limits {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "bronze"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "500m", "memory": "256Mi"},
                    "limits": {"cpu": "1000m", "memory": "512Mi"}
                }
            }]
        }
    }
    count(violations) == 0
}

# Bronze tier CPU exceeded (10 cores > 8 core limit)
test_bronze_exceeds_cpu {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "bronze"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "5000m", "memory": "256Mi"},
                    "limits": {"cpu": "10", "memory": "512Mi"}
                }
            }]
        }
    }
    violations[msg]
    startswith(msg, "resource_cpu:")
}

# Bronze tier memory at boundary (17Gi > 16Gi limit)
test_bronze_memory_boundary {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "bronze"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "2000m", "memory": "9Gi"},
                    "limits": {"cpu": "4000m", "memory": "17Gi"}
                }
            }]
        }
    }
    violations[msg]
    startswith(msg, "resource_memory:")
}

# Gold tier within limits - high but valid
test_gold_within_limits {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "gold"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "8000m", "memory": "16Gi"},
                    "limits": {"cpu": "16000m", "memory": "32Gi"}
                }
            }]
        }
    }
    count(violations) == 0
}

# CPU request-to-limit ratio too low (100m/1000m = 0.1 < 0.5)
test_cpu_ratio_too_low {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "gold"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "100m", "memory": "512Mi"},
                    "limits": {"cpu": "1000m", "memory": "1024Mi"}
                }
            }]
        }
    }
    violations[msg]
    startswith(msg, "resource_ratio_cpu:")
}

# CPU ratio acceptable (600m/1000m = 0.6 >= 0.5)
test_cpu_ratio_acceptable {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "gold"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "600m", "memory": "512Mi"},
                    "limits": {"cpu": "1000m", "memory": "1024Mi"}
                }
            }]
        }
    }
    count(violations) == 0
}

# Memory request-to-limit ratio too low (256Mi/4096Mi = 0.0625 < 0.5)
test_memory_ratio_too_low {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "gold"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "500m", "memory": "256Mi"},
                    "limits": {"cpu": "1000m", "memory": "4096Mi"}
                }
            }]
        }
    }
    violations[msg]
    startswith(msg, "resource_ratio_memory:")
}

# Missing resources entirely
test_missing_resources {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "bronze"}
        },
        "spec": {
            "containers": [{"name": "app", "image": "gcr.io/acme-prod/app:v1"}]
        }
    }
    count(violations) > 0
}

# Missing limits only
test_missing_limits {
    violations := violation with input as {
        "metadata": {
            "name": "test-pod",
            "namespace": "gamma-staging",
            "labels": {"platform.acme.io/tier": "bronze"}
        },
        "spec": {
            "containers": [{
                "name": "app",
                "resources": {
                    "requests": {"cpu": "500m", "memory": "256Mi"}
                }
            }]
        }
    }
    count(violations) > 0
}
