A network operator suspects BGP route hijacks in their border router's routing table. Routing data from multiple sources has been collected at `/opt/routing_data/`:

- `/opt/routing_data/rib_dump.mrt` — BGP RIB snapshot in MRT binary format (RFC 6396 TABLE_DUMP_V2), as archived by the route collector
- `/opt/routing_data/collector_info.json` — Route collector metadata with BGP identifier, local AS number, and dump timestamp; MRT path attributes record the AS path as received from peers (the collector's own AS is not present in the stored path)
- `/opt/routing_data/rpki_cache.db` — SQLite database from a relying party validator containing a `validated_roa_payloads` table (note: this cache reflects only one trust anchor and does not contain the complete set of ROAs)
- `/opt/routing_data/rpki_objects/` — Directory of ASN.1 DER-encoded ROA payload files (RFC 6482 RouteOriginAttestation structure, without CMS envelope) containing additional validated ROA data not present in the SQLite cache
- `/opt/routing_data/rrdp_snapshot.xml` — RPKI Repository Delta Protocol (RFC 8182) snapshot XML from a separate trust anchor; each `<publish>` element contains a base64-encoded DER RouteOriginAttestation payload
- `/opt/routing_data/irr_objects.tar.gz` — Internet Routing Registry export: a gzipped tarball of RPSL-formatted `route:` and `route6:` objects
- `/opt/routing_data/aspa_authorizations.csv` — ASPA (Autonomous System Provider Authorization) registrations exported as CSV

All RPKI data sources (SQLite cache, DER object files, and RRDP snapshot) must be combined to form the complete set of Validated ROA Payloads (VRPs) before performing origin validation. Using only the SQLite cache will yield incorrect results.

Cross-reference all data sources to produce a routing security assessment. Write results to `/app/analysis_results.json` as a JSON object with exactly these keys (all integer values):

- `total_routes` — total BGP route entries in the RIB (each distinct prefix+path combination)
- `rpki_valid` — routes with valid RPKI origin authorization per RFC 6811
- `rpki_invalid` — routes covered by ROAs but failing origin validation
- `rpki_invalid_as` — invalid due to unauthorized origin AS
- `rpki_invalid_length` — invalid due to prefix length exceeding maxLength
- `rpki_not_found` — routes with no RPKI coverage
- `rpki_unsafe_maxlength` — ROAs where maxLength exceeds the prefix length by 8 or more
- `rpki_conflicting_prefixes` — distinct prefixes with ROAs authorizing multiple origin ASes
- `rpki_redundant_roas` — ROAs fully subsumed by a more general ROA for the same AS
- `aspa_valid` — routes with fully authorized AS paths (full path from collector through to origin)
- `aspa_invalid` — routes with at least one unauthorized provider hop
- `aspa_unknown` — routes where no hop is unauthorized but at least one lacks ASPA coverage
- `irr_registered` — routes whose exact prefix has an IRR route object
- `irr_origin_match` — IRR-registered routes where BGP origin matches IRR origin
- `irr_origin_mismatch` — IRR-registered routes where BGP origin differs from IRR origin
- `multi_signal_hijack_candidates` — routes flagged by at least 2 of: RPKI invalid, ASPA invalid, IRR origin mismatch