An evaluator at `/app/netpol-eval` determines whether network traffic between two Kubernetes pods is permitted or denied according to the cluster's NetworkPolicy resources. Its CLI interface:

```
/app/netpol-eval <manifests_dir> <src_ns>/<src_pod> <dst_ns>/<dst_pod> <port> <protocol>
```

It reads Kubernetes resource manifests (`Namespace`, `Pod`, and `NetworkPolicy` of `networking.k8s.io/v1`) from `<manifests_dir>` and outputs exactly one line: `ALLOW` or `DENY`. Pod resources carry `status.podIP` for IP-based evaluation. Manifest directories may use different formats: a single `cluster.yaml` multi-document YAML, a kustomize overlay (containing `kustomization.yaml`), or resources split across multiple `.yaml` files. The tools `kustomize` and `yq` (v4) are pre-installed at `/usr/local/bin/`.

Eleven scenario directories at `/app/manifests/scenario-01` through `scenario-11` represent progressively complex cluster configurations — from no-policy baselines through multi-tenant isolation with label expressions, CIDR blocks, port ranges, and varied manifest formats. The evaluator currently handles some simple scenarios correctly but produces incorrect verdicts or crashes on several of the more complex ones.

Diagnose all defects in the current evaluator and replace `/app/netpol-eval` with a correct implementation that faithfully conforms to the Kubernetes `networking.k8s.io/v1` NetworkPolicy specification and correctly processes all supported manifest formats — including arbitrary valid cluster states not present in `/app/manifests/`.