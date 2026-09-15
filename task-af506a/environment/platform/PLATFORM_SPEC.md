# Internal Developer Platform — Configuration Specification

## Overview

This directory contains the Kubernetes manifests for a multi-tenant Internal Developer Platform (IDP) serving two application teams. The platform provides self-service infrastructure provisioning, GitOps-based delivery, policy enforcement, observability, and tenant isolation.

## Tenants

| Tenant | Namespace | Pod Security Standard | Cost Center |
|--------|-----------|----------------------|-------------|
| team-alpha | `team-alpha` | `restricted` | eng-backend |
| team-beta | `team-beta` | `baseline` | eng-frontend |

## Self-Service Infrastructure (Crossplane)

Teams provision PostgreSQL databases via `PostgreSQLDatabase` claims. The Crossplane Composite Resource Definition (XRD) schema defines three parameters:

- `storageGB` (integer) — PVC storage size in gigabytes
- `replicas` (integer) — StatefulSet replica count
- `version` (string) — PostgreSQL major version

The Composition must correctly propagate ALL XRD-defined parameters from the Composite Resource to composed Kubernetes resources. Every `fromFieldPath` referencing `spec.parameters.*` in the Composition must correspond to a field that actually exists in the XRD schema.

## GitOps Delivery (Argo CD)

- All tenant workloads deploy through Argo CD Applications in the `platform-teams` AppProject.
- Each Application MUST deploy to its corresponding tenant namespace — **never** to `default`.
- Source repository: `https://github.com/acme-corp/platform-apps.git` on the `main` branch.
- Sync policy: automated with prune and self-heal, retry with exponential backoff.

## Policy Enforcement (Kyverno)

Two ValidatingPolicies are in effect, both configured with `validationFailureAction: Enforce` so that non-compliant resources are **rejected** at admission time (not merely audited):

1. **require-labels** — All workload resources (Deployments, StatefulSets, DaemonSets, Services) must carry `app.kubernetes.io/name` and `app.kubernetes.io/managed-by` labels.
2. **enforce-resource-limits** — All Deployments must declare CPU and memory limits on every container (including init containers). The policy must correctly match the Deployment resource, which belongs to the `apps/v1` API group.

A policy set to `Audit` mode will only log violations without blocking them — this is a silent misconfiguration that undermines enforcement.

## Observability

### Prometheus Alerting Rules

| Alert | Behavior |
|-------|----------|
| HighErrorRate | Fires when aggregate HTTP 5xx error rate exceeds 5% **sustained for 10 minutes**. Must use `sum by (namespace, service)` aggregation to avoid noisy per-pod alerts. Must include a `for` duration. |
| HighMemoryUsage | Fires when pod memory exceeds 90% of limits for 15 minutes. |
| PodCrashLooping | Fires when a pod restarts more than 3 times in 15 minutes. |
| PVCNearCapacity | Fires when PVC usage exceeds 85% for 30 minutes. |

Recording rules compute `p99` latency and error ratio aggregated by namespace and service.

### OpenTelemetry Collector

The collector runs as a Deployment with three pipelines:

| Pipeline | Receivers | Processors | Exporters |
|----------|-----------|------------|-----------|
| traces | `otlp` | `memory_limiter`, `attributes/tenant`, `batch` | `otlp/traces` |
| metrics | `otlp`, `prometheus` | `memory_limiter`, `batch` | `otlphttp/metrics` |
| logs | `otlp` | `memory_limiter`, `batch` | `debug` |

**Every exporter name referenced in the `service.pipelines` section must match a defined exporter in the `exporters` section.** A name mismatch causes the Collector to fail on startup.

**The `memory_limiter` processor must always be the first processor in every pipeline.** Placing any buffering processor (such as `batch`) before `memory_limiter` allows unbounded data accumulation before limits are enforced, which can cause the Collector to OOM under load. The processor ordering shown in the table above is authoritative.

## RBAC

- The `platform-tenant-admin` ClusterRole defines the permission set for tenant teams.
- Each tenant receives a **namespace-scoped `RoleBinding`** (not a `ClusterRoleBinding`) binding to the `platform-tenant-admin` ClusterRole.
- Tenant bindings must NEVER be cluster-scoped. A ClusterRoleBinding would grant the tenant access to all namespaces, violating tenant isolation.
- Secrets access is read-only (`get`, `list`).

## Resource Governance

Each tenant namespace has a ResourceQuota and LimitRange:

- **LimitRange constraints must be internally consistent**: for each resource type (cpu, memory), `max >= default >= defaultRequest >= min`. A LimitRange where `max` is less than `min` is invalid and will be rejected by the Kubernetes API server.
- ResourceQuotas must accommodate planned workloads with headroom.
