A production Linux server running a connection-heavy application experienced a compound network incident involving multiple concurrent failure modes. During the event, the server exhibited connection failures, packet drops, and service degradation across both inbound and outbound traffic paths.

Post-incident diagnostic snapshots were captured and are available in `/app/data/`. These include kernel parameter dumps, socket state captures at various granularities, netfilter counter snapshots at multiple processing stages, kernel TCP/IP MIB counters, application error logs, kernel ring buffer messages, and a binary packet capture of ingress traffic taken at the network interface.

The organization's mitigation policy defining remediation requirements is at `/app/data/policy_requirements.txt`. The expected report field schema is at `/app/data/report_schema.json`.

## Deliverables

1. `/app/report.json` — A structured incident analysis report conforming to the schema. Every field is required. You must determine what each field represents and how to derive it from the available evidence and the mitigation policy.

2. `/app/mitigation.nft` — A complete, syntactically valid nftables ruleset (loadable via `nft -f`) that implements packet-level traffic filtering mitigations for this incident, based on your analysis findings and the organizational policy.