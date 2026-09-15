# Multi-Tier Platform Governance Specification

## Overview

This specification defines the complete resource governance model for a multi-tenant Kubernetes platform. Three tenant teams operate at different service tiers with distinct resource guarantees, isolation requirements, and observability targets. All configurations described below must be implemented or fixed to bring the platform into compliance.

## Cluster Capacity

| Resource | Total Allocatable | System Reserved | Available for Tenants |
|----------|-------------------|-----------------|----------------------|
| CPU | 48 cores | 8 cores | **40 cores** |
| Memory | 192Gi | 32Gi | **160Gi** |

Maximum cluster-wide overcommit ratio (sum of all tenant limits / sum of all tenant requests): **1.5**

## Tenant Service Tiers

| Property | Platinum (`team-core`) | Gold (`team-analytics`) | Silver (`team-edge`) |
|----------|----------------------|------------------------|---------------------|
| Namespace | `team-core` | `team-analytics` | `team-edge` |
| Min `requests.cpu` | 16 | 12 | 8 |
| Min `requests.memory` | 64Gi | 48Gi | 32Gi |
| Max `limits.cpu` | 24 | 18 | 12 |
| Max `limits.memory` | 96Gi | 72Gi | 48Gi |
| Max `pods` | 100 | 60 | 30 |
| Per-tenant burst ratio (`limits / requests`) | ≤ 1.5 | ≤ 1.5 | ≤ 1.5 |

## ResourceQuota

Create a ResourceQuota file (`resourcequota.yaml`) in each tenant directory (`/app/tenants/<team>/`). Each quota must define: `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, and `pods`.

### Capacity Constraints

- Each tenant's `requests.cpu` ≥ that tier's minimum
- Each tenant's `requests.memory` ≥ that tier's minimum
- Each tenant's `limits.cpu` ≤ that tier's maximum
- Each tenant's `limits.memory` ≤ that tier's maximum
- Each tenant's `pods` ≤ that tier's maximum
- Sum of all tenants' `requests.cpu` ≤ 40
- Sum of all tenants' `requests.memory` ≤ 160Gi
- Sum of all tenants' `limits.cpu` ≤ 60 (i.e. available × 1.5 overcommit)
- Sum of all tenants' `limits.memory` ≤ 240Gi
- Per-tenant: `limits.cpu / requests.cpu` ≤ 1.5
- Per-tenant: `limits.memory / requests.memory` ≤ 1.5
- Tier ordering must hold: platinum requests > gold requests > silver requests (for both CPU and memory)

## LimitRange

Create a LimitRange file (`limitrange.yaml`) in each tenant directory (`/app/tenants/<team>/`). Each LimitRange must define a single limit entry of type `Container`.

### Container Limit Bounds per Tier

| Constraint | Platinum (`team-core`) | Gold (`team-analytics`) | Silver (`team-edge`) |
|------------|----------------------|------------------------|---------------------|
| max.cpu ≤ | 4 | 2 | 1 |
| max.memory ≤ | 8Gi | 4Gi | 2Gi |
| min.cpu ≥ | 50m | 50m | 50m |
| min.memory ≥ | 64Mi | 64Mi | 64Mi |

### Internal Consistency

For each resource type (cpu, memory), the following ordering must hold:

    max ≥ default ≥ defaultRequest ≥ min

Both `default` and `defaultRequest` fields must be present for cpu and memory.

## Policy Enforcement (Kyverno)

Create two Kyverno `ClusterPolicy` resources in `/app/policies/`:

### `require-labels.yaml`
- **kind**: ClusterPolicy
- **name**: `require-labels`
- **validationFailureAction**: `Enforce`
- **Match**: Deployments and StatefulSets in API version `apps/v1`
- **Validation**: Every matched resource must carry labels `app.kubernetes.io/name` and `app.kubernetes.io/managed-by`

### `enforce-resource-limits.yaml`
- **kind**: ClusterPolicy
- **name**: `enforce-resource-limits`
- **validationFailureAction**: `Enforce`
- **Match**: Deployments in API version `apps/v1` (the `apps/v1` group — **not** core `v1`)
- **Validation**: Every container (including init containers) must declare both `resources.limits.cpu` and `resources.limits.memory`

A policy set to `Audit` mode will only log violations without blocking them — this silently undermines enforcement.

## RBAC

The `platform-tenant-admin` ClusterRole at `/app/rbac/platform-roles.yaml` defines the tenant permission set.

Each tenant must have a **namespace-scoped `RoleBinding`** (NOT a `ClusterRoleBinding`) in `/app/rbac/team-bindings.yaml` that:
- References the `platform-tenant-admin` ClusterRole via `roleRef`
- Specifies the tenant's namespace in `metadata.namespace`
- Grants access only within that namespace

A `ClusterRoleBinding` would grant the tenant access to all namespaces, violating tenant isolation. Fix any existing bindings that use the wrong kind.

## Observability

### Prometheus Alerting Rules (`/app/monitoring/alerting-rules.yaml`)

| Alert | Expression Requirements | `for` Duration |
|-------|------------------------|---------------|
| HighErrorRate | Rate of 5xx responses / total requests > 0.05. **Must** use `sum by (namespace, service)` aggregation to avoid noisy per-pod alerts. | 10m |
| HighMemoryUsage | Pod memory working set / memory limit > 0.9. Must use `sum by (namespace, pod)`. | 15m |
| PodCrashLooping | Container restarts > 3 in 15 minutes. | 5m |

All alerts must include a `for` duration. An alert without `for` fires on transient spikes.

### OpenTelemetry Collector (`/app/monitoring/otel-collector.yaml`)

| Pipeline | Receivers | Processors (in order) | Exporters |
|----------|-----------|----------------------|-----------|
| traces | `otlp` | `memory_limiter`, `attributes/tenant`, `batch` | `otlp/traces` |
| metrics | `otlp`, `prometheus` | `memory_limiter`, `batch` | `otlphttp/metrics` |
| logs | `otlp` | `memory_limiter`, `batch` | `debug` |

- **`memory_limiter` must be the first processor in every pipeline.** Placing a buffering processor before it allows unbounded data accumulation, risking OOM.
- **Every exporter name in `service.pipelines` must exactly match a defined exporter** in the `exporters` section. A name mismatch causes the Collector to crash on startup.

## Self-Service Infrastructure (Crossplane)

Fix the Composition at `/app/crossplane/composition-database.yaml`:
- Every `fromFieldPath` referencing `spec.parameters.*` must correspond to a field that exists in the XRD schema (`/app/crossplane/xrd-database.yaml`).
- The XRD defines three parameters: `storageGB`, `replicas`, `version`.
