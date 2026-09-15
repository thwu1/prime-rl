package platform.pod_policy

import future.keywords.in
import future.keywords.contains
import future.keywords.if

import data.lib.k8s

# ============================================================
# Image Governance
# ============================================================

allowed_registries := {
    "gcr.io/acme-prod/",
    "ghcr.io/acme/",
    "gcr.io/acme-infra/",
    "docker.io/library/",
}

# Collect all containers that should be validated
all_containers contains container if {
    some container in input.spec.containers
}

# Violation: image from unapproved registry
violation contains msg if {
    some container in all_containers
    image := container.image
    not image_from_allowed_registry(image)
    msg := sprintf("image_registry: container '%s' uses unapproved image '%s'", [container.name, image])
}

image_from_allowed_registry(image) if {
    some registry in allowed_registries
    startswith(image, registry)
}

# Violation: production namespace requires digest-pinned images
violation contains msg if {
    endswith(input.metadata.namespace, "-prod")
    some container in all_containers
    image := container.image
    contains(image, "@sha256:")
    msg := sprintf("image_digest: container '%s' in production must use digest-pinned image", [container.name])
}

# ============================================================
# Resource Enforcement
# ============================================================

tier_limits := {
    "gold": {"max_cpu_millicores": 32000, "max_memory_bytes": 68719476736},
    "silver": {"max_cpu_millicores": 16000, "max_memory_bytes": 34359738368},
    "bronze": {"max_cpu_millicores": 8000, "max_memory_bytes": 17179869184},
}

# Violation: container exceeds tier CPU limit
violation contains msg if {
    tier := input.metadata.labels["platform.acme.io/tier"]
    limits := tier_limits[tier]
    some container in input.spec.containers
    cpu_millicores := k8s.parse_cpu(container.resources.limits.cpu)
    cpu_millicores > limits.max_cpu_millicores
    msg := sprintf("resource_cpu: container '%s' exceeds tier '%s' CPU limit", [container.name, tier])
}

# Violation: container exceeds tier memory limit
violation contains msg if {
    tier := input.metadata.labels["platform.acme.io/tier"]
    limits := tier_limits[tier]
    some container in input.spec.containers
    mem_bytes := k8s.parse_memory(container.resources.limits.memory)
    mem_bytes > limits.max_memory_bytes
    msg := sprintf("resource_memory: container '%s' exceeds tier '%s' memory limit", [container.name, tier])
}

# Violation: CPU request-to-limit ratio too low (must be >= 0.5)
violation contains msg if {
    some container in input.spec.containers
    cpu_request := k8s.parse_cpu(container.resources.requests.cpu)
    cpu_limit := k8s.parse_cpu(container.resources.limits.cpu)
    ratio := cpu_limit / cpu_request
    ratio < 0.5
    msg := sprintf("resource_ratio_cpu: container '%s' CPU request-to-limit ratio too low", [container.name])
}

# Violation: memory request-to-limit ratio too low (must be >= 0.5)
violation contains msg if {
    some container in input.spec.containers
    mem_request := k8s.parse_memory(container.resources.requests.memory)
    mem_limit := k8s.parse_memory(container.resources.limits.memory)
    ratio := mem_limit / mem_request
    ratio < 0.5
    msg := sprintf("resource_ratio_memory: container '%s' memory request-to-limit ratio too low", [container.name])
}

# Violation: containers must have resource requirements defined
violation contains msg if {
    some container in input.spec.containers
    not container.resources
    msg := sprintf("resource_missing: container '%s' has no resource requirements", [container.name])
}

violation contains msg if {
    some container in input.spec.containers
    container.resources
    not container.resources.limits
    msg := sprintf("resource_missing_limits: container '%s' has no resource limits", [container.name])
}

violation contains msg if {
    some container in input.spec.containers
    container.resources
    not container.resources.requests
    msg := sprintf("resource_missing_requests: container '%s' has no resource requests", [container.name])
}
