# Cluster Information

## Environment
- Kubernetes version: 1.29.2
- Container runtime: containerd 1.7.11
- CNI: Calico 3.27.0
- Nodes: 1 control-plane (cp-01), 3 workers (worker-01, worker-02, worker-03)

## Namespaces
- `default`: Unused
- `kube-system`: Core Kubernetes components
- `webapp`: Customer-facing web application (frontend + backend)
- `payment`: Payment processing microservice
- `monitoring`: Prometheus + Grafana stack

## Security Stack
- Falco: v0.37.0 (systemd service on all nodes)
- No OPA/Gatekeeper admission controllers configured
- No network policies in place
- RBAC enabled

## Trusted Image Registries
- registry.company.com
- registry.k8s.io
- quay.io/calico
- docker.io/calico

## Incident Summary
On 2024-03-15, the security team detected unusual resource consumption on worker nodes.
Investigation revealed potential unauthorized activity. Audit logs and Falco alerts from
the incident window (07:55 - 08:40 UTC) have been collected for analysis.
