Kubernetes manifests at `/app/manifests/` are structured as a kustomize overlay. The production overlay (`/app/manifests/overlays/production/`) applies JSON patches converting several base policy port references from numeric to named, and adds policies using ipBlock CIDR rules with `except` exclusion ranges, `matchExpressions` set-based selectors, and `endPort` port ranges. Pod specs in the base already define named container ports.

Build `/app/analyzer.py` with four subcommands:

**`query <src_ns/pod> <dst_ns/pod> <port> [protocol]`** — Print `ALLOWED` or `DENIED`. Evaluate source egress AND destination ingress. Named port references in policies resolve against the relevant pod's containerPort definitions: for ingress rules, the policy-selected pod; for egress rules, the destination pod. A named port that does not exist on the target pod fails to match. `endPort` defines inclusive port ranges. Default protocol: TCP.

**`query-ip <source_ip> <dst_ns/pod> <port> [protocol]`** — Print `ALLOWED` or `DENIED` for external IP ingress. Only ipBlock peers match external sources; podSelector/namespaceSelector peers do not. Implement CIDR containment with `except` exclusions.

**`unprotected`** — Print JSON with `unprotected_ingress` and `unprotected_egress`: sorted `ns/pod` lists of pods not selected by any NetworkPolicy for that traffic direction.

**`graph`** — Print a valid Graphviz DOT digraph of pod-to-pod connectivity across ports 80, 443, 5432, 8080, 9090, 9200 (TCP). Nodes as `ns/pod`, edges labeled `port/protocol`. Must be parseable by `dot -Tsvg`.

The analyzer must render the production overlay via `kustomize build` before analysis. Full NetworkPolicy semantics required: peer AND/OR logic, `matchExpressions` operators (In, NotIn, Exists, DoesNotExist), named port resolution for both ingress and egress, ipBlock CIDR with except, endPort ranges, policy union across multiple selecting policies, default allow when no policy selects a pod for a direction.