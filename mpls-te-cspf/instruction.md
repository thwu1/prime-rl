A five-router ISP backbone running IS-IS with MPLS traffic engineering needs its RSVP-TE signaling outcomes computed offline and correlated with the operator's Network Management System data.

**Input data:**

- **Router configurations** in Junos `set`-command format: `/app/configs/{A,B,C,D,E}.conf`
- **IS-IS Traffic Engineering Database** in Junos RPC XML format (namespace `http://xml.juniper.net/junos/21.4R3/junos-routing`): `/app/ted_database.xml`. The XML is wrapped in an `<rpc-reply>` envelope; all TED elements are in the Junos routing namespace. Use `xmlstarlet` (pre-installed) or namespace-aware XML parsing to extract topology data.
- **NMS operational database** (SQLite): `/app/nms.db`. Query with `sqlite3` (pre-installed). Contains:
  - `link_pricing(link_key TEXT, cost_per_gbps_month INTEGER)` — per-link transport cost
  - `srlg_risk_scores(srlg_id INTEGER, risk_score REAL, description TEXT)` — per-SRLG failure probability
  - `customer_circuits(lsp_name TEXT, customer TEXT, sla_tier TEXT)` — customer/SLA mapping
- **LSP signaling order**: `/app/lsp_order.txt`

Seven RSVP-TE LSPs are configured across the ingress routers. Simulate CSPF path computation and sequential RSVP-TE signaling in the order listed. Write network state and NMS reports to `/app/results.json`. Generate a topology diagram at `/app/topology.svg` using Graphviz `dot` (pre-installed).

The network uses standard CSPF and RSVP-TE semantics: admin-group affinity constraints, SRLG-diverse path computation, shared bandwidth reservation per undirected link, and setup/hold priority preemption (RFC 3209, RFC 4124). Bandwidth values in the TED are in bits per second; LSP configs use Junos notation (e.g. `7g`).

Determinism rules for tiebreaking:
- Path selection: minimum IGP cost, then fewest hops, then lexicographically smallest router-name sequence
- Preemption targets: highest hold\_priority number first, then alphabetically earliest LSP name; minimum set preempted
- Link preemption evaluation order: alphabetical by link key

**Output `/app/results.json`:**
```json
{
  "lsp_results": [...],
  "link_utilization": {...},
  "billing_summary": [...],
  "risk_assessment": [...]
}
```

`lsp_results` array (signaling order): `"name"`, `"status"` (`"established"` / `"failed"` / `"preempted"`), `"path"` (router list or `[]`), `"cost"` (IGP cost or `0`). Preempted LSPs include `"preempted_by"`.

`link_utilization` object keyed by alphabetically-sorted hyphen-joined endpoint names: `"capacity"`, `"reserved"`, `"available"` in Gbps (integer).

`billing_summary` array (signaling order, all 7 LSPs): `"lsp_name"`, `"customer"`, `"sla_tier"` (from NMS `customer_circuits`), `"bandwidth_gbps"` (reserved, 0 if not established), `"monthly_cost_usd"` (bandwidth × sum of per-link `cost_per_gbps_month` from NMS `link_pricing` along the path; 0 if not established).

`risk_assessment` array (signaling order, all 7 LSPs): `"lsp_name"`, `"path_srlgs"` (sorted list of unique SRLG IDs on path, `[]` if not established), `"max_risk_score"` (highest `risk_score` from NMS `srlg_risk_scores` among path SRLGs; `0.0` if not established).

**Output `/app/topology.svg`:** Graphviz-rendered SVG topology diagram. Each router is a labeled node. Each link is an edge labeled with reserved/capacity utilization. Established LSP paths must be visually distinguishable (e.g. colored overlay edges). Generate DOT source, then render: `dot -Tsvg`.