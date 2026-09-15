# Configuration Review Notes
# Author: jsmith
# Date: 2024-11-15

Reviewed the broken/ directory to assess current state before handoff.

## File-by-File Assessment

### htpasswd
Generated for the spec users. Uses standard Apache password format.
Some users may not have been added yet.

### namespaces.yaml
All 4 namespaces present with correct labels. Ready to use as-is.

### oauth.yaml
Identity provider name and type match spec. Secret reference is correct.
Status: Complete, no changes needed.

### rbac-cluster-admin.yaml
Binds cluster-admin-01 to cluster-admin role. Verified correct.

### rbac-developers-frontend.yaml
Binds developers group to edit role in web-frontend. Looks correct.

### netpol-api-gateway.yaml
Found an issue: allow-to-backend egress policy is missing DNS port 53
rules. Pods won't be able to resolve service names without this.
The ingress rules (allow-from-frontend) look fine — correctly scoped.

### netpol-order-service-deny.yaml
Default deny policy is in place for order-service. Standard config.

### quota-inventory-db.yaml
Standard resource quota for database namespace. Values match spec.

### quota-web-frontend.yaml
Added starter quota for web-frontend based on the spec. Should be ready.

### limitrange-order-service.yaml
Limit range for order-service containers. Min/max/defaults are configured.
Might want to double-check the values at some point.

### route-api-passthrough.yaml
Passthrough route for API service. Includes TLS configuration for
the connection. Should work with the api-gateway backend service.

### TLS certificates (broken/tls/)
CA and frontend certs were generated. Frontend cert has SANs set.
Need to verify they match the spec hostnames.

## Remaining Work
- Create RBAC bindings for remaining roles (qa-team, operations, team-lead admin)
- Create network policies for web-frontend, order-service, inventory-db
- Create quotas and limit ranges for remaining namespaces
- Create edge route for frontend with TLS
- Create SCC bindings for inventory-db postgres service account
- Assemble kustomization.yaml referencing all resources
