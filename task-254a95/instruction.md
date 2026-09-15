A dn42 registry mirror at `/app/registry/` has been flagged for a security review after reports of unauthorized route announcements in the overlay network. The registry is a **git repository** with multiple commits spanning several months of modifications.

The registry follows the dn42 data model: RPSL-like plain-text objects under `data/` organized by type (`mntner`, `person`, `aut-num`, `inetnum`, `inet6num`, `route`, `route6`, `dns`). Each object file contains `key: value` attributes, with continuation lines indicated by leading whitespace. Lines starting with `#` are comments. The dn42 trust model uses maintainer objects (`mntner`) as the root of authorization chains — address allocations (`inetnum`/`inet6num`) may delegate sub-allocation authority via `mnt-lower`, and route announcements must be authorized by the entity controlling the covering address space. Autonomous system objects declare BGP peering policy through `import`/`export` attributes using RPSL syntax (`import: from <AS> accept <filter>`).

Perform a comprehensive security audit covering the full registry object graph: referential integrity of all cross-references, authorization chain validation for route objects against their covering allocations, BGP peering policy reference consistency, route containment within allocated address space, and ROA constraint compliance. Use git forensics to trace each finding to the commit that introduced it. The networking tool `sipcalc` is available for CIDR arithmetic.

Write your findings to `/app/forensic_report.json`:

```json
{
  "registry_summary": {
    "object_counts": {"<type>": <count>, ...},
    "total_objects": <int>
  },
  "violations": [
    {
      "category": "<descriptive_snake_case>",
      "object": "<path_relative_to_registry_root>",
      "detail": "<specific invalid reference, value, or authorization failure>",
      "introduced_in": "<full commit message>"
    }
  ],
  "network_analysis": {
    "ipv4_allocations": [
      {"cidr": "<cidr>", "usable_hosts": <int>}
    ],
    "total_ipv4_usable_hosts": <int>,
    "ipv6_allocations": [
      {"cidr": "<cidr>", "prefix_length": <int>}
    ]
  },
  "routing_security": {
    "roa_entries": [
      {"prefix": "<prefix>", "origin": "<AS>", "max_length": <int>, "authorized": <bool>}
    ],
    "authorized_count": <int>,
    "unauthorized_count": <int>
  },
  "total_violations": <int>
}
```

Report exactly the violations present — no false positives. The `object` field must be relative to the registry root (e.g., `data/route/172.20.10.0_24`). The `detail` field must name the specific entity (mntner, person, AS, prefix) that constitutes the violation. A route is `authorized` in the ROA table if a covering allocation exists, the route's maintainer is authorized by the allocation holder (matching `mnt-by` or listed in `mnt-lower`), and the route's origin AS is registered.