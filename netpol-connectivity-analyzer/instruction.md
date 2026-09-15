A microservices platform spans four Kubernetes namespaces (`web`, `api`, `db`, `monitoring`) with NetworkPolicies controlling inter-service traffic. Full Kubernetes manifests (Namespaces, Deployments, Services, NetworkPolicies) are at `/app/manifests/`.

`/app/queries.json` defines 25 pod-to-pod connectivity queries (source deployment, destination deployment, port, protocol). `/app/connectivity_requirements.json` classifies a subset of these queries as `required` (must remain ALLOWED for the application to function) or `forbidden` (must remain DENIED for security compliance).

Six proposed NetworkPolicy modifications are in `/app/proposed_changes/` as YAML files. Each specifies an `action` (`replace`, `add`, or `replace_multiple`), identifies the target policy/namespace, and provides full replacement policy YAML.

Design and implement a tool that evaluates the impact of each proposed change on the platform's connectivity posture. The tool must compute the correct baseline verdict (`ALLOWED` or `DENIED`) for all 25 queries under the current NetworkPolicies, applying correct Kubernetes NetworkPolicy semantics including bidirectional egress+ingress evaluation. For each of the 6 proposed changes, it must compute the modified verdicts, identify which queries flip between ALLOWED and DENIED, and classify the change as:

- `SAFE` — no required connections break, no forbidden connections open
- `BREAKS_REQUIRED` — at least one required connection becomes DENIED
- `OPENS_FORBIDDEN` — at least one forbidden connection becomes ALLOWED
- `CRITICAL` — both breaks a required AND opens a forbidden connection

Write the complete impact report to `/app/impact_report.json` conforming to `/app/output_schema.json`.