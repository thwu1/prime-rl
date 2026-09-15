Perform a security audit of the RPKI repository at `/app/rpki_repo/` against BGP routing data at `/app/bgp_data/`.

The repository contains a trust anchor certificate (`ta.pem` / `ta.cer`) and a set of CMS-signed (PKCS#7, DER-encoded) Route Origin Authorization objects under `roas/`. ASPA customer-provider authorization records are in `aspa_records.json`. The BGP routing table is a binary MRT TABLE_DUMP_V2 dump (RFC 6396) at `/app/bgp_data/rib.mrt`.

Your audit must cryptographically verify each CMS-signed ROA against the trust anchor — reject any ROA whose signature chain does not trace to the trust anchor. Extract the verified ROA payloads. Parse all BGP route announcements from the MRT binary dump (prefixes, origin AS, full AS path). For each route, determine Route Origin Validation status per RFC 6811 and ASPA upstream path verification status. Apply combined policy: REJECT if ROV is Invalid or ASPA is Invalid; ACCEPT otherwise.

Write results to `/app/results/audit_report.json`:

```json
{
  "roa_verification": {
    "total": "<number of CMS files examined>",
    "valid": "<number that passed chain-of-trust verification>",
    "invalid": "<number that failed>",
    "invalid_files": ["<filename that failed>"]
  },
  "route_validations": [
    {
      "route_id": 1,
      "prefix": "10.0.1.0/24",
      "origin_as": 64512,
      "as_path": [64512, 64500],
      "rov_status": "Valid",
      "aspa_status": "Valid",
      "policy": "ACCEPT"
    }
  ]
}
```

Route IDs are 1-based, sequential in MRT parse order. `rov_status`: `Valid`, `Invalid`, or `NotFound`. `aspa_status`: `Valid`, `Invalid`, or `Unknown`. All routes use upstream ASPA verification (received from customer peer).