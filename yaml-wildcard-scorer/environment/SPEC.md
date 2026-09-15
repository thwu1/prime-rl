# Configuration Drift Analysis – Specification

## Overview

This document specifies a drift analysis algorithm for comparing Kubernetes desired state (managed by Kustomize) against live cluster state. The algorithm produces a similarity score in [0.0, 1.0] for each matched resource pair, where 1.0 means the live state perfectly conforms to the desired state.

## Desired State Rendering

The desired state for each environment is defined as a Kustomize overlay. Render the desired state by executing `kustomize build <overlay_directory>`. The output is a multi-document YAML stream containing one or more Kubernetes resource manifests.

## Resource Matching

Resources from the rendered desired state and live state are matched by their identity: `apiVersion`, `kind`, and `metadata.name`. For each resource in the live state, find the matching resource in the desired state by comparing these three fields. Only matched pairs are scored. If a live resource has no matching desired counterpart, its drift score is 0.0.

## Wildcard Annotations

Live state YAML files may designate certain leaf fields as **wildcards** using a trailing `# *` comment on a key-value line:

```yaml
metadata:
  name: example-pod # *
spec:
  replicas: 3
```

Here `name` is wildcarded — any desired-state value is acceptable. `replicas` requires an exact match. Wildcard annotations appear only on leaf key-value lines, never on structural or container keys.

Standard YAML parsers discard comments during parsing. The analyzer must therefore extract wildcard information from the raw live state text before parsing the YAML.

## Leaf Key-Value Pairs

The metric operates on **leaf key-value pairs** — terminal values in the YAML mapping hierarchy. Each leaf is identified by its **key path**: the ordered sequence of mapping keys from the document root to the leaf value.

Scalars, lists of scalars, and other non-mapping values are leaves. Nested mappings and sequences of mappings are structural nodes that are traversed but not themselves leaves.

Key paths reflect the mapping hierarchy only. When sequences of mappings occur (e.g., a list of container definitions or a list of port objects), each mapping's leaves are extracted independently under the enclosing key — sequence indices do **not** appear in key paths.

## Kubernetes Semantic Extensions

Before computing the similarity score, apply these Kubernetes-aware normalizations to both the desired and live state resources:

### Resource Quantity Normalization

Values at leaf positions under `resources.requests.*` or `resources.limits.*` (at any nesting depth) are Kubernetes resource quantities. Before comparison, normalize both values to a common numeric form:

- **Memory**: String suffixes are converted to bytes: `Ki` (multiply by 1024), `Mi` (multiply by 1048576), `Gi` (multiply by 1073741824). Plain numeric values (integer or float) already represent bytes.
- **CPU**: A string suffix of `m` denotes millicores (divide by 1000 to get cores). Plain numeric values (integer or float) already represent cores.

After normalization, compare quantities as numbers. Two quantities are equal if their normalized numeric values are equal.

### Port Protocol Defaulting

Within container specifications, port objects reside inside a `ports` list, which in turn sits inside a `containers` list. If a port mapping lacks a `protocol` field, inject `protocol: TCP` before leaf extraction. Apply this defaulting to both desired and live state resources.

## Similarity Score

For each matched resource pair, the live state serves as the **reference** and the kustomize-rendered desired state serves as the **candidate**:

    score = |intersection| / |union|
    |union| = |reference_leaves| + |candidate_leaves| - |intersection|

A reference leaf is counted in the intersection when a candidate leaf exists with an identical key path and either:
- the reference leaf is wildcarded, or
- the values are equal (after applying Kubernetes semantic extensions for resource quantities; all other values use native Python equality on the YAML-parsed types).

If the union is zero, the score is 0.0.

## Output

Write a JSON report to `/app/output/drift_report.json`:

```json
{
  "environments": {
    "<env>": {
      "resources": {
        "<apiVersion>/<kind>/<name>": <score>,
        ...
      },
      "mean": <env_mean>
    },
    ...
  },
  "aggregate_mean": <overall_mean>
}
```

- Resource keys use `apiVersion/kind/name` format (e.g., `apps/v1/Deployment/alpha-webapp`).
- Environment `mean` is the arithmetic mean of that environment's resource scores.
- `aggregate_mean` is the arithmetic mean of all individual resource scores across all environments.

## Environment Notes

- Values are compared using their YAML-parsed native types. Quoted and unquoted values may yield different Python types (e.g., `"true"` is a string, `true` is a boolean; `"10"` is a string, `10` is an integer).
- `kustomize`, `yq`, and `jq` are available in the environment.
