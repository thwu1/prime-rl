A 6-router enterprise network has Cisco IOS-XE running configurations at `/app/network/configs/` (R1.cfg through R6.cfg), a physical topology at `/app/network/topology.json`, and an authoritative network design specification stored in a SQLite database at `/app/network/design.db`. The design database contains intended state across multiple normalized tables covering OSPF parameters, BGP sessions, redistribution policies, security features, IP allocations, and traffic-flow SLA definitions.

A Cisco DNA Center API simulator is installed at `/app/dnac/`. Start it with `/app/dnac/start.sh` and access it at `http://localhost:9443`. Credentials: `admin` / `Cisco123!`. The DNA Center manages a subset of network devices and provides compliance assessments, assurance-detected issues, site hierarchy, and health scores through its REST API (token-based auth: `POST /dna/system/api/v1/auth/token` with HTTP Basic, then pass the returned token as `X-Auth-Token` header). Several configuration errors exist. The DNA Center's compliance engine has detected some but not all deviations, and reports at least one finding not substantiated by the design database.

Audit every configuration against both the design database and DNA Center API data, then produce the following nine output artifacts in `/app/output/`:

- **adjacency_audit.json** — Every routing-protocol adjacency that will fail to form, with the specific parameter mismatch and its operational impact.
- **redistribution_audit.json** — All route redistribution points lacking the loop-prevention controls specified in the design database.
- **bgp_audit.json** — BGP operational issues found by comparing actual BGP config against the design database.
- **security_audit.json** — Security features required by the design database but missing from the actual configurations.
- **ip_plan_audit.json** — Compare every actual interface IP assignment against the design database. Report each planned allocation as matching or deviating.
- **path_analysis.json** — For each traffic flow in the design database, determine the Layer 3 forwarding path assuming adjacency issues are corrected, using configured OSPF costs. Report unreachable flows with reason.
- **remediation.json** — Exact IOS-XE CLI commands to fix every issue found.
- **topology.svg** — SVG network topology diagram with all routers, links with OSPF costs, and red-colored links for adjacency issues with annotations.
- **dnac_reconciliation.json** — Three-way reconciliation of DNA Center compliance/assurance data against the design database and actual configurations. For each managed device, classify findings as true positive (DNAC correctly identified a real issue), false negative (DNAC missed a real issue), or false positive (DNAC reported an issue not in the design spec). List devices absent from the DNA Center inventory as unmanaged.

Consult `/app/network/requirements.json` for the precise JSON schema each output file must follow.