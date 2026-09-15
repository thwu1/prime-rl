The `/app` directory contains a multi-tenant cloud native platform configuration with OPA Rego governance policies and an OpenTelemetry Collector observability pipeline. Both have multiple bugs.

## Platform Policies (`/app/policies/`)

OPA Rego policy files enforce multi-tenant governance: container image validation, resource enforcement per tier, and network segmentation. Helper functions in `/app/policies/lib/k8s.rego` handle Kubernetes resource quantity parsing (CPU millicores, memory in binary bytes). The test files (`*_test.rego`) define correct expected behavior. Fix all bugs in the policy and helper files so that `opa test /app/policies/ -v` reports zero failures.

## Observability Pipeline (`/app/observability/collector-config.yaml`)

The OpenTelemetry Collector configuration has pipeline routing errors, undefined component references, and processor ordering issues. Fix the config so that:
- Every receiver, processor, and exporter referenced in a service pipeline is defined in its corresponding top-level section
- Traces export to `otlp/jaeger`, metrics export to `prometheusremotewrite`, logs export to `loki`
- The `memory_limiter` processor is the first processor in every pipeline

## Reference

`/app/platform-spec.yaml` documents the intended platform governance rules and observability architecture.