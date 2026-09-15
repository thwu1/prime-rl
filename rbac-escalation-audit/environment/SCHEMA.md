# RBAC Audit Report Schema

The tool must produce `/app/output/report.json` with the following structure:

```json
{
  "effective_permissions": {
    "<subject_key>": {
      "cluster_wide": [<rule>, ...],
      "namespaced": {
        "<namespace>": [<rule>, ...]
      }
    }
  },
  "escalation_paths": [<escalation_path>, ...],
  "wildcard_roles": [<wildcard_entry>, ...]
}
```

## Input Format

The manifest directory `/app/manifests/` contains files with Kubernetes RBAC objects. YAML files may have multiple documents (separated by `---`). Each document is a single Kubernetes RBAC object (ClusterRole, Role, ClusterRoleBinding, or RoleBinding).

## Subject Keys

Format: `<Kind>:<name>` for Users and Groups, `<Kind>:<namespace>:<name>` for ServiceAccounts.

Examples:
- `User:admin@example.com`
- `Group:sre-team`
- `ServiceAccount:monitoring:prometheus`

## Rule Object

```json
{
  "apiGroups": ["", "apps"],
  "resources": ["pods", "deployments"],
  "verbs": ["get", "list", "create"]
}
```

Rules with `nonResourceURLs` should be excluded from the output.

## Effective Permissions

For each subject in `/app/queries.json`:

- `cluster_wide`: rules from ClusterRoleBindings that reference ClusterRoles — these apply across ALL namespaces.
- `namespaced`: rules from RoleBindings — these apply only in the RoleBinding's namespace. A RoleBinding that references a ClusterRole grants that ClusterRole's permissions ONLY within the RoleBinding's namespace (not cluster-wide).

**ClusterRole aggregation**: if a ClusterRole has an `aggregationRule` with `clusterRoleSelectors`, its effective rules are the union of all rules from ClusterRoles whose `metadata.labels` match ALL labels in any of the selectors. The aggregating ClusterRole's own `rules: []` is replaced by the aggregated rules. Aggregation may be transitive — an aggregating ClusterRole may aggregate another aggregating ClusterRole.

**ServiceAccount namespace defaulting**: when a binding's subject is a ServiceAccount and does not specify a `namespace` field, the namespace defaults to the binding's own `metadata.namespace`.

## Escalation Path

```json
{
  "subject": "<subject_key>",
  "type": "<escalation_type>",
  "scope": "<cluster|namespace:name>",
  "detail": "<human-readable description>"
}
```

Scan ALL subjects found in any binding for escalation vectors (not just queried subjects).

Escalation types:
- `bind` — subject has the `bind` verb on resources `roles`, `clusterroles`, `rolebindings`, or `clusterrolebindings` in apiGroup `rbac.authorization.k8s.io` (or wildcard `*` matching these)
- `escalate` — subject has the `escalate` verb on `roles` or `clusterroles` in apiGroup `rbac.authorization.k8s.io` (or wildcard matching)
- `impersonate` — subject has the `impersonate` verb on `users`, `groups`, or `serviceaccounts` resources (or wildcard matching)
- `create_pods` — subject can `create` pods AND has access to `pods/exec` in the same or inherited scope (cluster-wide permissions apply in all namespaces), allowing them to create pods with arbitrary ServiceAccount tokens and exec into them

## Wildcard Entry

```json
{
  "name": "<role_name>",
  "kind": "ClusterRole|Role",
  "wildcard_fields": ["apiGroups", "resources", "verbs"]
}
```

A role should be flagged if any of its rules contain `"*"` in its apiGroups, resources, or verbs arrays. The `wildcard_fields` list indicates which fields contain wildcards (sorted alphabetically).
