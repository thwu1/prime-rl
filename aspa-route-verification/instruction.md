A regional ISP suspects that its RPKI/ASPA cache has been partially compromised. The operational data — network topology, published ASPA attestations with their signing certificates, and recent BGP route observations — resides in a SQLite database at `/app/rpki_cache.db`. Each ASPA attestation's signing certificate is a PEM file referenced by path in the database.

Produce `/app/audit.json` conforming to the schema at `/app/output_schema.json` with these four sections:

- **erroneous_objects**: Every ASPA attestation whose signing certificate is no longer valid or whose provider set contradicts the actual network topology. Report the specific provider-set discrepancies for each.

- **corrected_aspa**: The definitive ASPA database covering every customer ASN that published an attestation. Provider sets must reflect the actual transit relationships in the topology.

- **route_analysis**: Verification outcome for every BGP route observation in the database, including verification direction, result classification, and leak attribution for invalid routes.

- **deployment_recommendation**: Additional ASes (those without existing attestations) whose ASPA deployments would eliminate the greatest number of unresolved route verification outcomes. Order by impact, breaking ties by ascending ASN.

ASPA verification algorithm reference: `/app/aspa_reference.md`