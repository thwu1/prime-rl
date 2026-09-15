# OSmosis Model Specification for seL4 Microkit Security Analysis

## 1. Overview

The OSmosis model (from the CellulOS project, UBC Systopia Lab) represents
system resources and protection domains as a bipartite graph for reasoning
about isolation and sharing. This specification extends OSmosis with
Bell-LaPadula/Biba multi-level security analysis, architecture refinement
verification, and attack surface quantification for seL4 Microkit systems.

## 2. Input Formats

### 2.1 Microkit System Description (XML)

```xml
<system>
    <memory_region name="NAME" size="0xSIZE" />

    <protection_domain name="NAME" priority="N">
        <program_image path="FILE.elf" />
        <map mr="REGION_NAME" vaddr="0xADDR" perms="PERMS" />
        <irq irq="N" id="N" />
    </protection_domain>

    <channel>
        <end pd="PD_NAME_1" id="N" />
        <end pd="PD_NAME_2" id="N" />
    </channel>
</system>
```

- `perms` is a subset of {r, w, x} (e.g., `"r"`, `"rw"`, `"rwx"`)
- Each `<channel>` connects exactly two protection domains
- Each `<irq>` is bound to a single protection domain

### 2.2 Security Labels (`/app/labels/<system>_labels.json`)

```json
{
  "levels": {
    "<pd_name>": {"secrecy": <int>, "integrity": <int>}
  },
  "domains": {
    "<pd_name>": "<domain_name>"
  },
  "declassifiers": {
    "<pd_name>": ["<resource_name>", ...]
  }
}
```

Higher secrecy values indicate more classified information. Higher integrity
values indicate more trusted components.

### 2.3 Abstract Architecture (`/app/architectures/<system>_arch.json`)

```json
{
  "allowed_flows": [
    ["<source_domain>", "<target_domain>"]
  ]
}
```

Each entry authorizes directed information flow from source_domain to
target_domain. Intra-domain flows (same source and target domain) are
implicitly allowed only if listed.

## 3. OSmosis Resource Graph

Construct a bipartite graph G = (P ∪ R, E):

- **P** = set of protection domains (from `<protection_domain>` elements)
- **R** = set of resources:
  - Each `<memory_region>` mapped by at least one PD is a resource
  - Each `<channel>` is a resource (named `channel_<sorted_pd1>_<sorted_pd2>`
    where pd names are sorted alphabetically)
  - IRQs are NOT resources (bound to single PDs, not shared)
- **E** = edges with capability annotations:
  - Memory region mappings: edge carries the `perms` attribute
  - Channels: both connected PDs receive `rw` capabilities

## 4. Information Flow

A **directed information flow** from PD_A to PD_B (A != B) exists when there
is a resource R such that A holds write capability (`'w'` in permissions)
to R and B holds read capability (`'r'` in permissions) to R.

The set of all such resources constitutes the **mediating resource set** for
the flow edge (A, B).

## 5. Security Metrics

### 5.1 Trusted Computing Base (TCB)

