Six interrelated OSCAL documents in `/app/` model a security compliance lifecycle spanning control definition, baseline selection, system implementation, assessment, and remediation tracking. Analyze these documents and produce a reconciliation report that identifies compliance posture across all layers.

**Documents in `/app/`:**
- `catalog.xml` — Security control catalog (OSCAL XML format)
- `profile_low.json` — Low-impact baseline profile
- `profile_moderate.json` — Moderate-impact baseline profile
- `ssp.json` — System Security Plan
- `assessment_results.json` — Assessment findings, observations, and risks
- `poam.json` — Plan of Action and Milestones

Produce `/app/reconciliation_report.json` with the following ten sections:

1. `catalog_control_ids` — Sorted list of every control identifier defined in the catalog, including control enhancements
2. `effective_controls` — Sorted list of control IDs comprising the fully-resolved Moderate baseline
3. `implementation_gaps` — Sorted control IDs required by the effective baseline but absent from the SSP
4. `stale_implementations` — Sorted control IDs present in the SSP but not required by the effective baseline
5. `broken_component_refs` — Array sorted by `(control_id, statement_id)` of objects `{control_id, statement_id, component_uuid}` identifying SSP implementation statements that reference system components not declared in the SSP
6. `parameter_gaps` — Array sorted by `(control_id, param_id)` of objects `{control_id, param_id}` identifying baseline-mandated parameters absent from the corresponding SSP control implementation
7. `statement_coverage_gaps` — Array sorted by `control_id` of objects `{control_id, missing_statements}` identifying controls whose SSP implementation omits top-level statement parts defined in the catalog
8. `finding_control_map` — Array sorted by `finding_uuid` of objects `{finding_uuid, target_control_id, finding_status, control_in_baseline, control_implemented, has_poam_entry, poam_status}` correlating each assessment finding with baseline membership, SSP implementation status, and POA&M tracking
9. `untracked_risks` — Sorted UUIDs of assessment risks not covered by any POA&M item
10. `remediation_coverage` — Object `{total_poam_items, valid_poam_items, orphaned_poam_items, risks_tracked, risks_untracked}` summarizing POA&M coverage; valid items reference risks present in assessment results, orphaned items do not