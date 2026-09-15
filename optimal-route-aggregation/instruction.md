Implement an IPv4 Forwarding Information Base (FIB) manager as an executable at `/app/fib_manager`.

The program reads operations line-by-line from stdin and writes results to stdout. Supported operations:

- `INSERT <prefix>/<len> <nexthop>` — insert or replace a route. Nexthop is an integer 0-255. Prefix is in canonical CIDR form (host bits zero).
- `DELETE <prefix>/<len>` — remove the exact route. No-op if it doesn't exist. No output.
- `LOOKUP <ip>` — print the nexthop of the longest matching prefix, or `NONE` if no prefix matches.
- `AGGREGATE` — print the optimal (minimum-entry-count) CIDR routing table that produces identical longest-prefix-match results for all 2^32 IPv4 addresses. First line of output is the entry count. Following lines: `<prefix>/<len> <nexthop>`, sorted by prefix address ascending then prefix length ascending. AGGREGATE is read-only and does not modify the internal routing table.

The aggregated table must be provably minimal. Naive greedy merging of sibling prefixes is insufficient. The optimal solution may require "promoting" routes to shorter prefixes and adding more-specific exceptions, yielding fewer total entries than any bottom-up-only merge strategy. The Optimal Routing Table Constructor (ORTC) algorithm or equivalent is required.

The program must handle routing tables with up to 50,000 entries and process 200,000 LOOKUP operations within 60 seconds. See `/app/spec.txt` for format details, edge-case specifications, and worked examples.