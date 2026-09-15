A production Kubernetes control plane node was compromised by unauthorized modifications to its PKI certificates, static pod manifests, and admin kubeconfig. All recovered artifacts are at `/app/`. An etcd snapshot taken before the incident is also available.

Audit every component against Kubernetes standards, identify all deviations, and produce fully corrected versions.

## Cluster Parameters

- Control plane IP: `192.168.1.10`
- Service ClusterIP range: `10.96.0.0/12`
- API server endpoint: `https://192.168.1.10:6443`

## Deliverables

**Corrected PKI** → `/app/pki-fixed/`

Audit all certificates in `/app/pki/` and produce corrected versions. Required output files: `ca.crt`, `ca.key` (copy from source if valid), `apiserver.crt` + key, `admin.crt` + key, `scheduler.crt` + key. Every certificate must be signed by the appropriate cluster CA, carry the correct Subject fields (CN and O) per Kubernetes conventions, and the API server certificate must include all standard SANs derived from the cluster parameters above.

**Corrected Static Pod Manifests** → `/app/manifests-fixed/`

Audit all manifests in `/app/manifests/` and produce corrected versions with identical filenames: `kube-apiserver.yaml`, `kube-scheduler.yaml`, `kube-controller-manager.yaml`, `etcd.yaml`. Each must be a valid Pod spec conforming to kubeadm defaults and Kubernetes security best practices. Audit port assignments, TLS certificate paths, authorization modes, required component flags, bind addresses, kubeconfig file references, data directories, and volume definitions for correctness and internal consistency.

**etcd Restore and Backup**

Restore the snapshot at `/app/etcd/pre-failure-snapshot.db` to data directory `/app/etcd/restored/`. Produce a valid backup snapshot at `/app/etcd/backup.db` that contains at least one key.

**Admin Kubeconfig** → `/app/kubeconfig/admin.kubeconfig`

Reconstruct a working admin kubeconfig from `/app/kubeconfig/admin.kubeconfig.broken`. The output must be a valid Kubernetes Config (`apiVersion: v1`, `kind: Config`) with cluster server `https://192.168.1.10:6443`, embedded `certificate-authority-data`, and user credentials as embedded `client-certificate-data` (carrying the correct Organization for cluster-admin RBAC mapping) and `client-key-data`.

**RBAC Manifests** → `/app/rbac/`

Read the policy specification at `/app/rbac/requirements.txt` and create RBAC YAML manifests (`.yaml` or `.yml` files) in `/app/rbac/` that satisfy all stated requirements, with correct API groups, resources, verbs, and subject bindings.