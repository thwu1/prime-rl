A previous administrator attempted to configure Kubernetes/OpenShift resource manifests for a multi-tenant production cluster. The authoritative specification is at `/app/spec.yaml`. Their partial work is in `/app/broken/`, and diagnostic notes they left behind are at `/app/notes.md`.

Produce a complete, validated configuration in `/app/output/` that faithfully implements every aspect of the specification. The output must include:

- `/app/output/htpasswd` — htpasswd credential file for all users defined in the spec
- `/app/output/oauth.yaml` — OAuth custom resource for the identity provider
- `/app/output/namespaces.yaml` — All namespace definitions (multi-document YAML)
- `/app/output/rbac/` — Individual RoleBinding and ClusterRoleBinding YAML files (one per binding, named `{binding-name}.yaml`)
- `/app/output/network-policies/{namespace}.yaml` — NetworkPolicy YAML files per namespace (multi-document)
- `/app/output/quotas/{namespace}.yaml` — ResourceQuota YAML files per namespace
- `/app/output/limit-ranges/{namespace}.yaml` — LimitRange YAML files per namespace
- `/app/output/tls/ca.crt`, `ca.key` — Self-signed CA certificate and key
- `/app/output/tls/frontend.crt`, `frontend.key` — Server certificate signed by the CA, with SANs matching the spec
- `/app/output/routes/` — Route YAML files per route in the spec
- `/app/output/scc/` — ServiceAccount and SCC binding YAML files
- `/app/output/kustomization.yaml` — Kustomize overlay referencing all YAML resources (must pass `kustomize build`)

The broken files contain an unknown number of errors spanning multiple resource types. The previous admin's diagnostic notes may or may not be accurate. Every file in `/app/broken/` must be independently verified against the spec before being used.