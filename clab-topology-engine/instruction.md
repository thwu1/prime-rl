Build `/app/clab_federator.py` -- a CLI tool that merges multiple independent containerlab pod topologies into a single federated topology with Graphviz visualization support.

The tool must correctly resolve containerlab's 4-level property inheritance (node > group > kind > defaults) when constructing the merged output. The resolution algorithm is NOT documented in prose -- reverse-engineer it from the canonical Go implementation at `/app/containerlab_src/types_topology.go`. Study `GetNodeKind`, `GetNodeGroup`, `getField`, and `mergeStringMapFields` carefully: there are non-obvious transitive resolution paths (e.g., a kind definition can specify a `group` field, and the defaults section can specify a `group` that indirectly determines kind resolution). These subtleties affect all property lookups and must be faithfully reproduced.

The merged topology must be flat -- all properties fully materialized per node, with no kinds/groups/defaults sections. The federation resolves namespace collisions via pod-name prefixing, partitions a base management subnet into non-overlapping per-pod subnets with correct IP allocation, generates full-mesh inter-pod border links with properly numbered interfaces, and detects infeasible configurations.

The federation specification format, behavioral rules (namespace prefixing, subnet partitioning, border link generation, interface numbering, feasibility checks), and expected output formats are documented in `/app/reference.md`. Pod topologies are at `/app/pods/` and federation specifications at `/app/federation_specs/`.

Required subcommands:
- `federate <spec>` -- merged topology as YAML to stdout; exit 1 if infeasible
- `allocate-ips <spec>` -- per-node IP map as JSON to stdout; exit 1 if infeasible
- `inventory <spec>` -- Ansible inventory as YAML to stdout; exit 1 if infeasible
- `check <spec>` -- feasibility report as JSON to stdout (must be queryable with `jq`)
- `graph <spec>` -- Graphviz DOT-format undirected graph to stdout with pod subgraph clusters and dashed border links; output must pass `dot -Tcanon` validation; exit 1 if infeasible