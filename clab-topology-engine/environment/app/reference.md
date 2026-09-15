# Containerlab Topology Federation Reference

## Containerlab Topology Format

Containerlab topology files (`*.clab.yml`) are YAML with this structure:

```yaml
name: <lab-name>
prefix: <prefix>           # Default "clab"
mgmt:
  ipv4-subnet: <CIDR>     # Default 172.20.20.0/24
  ipv4-gw: <IP>           # Default: first host in subnet
topology:
  defaults: <NodeDef>     # Global defaults for all nodes
  kinds:
    <kind-name>: <NodeDef>
  groups:
    <group-name>: <NodeDef>
  nodes:
    <node-name>: <NodeDef>
  links:
    - endpoints: ["<node>:<iface>", "<node>:<iface>"]
```

### Node Definition Properties

A `NodeDef` can contain:

**Scalar fields** (most specific level wins): `kind`, `image`, `type`, `group`, `user`, `memory`, `cmd`, `entrypoint`, `startup-config`, `network-mode`, `mgmt-ipv4`, `mgmt-ipv6`, `cpu`, `cpuset`, `shm-size`, `restart-policy`

**Map fields** (merged across all levels): `env`, `labels`

### Property Inheritance

The property resolution algorithm is implemented in containerlab's Go source code at `/app/containerlab_src/types_topology.go`. Your implementation must produce identical results to the Go reference.

Key functions to study:
- `GetNodeKind` — resolves the effective kind for a node; involves multiple fallback paths
- `GetNodeGroup` — resolves the effective group; depends on the resolved kind
- `getField` — generic scalar field resolution through the 4-level hierarchy using the **resolved** group and kind
- `mergeStringMapFields` — map field merge across all levels using the **resolved** group and kind

Note: The `group` field on a `NodeDef` is special — it can appear on defaults, kinds, and groups themselves, creating transitive resolution paths. Read the Go source carefully.

### Ansible Inventory

Containerlab generates Ansible inventory grouped by kind:

```yaml
all:
  children:
    <kind>:
      vars:            # Only for kinds with known defaults
        ansible_network_os: <os>
        ansible_connection: <connection>
        ansible_user: <user>
        ansible_password: <password>
      hosts:
        clab-<lab-name>-<node-name>:
          ansible_host: <mgmt-ipv4>
```

**Known kind Ansible vars:**

| Kind | ansible_network_os | ansible_connection | ansible_user | ansible_password |
|------|-------------------|-------------------|-------------|-----------------|
| srl / nokia_srlinux | nokia.srlinux.srlinux | ansible.netcommon.httpapi | admin | NokiaSrl1! |
| ceos / arista_ceos | arista.eos.eos | ansible.netcommon.httpapi | admin | admin |

Kinds without known defaults (e.g., `linux`) have no `vars` section.

---

## Federation Specification Format

A federation specification (`*.federation.yml`) defines how to merge multiple pod topologies:

```yaml
federation:
  name: <federation-name>
  mgmt:
    ipv4-base: <base-CIDR>          # Supernet encompassing all pod subnets
    pod-prefix-length: <int>         # Prefix length for each pod's subnet
  pods:
    - name: <pod-name>
      topology: <path-to-.clab.yml>
      border-nodes:                  # Nodes that participate in inter-pod links
        - <node-name>
        - <node-name>
  interconnect: full-mesh            # Currently only full-mesh is supported
```

## Federation Tool Subcommands

The tool (`/app/clab_federator.py`) must support five subcommands:

### `federate <spec.yml>`

Produce the merged federated topology as YAML on stdout. Exit with code 1 and print errors to stderr if the federation is infeasible.

### `allocate-ips <spec.yml>`

Produce the per-node IP allocation map as JSON on stdout (`{"<prefixed-node>": "<ip>", ...}`, sorted by key). Exit 1 if infeasible.

### `inventory <spec.yml>`

Produce an Ansible inventory as YAML on stdout. Exit 1 if infeasible.

### `check <spec.yml>`

Produce a feasibility report as JSON on stdout with this structure:

```json
{
  "feasible": true,
  "errors": [],
  "pod_subnets": {"<pod-name>": "<CIDR>", ...},
  "naming_conflicts": [
    {"name": "<node-name>", "pods": ["<pod1>", "<pod2>"]}
  ],
  "border_link_count": 8,
  "total_node_count": 15
}
```