TCB(pd) = { pd' in P \ {pd} : there exists a directed information flow
path from pd' to pd }

### 5.2 Impact Boundary (IB)

IB(pd) = { pd' in P \ {pd} : there exists a directed information flow
path from pd to pd' }

### 5.3 Isolation Degree

For each unordered pair {pd_a, pd_b}:

isolation_degree(pd_a, pd_b) = |accessible_resources(pd_a) INTERSECT accessible_resources(pd_b)|

where accessible_resources(pd) includes all memory regions and channels
that pd has any capability to (regardless of permission type). IRQs excluded.

## 6. Multi-Level Security Analysis

### 6.1 BLP Violations

A direct information flow edge A -> B is a **Bell-LaPadula violation** when
secrecy(A) > secrecy(B).

For each BLP-violating edge, determine declassification status: the violation
is **declassified** if and only if A appears in the declassifiers map AND
every resource in the mediating resource set for edge (A, B) is contained
in A's declared declassification resource list.

### 6.2 Biba Violations

A direct information flow edge A -> B is a **Biba integrity violation** when
integrity(A) < integrity(B).

### 6.3 Residual Leakage

Construct the **purged flow graph** by removing all declassified BLP-violating
edges from the information flow graph. Non-violating edges and undeclassified
BLP-violating edges are retained.

For each ordered pair (A, B) where secrecy(A) > secrecy(B): if B is reachable
from A in the purged flow graph, (A, B) is a **residual leakage pair**.

## 7. Architecture Refinement

A direct information flow edge A -> B is a **refinement violation** when
domain(A) != domain(B) and the pair [domain(A), domain(B)] does not appear
in the architecture's allowed_flows list.

## 8. Attack Surface

For each resource R accessible to a PD, assign weight w(R, PD):
- If R is a channel: w = 3
- If R is a memory region and PD's capabilities include both 'r' and 'w': w = 2
- If R is a memory region and PD has only read or only write capability: w = 1

attack_surface(PD) = (SUM of w(R, PD) for all accessible R) * (|TCB(PD)| + 1)

## 9. Security Policy Evaluation

Policies are JSON arrays of policy objects. Six types are supported:

### max_tcb_size
```json
{"type": "max_tcb_size", "domain": "pd_name", "max_size": N}
```
`"pass"` if |TCB(pd)| <= max_size, else `"fail"`.

### no_flow
```json
{"type": "no_flow", "from": "src", "to": "dst"}
```
`"pass"` if no directed information flow path from src to dst exists,
else `"fail"`.

### required_isolation
```json
{"type": "required_isolation", "domain_a": "a", "domain_b": "b"}
```
`"pass"` if isolation_degree(a, b) == 0, else `"fail"`.

### blp_compliant
```json
{"type": "blp_compliant", "domain": "pd_name"}
```
`"pass"` if no undeclassified BLP-violating edge targets pd_name,
else `"fail"`.

### biba_compliant
```json
{"type": "biba_compliant", "domain": "pd_name"}
```
`"pass"` if no Biba-violating edge targets pd_name, else `"fail"`.

### arch_compliant
```json
{"type": "arch_compliant", "domain": "pd_name"}
```
`"pass"` if every direct information flow edge involving pd_name (either
as source or target) satisfies the architecture, else `"fail"`.

## 10. Output JSON Schema

Write results to `/app/output/analysis.json`:

```json
{
  "<system_name>": {
    "tcb": {
      "<pd_name>": ["<sorted_list_of_pd_names_in_tcb>"]
    },
    "impact_boundary": {
      "<pd_name>": ["<sorted_list_of_pd_names_in_ib>"]
    },
    "isolation_degree": {
      "<pd_a>,<pd_b>": <count>
    },
    "mls": {
      "blp_violations": [
        {
          "from": "<pd>",
          "to": "<pd>",
          "resources": ["<sorted_resource_names>"],
          "declassified": true_or_false
        }
      ],
      "biba_violations": [
        {
          "from": "<pd>",
          "to": "<pd>",
          "resources": ["<sorted_resource_names>"]
        }
      ],
      "residual_leakage": [
        ["<source_pd>", "<target_pd>"]
      ]
    },
    "refinement_violations": [
      {
        "from": "<pd>",
        "to": "<pd>",
        "from_domain": "<domain>",
        "to_domain": "<domain>"
      }
    ],
    "attack_surface": {
      "<pd_name>": <integer_score>
    },
    "policy_results": ["pass_or_fail", ...]
  }
}
```

### Ordering conventions

- `system_name`: XML filename without extension (e.g., `"avionics"`)
- TCB and IB lists: sorted alphabetically
- Isolation degree keys: comma-separated PD names, alphabetically sorted
  (pd_a < pd_b); include ALL unordered PD pairs, even those with degree 0
- BLP violations: sorted by (from, to); resources sorted alphabetically
- Biba violations: sorted by (from, to); resources sorted alphabetically
- Residual leakage pairs: sorted by (source, target)
- Refinement violations: sorted by (from, to)
- Policy results: ordered matching the input policy array order

## 11. Information Flow Graph Output

For each system, output a Graphviz DOT directed graph of the direct
information flow relationships.

File: `/app/output/<system_name>_flow.dot`

Requirements:
- Graph type: `digraph`, graph name: the system name
- Layout direction: `rankdir=LR`
- Node shape: `box`
- One node declaration per protection domain, sorted alphabetically
- One directed edge per `(source_pd, target_pd)` pair with a direct
  information flow
- Edge `label`: comma-separated sorted resource names mediating that flow
- Edges sorted alphabetically by `(source, target)`

Render each DOT graph to SVG:
File: `/app/output/<system_name>_flow.svg`
