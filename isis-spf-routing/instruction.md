An IS-IS Level-2 Link State Database captured from a multi-router network is stored in a SQLite database at `/app/isis_lsdb.db`. A YANG module at `/app/isis-rib.yang` defines the schema for the routing table output.

Compute the IS-IS SPF routing table for the source router and produce `/app/routing_table.json`.

## Database schema

The SQLite database contains these tables:

- `config` — key-value parameters; `source_router` gives the SPF root's system-ID.
- `lsp_entries` — LSP headers with `lsp_id`, `remaining_lifetime`, and `overload` flag.
- `is_adjacencies` — IS-neighbor TLVs with `lsp_id`, `neighbor_id`, and `metric`.
- `ipv4_prefixes` — IPv4 reachability TLVs with `lsp_id`, `address`, `prefix_length`, and `metric` (address and prefix_length are separate columns; combine them as CIDR).

LSP IDs follow the format `SSSS.SSSS.SSSS.PP-FF` where `PP` is the pseudonode byte and `FF` is the fragment number.

## Output format

The output must use RFC 7951 JSON encoding with the YANG module `isis-rib`. The top-level key must be `isis-rib:routing-table` (module-name:container-name namespacing). The structure:

```json
{
  "isis-rib:routing-table": {
    "source-router": "<system-id of SPF root>",
    "route": [
      {
        "destination-prefix": "<A.B.C.D/N>",
        "total-metric": <integer>,
        "forwarding-next-hop": ["<system-id>", ...]
      }
    ]
  }
}
```

- `source-router`: the system-ID from the `config` table (format `XXXX.XXXX.XXXX`).
- `destination-prefix`: IPv4 prefix in CIDR notation.
- `total-metric`: cost-to-advertising-router plus the prefix metric from the LSDB.
- `forwarding-next-hop`: first-hop system-ID(s) toward the destination. When multiple equal-cost paths exist, list all distinct first-hop routers. Entries must be sorted in ascending lexicographic order. System-IDs use the three-dotted-group format `XXXX.XXXX.XXXX` (no pseudonode byte).

## SPF computation requirements

The computation must correctly handle:

- **LSP fragment aggregation**: Multiple LSP fragments from the same node (e.g., `SSSS.SSSS.SSSS.PP-00` and `SSSS.SSSS.SSSS.PP-01`) must be merged — adjacencies and prefixes from all fragments contribute to a single node.
- **Expired LSP purging**: LSPs with `remaining_lifetime = 0` must be entirely excluded from SPF — no routes from those nodes may appear.
- **Overload bit (OL) handling**: A router with the overload bit set must not be used as transit (do not expand its IS-neighbor links during SPF). However, prefixes directly advertised by the overloaded router remain reachable at their computed cost (cost-to-overloaded-node + prefix metric).
- **Pseudonode / LAN segment handling**: Broadcast (LAN) segments are represented by pseudonode LSPs (non-zero pseudonode byte in the node-ID). During SPF, pseudonodes are traversed normally, but forwarding next-hops in the output must be resolved to real router system-IDs — pseudonode IDs must never appear in `forwarding-next-hop`.
- **ECMP (Equal-Cost Multi-Path)**: Track all equal-cost first-hops at the node level. When a destination prefix is advertised by multiple routers at the same minimum total cost, merge the first-hop sets from all advertisers.
- **Connected route exclusion**: Exclude any prefix where the source router's own advertised cost is less than or equal to the best remote cost.

Pre-installed tools: `sqlite3`, `pyang`.