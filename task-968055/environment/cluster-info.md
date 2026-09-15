# Cluster Architecture

## Kubernetes Version
v1.29.0

## Namespaces
- `production` — Application workloads (frontend, backend-api, database, redis)
- `pipeline` — CI/CD automation (build jobs, deployment pipelines)
- `monitoring` — Observability stack (Prometheus, Grafana)
- `kube-system` — Core Kubernetes components
- `default` — Miscellaneous resources

## Service Accounts
- `pipeline:ci-bot` — CI pipeline runner, executes build and test jobs within the pipeline namespace
- `production:deploy-bot` — ArgoCD application controller, manages deployment rollouts in production
- `monitoring:prometheus-sa` — Prometheus service account for cluster-wide metrics collection

## Application Architecture
```
[Internet] -> [Ingress Controller] -> frontend:8080 -> backend-api:3000 -> database:5432
                                                                       -> redis:6379
```

## RBAC Configuration
- `ci-bot` has a ClusterRoleBinding (`ci-pipeline-binding`) to ClusterRole `ci-pipeline-reader` granting read access to pods and configmaps cluster-wide
- `deploy-bot` has a RoleBinding in `production` granting deployment management permissions
- `prometheus-sa` has a ClusterRoleBinding granting read access to pods, nodes, and endpoints cluster-wide