- `feasible`: false if any pod subnet cannot accommodate its nodes, or if the base CIDR cannot be partitioned
- `errors`: list of human-readable error strings
- `pod_subnets`: map of pod name to assigned subnet CIDR string
- `naming_conflicts`: list of node names appearing in multiple pods, sorted by name; each entry has the name and list of pod names
- `border_link_count`: total number of inter-pod links to be generated
- `total_node_count`: total nodes across all pods

### `graph <spec.yml>`

Produce a Graphviz DOT-format undirected graph of the federated topology to stdout. Exit 1 if infeasible.

Requirements:
- Use `graph` (not `digraph`) format
- Group nodes from each pod in a `subgraph cluster_<pod_name>` block
- Include all federated nodes with their prefixed names
- All edges must have `label` attributes showing the interface pair (e.g., `"eth1:eth2"`)
- Border links must have `style=dashed` to distinguish them from internal links
- Output must be valid DOT parseable by `dot -Tcanon`

## Federation Behavioral Rules

### Namespace Resolution

All node names in the merged topology are prefixed with their pod name using a hyphen separator: `<pod-name>-<node-name>`. For example, node `spine1` in pod `east` becomes `east-spine1`.

Link endpoints within each pod are updated to use prefixed node names. Interface names remain unchanged.

Each node in the merged topology receives a label `clab-federation-pod` set to its pod name.

### Property Resolution

Each pod's topology is resolved independently using the containerlab property resolution algorithm (see Go source). The merged topology is flat: it contains only resolved nodes with all inherited properties materialized. There are no `kinds`, `groups`, or `defaults` sections in the output.

The `group` field is removed from resolved nodes in the merged output (it is no longer meaningful in the flat structure).

### IP Address Space Partitioning

The base CIDR (`mgmt.ipv4-base`) is subdivided into per-pod subnets using the specified `pod-prefix-length`. Pods receive subnets in declaration order — the first pod gets the first subnet, the second pod gets the second, etc.

**Feasibility**: If the base CIDR cannot accommodate enough subnets of the given prefix length for all pods, the federation is infeasible.

**Per-pod capacity**: Each pod's subnet must have enough usable addresses for all its nodes. Usable addresses = total addresses - 3 (network address + broadcast address + gateway). If a pod has more nodes than usable addresses, the federation is infeasible.

### IP Allocation Within Each Pod

Within each pod's assigned subnet:

1. The gateway is the first host address (network_address + 1)
2. Reserved addresses: network address, broadcast address, gateway
3. Nodes are sorted alphabetically by their **prefixed** name
4. IPs are allocated sequentially starting from gateway + 1, skipping reserved addresses
5. Each allocated IP is added to the reserved set

### Full-Mesh Border Link Generation

In full-mesh mode, every border node of every pod connects to every border node of every other pod.

**Link generation order**:

1. Iterate over all pod pairs (i, j) where i < j, with i and j being declaration order indices
2. For each pod pair, iterate over border nodes of pod i in declaration order
3. For each border node of pod i, iterate over border nodes of pod j in declaration order
4. Generate one link per border node pair

**Interface naming**: Border links use sequential `ethN` interfaces. The N for each node starts from the count of that node's existing interfaces in its pod's internal links, plus one. As border links are generated, the counter increments for each node.

For example, if `spine1` in pod `east` has 2 interfaces from internal links (eth1, eth2), its first border link uses eth3, the next uses eth4, etc.

### Merged Topology Output Format

```yaml
name: <federation-name>
mgmt:
  ipv4-subnet: <base-CIDR>
topology:
  nodes:
    <pod>-<node>:
      kind: <resolved-kind>
      image: <resolved-image>
      mgmt-ipv4: <allocated-ip>
      labels:
        <merged-labels>
        clab-federation-pod: <pod-name>
      env:
        <merged-env>       # Only present if non-empty
      # ... other resolved scalar fields
  links:
    # Internal links first (in pod declaration order, preserving each pod's link order)
    - endpoints: ["<pod>-<node>:<iface>", "<pod>-<node>:<iface>"]
    # Then border links (in generation order)
    - endpoints: ["<pod-i>-<node>:<iface>", "<pod-j>-<node>:<iface>"]
```

### Federated Ansible Inventory

The inventory uses the federation name as the lab name in hostnames:

```
clab-<federation-name>-<pod-name>-<node-name>
```

Nodes are grouped by their resolved kind. Kind-specific Ansible vars are applied per the standard containerlab mapping. IPs come from the federated IP allocation.
