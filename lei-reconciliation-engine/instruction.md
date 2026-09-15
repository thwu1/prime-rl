A portfolio at `/app/data/portfolio.json` lists financial entities identified through heterogeneous identifiers: LEI codes, BIC (SWIFT) codes, and entity names. Each entry has `id`, `identifier`, and `type` fields.

Resolve all identifiers to canonical GLEIF LEI records, build verified ownership chains by recursively traversing parent relationships, assess relationship data quality through corroboration analysis, and produce a forensic report at `/app/output/forensics.json`.

## Output schema

**`entities`** — one object per input entry:
- `id`, `input_identifier`, `input_type`
- `resolved_lei` (null if unresolvable), `resolution_method` (one of `checksum_validated`, `bic_lookup`, `fulltext_search`, `invalid`)
- `checksum_valid` (boolean for LEI-type inputs; null for other types)
- GLEIF attributes: `entity_name`, `jurisdiction`, `entity_status`, `registration_status`, `conformity_flag`, `bic_codes` (list)
- Counts: `isin_count`, `direct_children_count`
- Ownership chain: `parent_chain` (ordered LEI list from direct parent up to chain root), `chain_depth`, `claimed_ultimate_parent_lei`, `chain_consistent` (boolean — does traversing direct-parent links terminate at the claimed ultimate parent?)
- Relationship quality of the direct-parent link: `corroboration_level`, `relationship_registration_status` (null for parentless entities)
- `has_reporting_exception` (boolean), `exception_reason` (for parentless entities; null otherwise)

For unresolvable entries, GLEIF-sourced fields should be null/zero/empty.

**`clusters`** — mapping from ultimate parent LEI to:
- `member_ids`, `member_leis`
- `jurisdictions` (sorted unique list)
- `max_chain_depth`, `total_isin_exposure`, `total_direct_children`
- `data_quality_score`: mean corroboration score across parent relationships in the cluster (FULLY_CORROBORATED=1.0, PARTIALLY_CORROBORATED=0.5, ENTITY_SUPPLIED_ONLY=0.0; null if no parent relationships exist in the cluster)

Entities without parents are their own ultimate parent.

**`unresolved`** — list of input entry IDs that could not be resolved.

**`summary`** — `total_entries`, `resolved_count`, `unresolved_count`, `cluster_count`, `entities_with_parents`, `total_chain_depth`, `total_isin_exposure`, `total_direct_children`

The GLEIF public API base is `https://api.gleif.org/api/v1/` and follows the JSON:API specification.