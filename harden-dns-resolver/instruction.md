A DNS resolver at `/app/resolver.py` performs iterative resolution from root nameservers using only the Python standard library. It was deployed as part of an internal tool but has been flagged for multiple issues:

- Many domains that resolve correctly with system DNS fail silently or return no result through this resolver
- The resolver occasionally hangs indefinitely on certain inputs
- A preliminary security review raised concerns about the resolver's susceptibility to protocol-level attacks on DNS

No detailed bug reports or failing domain lists exist. You must independently audit the resolver's correctness, security posture, and protocol conformance by examining its code and testing its behavior against live DNS infrastructure.

**Deliverables:**

1. Fix all defects in `/app/resolver.py`. Use only the Python standard library. Preserve the module's public API: functions `build_query()`, `parse_dns_packet()`, `send_query()`, and `resolve()` must retain their existing signatures and return types. The dataclasses `DNSHeader`, `DNSQuestion`, `DNSRecord`, `DNSPacket` and the constants `TYPE_A`, `TYPE_NS`, `TYPE_CNAME`, `TYPE_OPT`, `CLASS_IN` must remain importable.

2. Write a comprehensive security and conformance audit report to `/app/audit.json` conforming to this schema:

```json
{
  "findings": [
    {
      "id": "<kebab-case-identifier>",
      "category": "<vulnerability|protocol_violation|missing_feature>",
      "severity": "<critical|high|medium>",
      "description": "<description of the issue>",
      "rfc_reference": "<RFC number or N/A>",
      "remediation": "<description of the fix applied>"
    }
  ],
  "risk_assessment": "<critical|high|medium|low — overall pre-fix risk level>",
  "test_methodology": "<brief description of how you investigated>"
}
```

The report must document every defect discovered and fixed, categorized by type and severity, with RFC references where applicable. After your fixes, the resolver must correctly handle the full range of DNS protocol features encountered during real-world iterative resolution and be resilient to known protocol-level attacks.