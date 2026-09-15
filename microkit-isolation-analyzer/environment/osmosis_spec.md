# OSmosis Isolation Model Specification

This document defines the OSmosis-style isolation analysis to be performed on
a seL4 Microkit system description.

## 1. Input: Microkit System Description

The system description (`/app/system.xml`) is an XML file conforming to the
seL4 Microkit format. The relevant elements are:

- `<memory_region name="..." size="0x..." />` — declares a shared memory region.
- `<protection_domain name="..." priority="...">` — declares a protection domain (PD).
  PDs may be nested: a `<protection_domain>` inside another `<protection_domain>`
  defines a **child PD**. The outer PD is the **parent**.
- `<map mr="..." vaddr="0x..." perms="..." />` — maps a memory region into a PD.
  The `perms` attribute is a string containing any combination of `r`, `w`, `x`.
  A PD has **write access** if the `perms` string contains the character `w`.
  Otherwise the PD has **read-only access**.
- `<channel>` — declares a bidirectional communication channel between two PDs,
  each identified by `<end pd="..." id="..." />`.
- `<irq irq="..." id="..." />` — declares a hardware interrupt bound to a PD.
  IRQs do not create inter-PD dependencies; they are device resources.
- `<program_image>`, `<virtual_machine>`, and other elements should be ignored
  for the purposes of this analysis.

## 2. OSmosis Dependency Graph Construction

Construct a **directed dependency graph** where nodes are protection domains
and edges represent dependencies. PD **X depends on PD Y** (edge X → Y) if
any of the following conditions hold:

### Rule 1: Shared Memory (Write Exposure)
Y has **write access** (`w` in perms) to a memory region **R**, and X also
maps **R** (with any permissions). Y can modify data that X relies on,
so X depends on Y.

### Rule 2: Channel Communication
There exists a `<channel>` with endpoints in both X and Y. Channels are
bidirectional, so this creates edges in **both** directions: X → Y and Y → X.

### Rule 3: Parent-Child Relationship
Y is the **parent** PD of X (X is defined as a nested `<protection_domain>`
inside Y). The child depends on the parent because the parent controls the
child's lifecycle. This creates a **one-way** edge: X → Y (child depends on
parent).

**Important:** If multiple rules produce the same edge, it appears only once
in the graph. Self-loops (X → X) are excluded.

## 3. Trusted Computing Base (TCB)

The **TCB of PD X** is the set of all protection domains Y (Y ≠ X) such that
X **transitively depends** on Y. Formally, it is the transitive closure of the
dependency relation starting from X, excluding X itself.

Compute the TCB via breadth-first or depth-first traversal of the dependency
graph from X, following outgoing edges.

## 4. Impact Boundary

The **impact boundary of PD X** is the set of all protection domains Y (Y ≠ X)
such that X is in the TCB of Y. In other words, if X were compromised, all PDs
in its impact boundary would be affected.

## 5. Shared Resources

For each memory region mapped by **two or more** protection domains, classify
the PDs into:
- **writers**: PDs whose `perms` contain `w`
- **readers**: PDs whose `perms` do not contain `w`

## 6. Security Policy Checking

The security policy (`/app/policy.json`) defines three types of constraints:

### isolated_pairs
A list of PD pairs `[A, B]` that must be fully isolated: neither A may be in
the TCB of B, nor B in the TCB of A. Report a violation for each pair where
this condition fails.

### max_tcb_size
A mapping from PD name to maximum allowed TCB size. Report a violation if the
actual TCB size exceeds the limit.

### max_impact_size
A mapping from PD name to maximum allowed impact boundary size. Report a
violation if the actual impact boundary size exceeds the limit.

## 7. Output Format

Write the analysis results to `/app/report.json` with the following structure.
**All lists must be sorted alphabetically** for determinism.

```json
{
  "protection_domains": ["<sorted list of all PD names>"],

  "dependency_graph": {
    "<pd_name>": ["<sorted list of PDs this PD directly depends on>"],
    ...
  },

  "tcb": {
    "<pd_name>": ["<sorted list of PDs in this PD's TCB>"],
    ...
  },

  "impact_boundary": {
    "<pd_name>": ["<sorted list of PDs in this PD's impact boundary>"],
    ...
  },

  "shared_resources": {
    "<region_name>": {
      "writers": ["<sorted list of PDs with write access>"],
      "readers": ["<sorted list of PDs with read-only access>"]
    },
    ...
  },

  "policy_violations": {
    "isolation_violations": [
      {
        "pair": ["<pd_a>", "<pd_b>"],
        "first_in_tcb_of_second": <bool>,
        "second_in_tcb_of_first": <bool>
      },
      ...
    ],
    "tcb_size_violations": [
      {"pd": "<name>", "actual_size": <int>, "max_allowed": <int>},
      ...
    ],
    "impact_size_violations": [
      {"pd": "<name>", "actual_size": <int>, "max_allowed": <int>},
      ...
    ]
  }
}
```

Notes:
- `isolation_violations`: each `pair` is sorted alphabetically. The list of
  violations is also sorted by pair. `first_in_tcb_of_second` is true when
  the alphabetically-first PD is in the TCB of the second.
  `second_in_tcb_of_first` is true when the second PD is in the TCB of the
  first.
- `tcb_size_violations` and `impact_size_violations`: sorted by PD name.
- Only include memory regions in `shared_resources` that are mapped by at
  least two distinct protection domains.
